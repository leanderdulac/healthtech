import logging
import time
from typing import Dict, List, Optional

from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.feature_builder import DatalakeFeatureBuilder
from src.integrations.vertex.local_model import LocalAnomalyModel
from src.ml_pipeline.online_inference import VertexOnlineDetector

logger = logging.getLogger(__name__)


class VertexOnlinePipeline:
    """
    Pipeline de inferência online: extrai vitals do datalake Silver
    e envia para Vertex AI Endpoint (ou modelo local como fallback).
    """

    def __init__(
        self,
        config: VertexConfig,
        feature_builder: DatalakeFeatureBuilder,
        local_model: Optional[LocalAnomalyModel] = None,
    ):
        self.config = config
        self.feature_builder = feature_builder
        self.local_model = local_model or LocalAnomalyModel(config.local_model_dir)
        self._vertex_detector: Optional[VertexOnlineDetector] = None

        if config.is_gcp_configured:
            self._vertex_detector = VertexOnlineDetector(
                project=config.project_id,
                location=config.location,
                endpoint_id=config.endpoint_id,
            )

    @property
    def vertex_ready(self) -> bool:
        return self._vertex_detector is not None and self._vertex_detector.is_ready

    def stream_patient_vitals(
        self,
        patient_id: str,
        partition_date: str,
        max_records: int = 20,
        delay_seconds: float = 0.1,
    ) -> List[Dict]:
        instances = self.feature_builder.build_online_instances(
            patient_id=patient_id,
            partition_date=partition_date,
            max_records=max_records,
        )

        if not instances:
            logger.warning("Nenhuma instância online para paciente %s", patient_id)
            return []

        results = []
        for inst in instances:
            result = self._predict_single(inst)
            results.append(result)
            if delay_seconds > 0:
                time.sleep(delay_seconds)

        alerts = sum(1 for r in results if r.get("alerta"))
        logger.info(
            "Online stream %s: %d leituras, %d alertas (modo=%s)",
            patient_id, len(results), alerts, results[0].get("modo") if results else "N/A",
        )
        return results

    def _predict_single(self, instance: Dict) -> Dict:
        if self.vertex_ready:
            vertex_result = self._vertex_detector.processar_features(instance)
            if vertex_result.get("modo") == "Produção GCP":
                return vertex_result

        return self.local_model.predict_online(instance)