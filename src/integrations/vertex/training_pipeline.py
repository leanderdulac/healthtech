import logging
from typing import Dict, Optional

from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.export import VertexDataExporter
from src.integrations.vertex.feature_builder import DatalakeFeatureBuilder
from src.integrations.vertex.local_model import LocalAnomalyModel
from src.ml_pipeline.training import orquestrar_custom_training

logger = logging.getLogger(__name__)


class VertexTrainingPipeline:
    """
    Pipeline de treinamento: prepara features do datalake Gold
    e treina modelo local + opcionalmente submete CustomTrainingJob no Vertex.
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

    def run_training(self, partition_dates: Optional[list] = None) -> Dict:
        features = self.feature_builder.build_batch_features(
            min_risk_score=0.0,
            partition_dates=partition_dates,
        )

        if features.empty:
            return {"status": "NO_DATA", "mensagem": "Sem features para treino"}

        csv_path = self.exporter.export_training_csv(features)
        local_result = self.local_model.train(features)

        vertex_result = {"status": "SKIPPED"}
        if self.config.is_gcp_configured:
            try:
                job = orquestrar_custom_training(
                    project_id=self.config.project_id,
                    location=self.config.location,
                    gcs_staging_bucket=self.config.staging_bucket,
                )
                vertex_result = {
                    "status": "SUBMITTED",
                    "job": str(job) if job else None,
                }
            except Exception as e:
                vertex_result = {"status": "FAILED", "error": str(e)}
                logger.warning("Vertex CustomTraining falhou: %s", e)

        return {
            "status": "COMPLETED",
            "training_samples": len(features),
            "csv_path": str(csv_path),
            "local_model": local_result,
            "vertex_training": vertex_result,
        }