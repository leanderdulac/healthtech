import json
import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.export import VertexDataExporter
from src.integrations.vertex.feature_builder import DatalakeFeatureBuilder
from src.integrations.vertex.local_model import LocalAnomalyModel
from src.ml_pipeline.batch_inference import orquestrar_batch_vertex_ai

logger = logging.getLogger(__name__)


class VertexBatchPipeline:
    """
    Pipeline de inferência batch: extrai coorte do datalake Gold,
    exporta JSONL e submete job no Vertex AI (ou executa localmente).
    """

    def __init__(
        self,
        config: VertexConfig,
        feature_builder: DatalakeFeatureBuilder,
        exporter: VertexDataExporter,
        local_model: Optional[LocalAnomalyModel] = None,
    ):
        self.config = config
        self.feature_builder = feature_builder
        self.exporter = exporter
        self.local_model = local_model or LocalAnomalyModel(config.local_model_dir)

    def run_batch_prediction(
        self,
        min_risk_score: float = 0.0,
        partition_dates: Optional[list] = None,
    ) -> Dict:
        features = self.feature_builder.build_batch_features(
            min_risk_score=min_risk_score,
            partition_dates=partition_dates,
        )

        if features.empty:
            return {"status": "NO_DATA", "mensagem": "Nenhuma feature disponível no datalake"}

        jsonl_path = self.exporter.export_batch_jsonl(features)
        upload_info = self.exporter.get_gcs_upload_instructions(jsonl_path)

        local_predictions = self._run_local_batch(features)
        local_output = self.config.local_export_dir / "batch_predictions.jsonl"
        self._save_local_predictions(local_predictions, local_output)

        vertex_result = {"status": "SKIPPED", "mensagem": "GCP não configurado"}
        if self.config.is_gcp_configured:
            gcs_input = upload_info["gcs_uri"]
            vertex_result = orquestrar_batch_vertex_ai(
                project=self.config.project_id,
                location=self.config.location,
                model_name=self.config.model_name,
                gcs_input_uri=gcs_input,
                gcs_output_uri=self.config.gcs_output_uri,
                machine_type=self.config.machine_type,
            )
        else:
            vertex_result = orquestrar_batch_vertex_ai(
                project=self.config.project_id,
                location=self.config.location,
                model_name=self.config.model_name,
                gcs_input_uri=str(jsonl_path),
                gcs_output_uri=str(self.config.local_export_dir / "vertex_output"),
                machine_type=self.config.machine_type,
            )

        anomalies = int(local_predictions["is_anomaly"].sum()) if not local_predictions.empty else 0

        return {
            "status": vertex_result.get("status", "COMPLETED"),
            "input_records": len(features),
            "local_anomalies": anomalies,
            "jsonl_path": str(jsonl_path),
            "local_predictions_path": str(local_output),
            "gcs_upload": upload_info,
            "vertex_job": vertex_result,
        }

    def _run_local_batch(self, features: pd.DataFrame) -> pd.DataFrame:
        if not self.local_model.is_trained:
            self.local_model._load()
        return self.local_model.predict_batch(features)

    @staticmethod
    def _save_local_predictions(predictions: pd.DataFrame, output_path: Path) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            for _, row in predictions.iterrows():
                record = {
                    "patient_id": row.get("patient_id"),
                    "is_anomaly": bool(row.get("is_anomaly", False)),
                    "anomaly_score": float(row.get("anomaly_score", 0)),
                    "clinical_risk_level": row.get("clinical_risk_level", "unknown"),
                    "modo": row.get("modo", "local"),
                }
                f.write(json.dumps(record) + "\n")
        logger.info("Predições batch locais salvas: %s", output_path)