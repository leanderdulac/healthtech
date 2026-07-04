import logging
from typing import Dict, Optional

from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.export import VertexDataExporter
from src.integrations.vertex.feature_builder import DatalakeFeatureBuilder
from src.integrations.vertex.local_model import LocalAnomalyModel
from src.clinical_intelligence.temporal_features import TemporalFeatureBuilder
from src.clinical_intelligence.temporal_model import TemporalModelWrapper
from src.ml_pipeline.training import orquestrar_custom_training
from src.ontology.registry import MedicalOntologyRegistry

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
        temporal_result = self._train_temporal_model(partition_dates)

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

        ontology_info = {"status": "NOT_LOADED"}
        registry = MedicalOntologyRegistry()
        if registry.load():
            ontology_info = {
                "status": "LOADED",
                "keywords": len(registry.get_top_keywords(999)),
                "areas": len(registry.get_top_areas(999)),
                "statistics": registry.statistics,
            }

        return {
            "status": "COMPLETED",
            "training_samples": len(features),
            "csv_path": str(csv_path),
            "local_model": local_result,
            "temporal_model": temporal_result,
            "vertex_training": vertex_result,
            "ontology": ontology_info,
        }

    def _train_temporal_model(self, partition_dates: Optional[list] = None) -> Dict:
        profiles = []
        try:
            store = self.feature_builder.query_engine.store
            from src.datalake.schemas.base import DataLayer
            daily = store.read_layer(layer=DataLayer.GOLD, table="daily_summary", partition_dates=partition_dates)
            if not daily.empty:
                from src.datalake.utils.telemetry_simulator import TelemetrySimulator, SimulationConfig
                sim = TelemetrySimulator(SimulationConfig(num_patients=len(daily["patient_id"].unique())))
                profiles = [p for p in sim.patient_profiles if p.patient_id in daily["patient_id"].values]
        except Exception as e:
            logger.warning("Não foi possível carregar perfis para treino temporal: %s", e)

        if not profiles:
            return {"status": "SKIPPED", "reason": "no_profiles"}

        builder = TemporalFeatureBuilder(seq_len=32, subsample=12, feature_stride=4)
        X, y, _ = builder.build_from_datalake(
            self.feature_builder.query_engine,
            profiles,
            partition_dates,
        )

        if len(X) < 4:
            return {"status": "SKIPPED", "reason": "insufficient_sequences", "sequences": len(X)}

        wrapper = TemporalModelWrapper(self.config.local_model_dir)
        return wrapper.train(X, y, epochs=30)