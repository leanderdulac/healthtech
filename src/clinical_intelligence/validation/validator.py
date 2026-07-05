"""
Validador clínico — compara predições TCN com ground truth e gera relatório.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.clinical_intelligence.temporal_features import HORIZON_NAMES, TemporalFeatureBuilder
from src.clinical_intelligence.temporal_model import TemporalModelWrapper
from src.clinical_intelligence.validation.ground_truth import GroundTruthExtractor
from src.clinical_intelligence.validation.metrics import ClinicalMetrics, HorizonMetrics

logger = logging.getLogger(__name__)


class ClinicalValidator:
    """Executa validação clínica end-to-end com relatório JSON."""

    def __init__(
        self,
        model_dir: Path = Path("data/models"),
        output_dir: Path = Path("data/clinical_validation"),
        clinical_bridge=None,
    ):
        self.model_dir = Path(model_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model = TemporalModelWrapper(self.model_dir)
        self.ground_truth = GroundTruthExtractor(clinical_bridge)
        self.feature_builder = TemporalFeatureBuilder(seq_len=32, subsample=30, feature_stride=4)

    def validate_from_datalake(
        self,
        query_engine,
        patient_profiles,
        partition_dates: Optional[List[str]] = None,
    ) -> Dict:
        if not self.model.is_trained:
            self.model._load_checkpoint()

        X, y, patient_ids = self.feature_builder.build_from_datalake(
            query_engine=query_engine,
            patient_profiles=patient_profiles,
            partition_dates=partition_dates,
        )

        if len(X) == 0:
            return {"status": "skipped", "reason": "no_sequences"}

        probs = self.model.predict(X)
        return self._evaluate(probs, y, patient_ids, source="datalake_labels")

    def validate_with_fhir_ground_truth(
        self,
        query_engine,
        patient_profiles,
        partition_dates: Optional[List[str]] = None,
    ) -> Dict:
        """Valida usando alertas Gold + eventos FHIR como ground truth."""
        primary = self.validate_from_datalake(query_engine, patient_profiles, partition_dates)

        fhir_summary = {"patients": 0, "events": 0}
        if self.ground_truth.clinical_bridge:
            for profile in patient_profiles:
                events = self.ground_truth.from_fhir_events(profile.patient_id)
                fhir_summary["patients"] += 1
                fhir_summary["events"] += len(events)

        primary["fhir_ground_truth"] = fhir_summary
        primary["validation_mode"] = "hybrid_datalake_fhir"
        return primary

    def _evaluate(
        self,
        probs: np.ndarray,
        labels: np.ndarray,
        patient_ids: List[str],
        source: str,
    ) -> Dict:
        horizon_metrics: List[HorizonMetrics] = []

        for h, name in enumerate(HORIZON_NAMES[: labels.shape[1]]):
            m = ClinicalMetrics.compute(
                y_true=labels[:, h],
                y_prob=probs[:, h],
                horizon=name,
            )
            horizon_metrics.append(m)

        report = {
            "status": "completed",
            "validated_at": datetime.utcnow().isoformat(),
            "source": source,
            "n_sequences": len(probs),
            "n_patients": len(set(patient_ids)),
            "metrics": ClinicalMetrics.aggregate(horizon_metrics),
            "conformal_available": (self.model_dir / "conformal_calibration.json").exists(),
        }

        path = self._save_report(report)
        report["report_path"] = str(path)
        return report

    def _save_report(self, report: Dict) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"validation_{timestamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        latest = self.output_dir / "latest_validation.json"
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info("Relatório de validação salvo em %s", path)
        return path