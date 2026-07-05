"""
Extração de ground truth clínico para validação preditiva.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HORIZON_HOURS = {"6h": 6, "24h": 24, "72h": 72}
HORIZON_KEYS = ["event_6h", "event_24h", "event_72h"]


class GroundTruthExtractor:
    """Constrói labels de validação a partir de FHIR, Gold alerts ou labels sintéticos."""

    def __init__(self, clinical_bridge=None):
        self.clinical_bridge = clinical_bridge

    def from_fhir_events(self, patient_id: str) -> List[Dict]:
        if not self.clinical_bridge:
            return []
        return self.clinical_bridge.get_clinical_events(patient_id)

    def from_gold_alerts(
        self,
        query_engine,
        patient_ids: Optional[List[str]] = None,
        partition_dates: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        from src.datalake.extraction.filters import QueryFilters

        alerts = query_engine.extract("alerts", QueryFilters(
            patient_ids=patient_ids,
            partition_dates=partition_dates,
        ))
        if alerts.empty:
            return pd.DataFrame(columns=["patient_id", "timestamp", "alert_type", "severity"])

        cols = [c for c in ["patient_id", "alert_timestamp", "alert_type", "severity", "metric"]
                if c in alerts.columns]
        return alerts[cols] if cols else alerts

    def build_horizon_labels_from_alerts(
        self,
        alert_times: List[datetime],
        sequence_timestamps: List[datetime],
        minutes_per_step: float = 2.5,
    ) -> np.ndarray:
        """
        Para cada timestep da sequência, marca 1 se evento ocorre no horizonte.
        Retorna (n_steps, 3) labels para 6h/24h/72h.
        """
        n = len(sequence_timestamps)
        labels = np.zeros((n, 3), dtype=np.float32)

        if not alert_times:
            return labels

        for i, ts in enumerate(sequence_timestamps):
            for h_idx, (h_label, hours) in enumerate(HORIZON_HOURS.items()):
                horizon_end = ts + pd.Timedelta(hours=hours)
                for alert_ts in alert_times:
                    if ts < alert_ts <= horizon_end:
                        labels[i, h_idx] = 1.0
                        break

        return labels

    def align_predictions_to_ground_truth(
        self,
        y_model: np.ndarray,
        y_ground: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        n = min(len(y_model), len(y_ground))
        return y_model[:n], y_ground[:n]