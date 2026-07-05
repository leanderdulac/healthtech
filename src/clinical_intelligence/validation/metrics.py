"""
Métricas de validação clínica para predição temporal multi-horizonte.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np


@dataclass
class HorizonMetrics:
    horizon: str
    sensitivity: float
    specificity: float
    ppv: float
    npv: float
    accuracy: float
    f1: float
    threshold: float
    n_positive: int
    n_negative: int
    lead_time_mae_hours: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "horizon": self.horizon,
            "sensitivity": round(self.sensitivity, 4),
            "specificity": round(self.specificity, 4),
            "ppv": round(self.ppv, 4),
            "npv": round(self.npv, 4),
            "accuracy": round(self.accuracy, 4),
            "f1": round(self.f1, 4),
            "threshold": round(self.threshold, 4),
            "n_positive": self.n_positive,
            "n_negative": self.n_negative,
            "lead_time_mae_hours": round(self.lead_time_mae_hours, 2)
            if self.lead_time_mae_hours is not None else None,
        }


@dataclass
class ClinicalMetrics:
    """Calcula métricas clínicas padrão por horizonte."""

    @staticmethod
    def compute(
        y_true: np.ndarray,
        y_prob: np.ndarray,
        horizon: str,
        threshold: Optional[float] = None,
        lead_times_pred: Optional[np.ndarray] = None,
        lead_times_true: Optional[np.ndarray] = None,
    ) -> HorizonMetrics:
        y_true = y_true.astype(int)
        thresh = threshold if threshold is not None else 0.5
        if 0 < y_true.sum() < len(y_true):
            thresh = float(np.percentile(y_prob, 100 * (1 - y_true.mean())))
            thresh = max(0.15, min(0.85, thresh))

        y_pred = (y_prob >= thresh).astype(int)
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        tn = int(((y_pred == 0) & (y_true == 0)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())

        sensitivity = tp / max(tp + fn, 1)
        specificity = tn / max(tn + fp, 1)
        ppv = tp / max(tp + fp, 1)
        npv = tn / max(tn + fn, 1)
        accuracy = (tp + tn) / max(len(y_true), 1)
        precision = ppv
        recall = sensitivity
        f1 = 2 * precision * recall / max(precision + recall, 1e-6)

        lead_mae = None
        if lead_times_pred is not None and lead_times_true is not None:
            mask = y_true == 1
            if mask.sum() > 0:
                lead_mae = float(np.mean(np.abs(
                    lead_times_pred[mask] - lead_times_true[mask]
                )))

        return HorizonMetrics(
            horizon=horizon,
            sensitivity=float(sensitivity),
            specificity=float(specificity),
            ppv=float(ppv),
            npv=float(npv),
            accuracy=float(accuracy),
            f1=float(f1),
            threshold=float(thresh),
            n_positive=int(y_true.sum()),
            n_negative=int(len(y_true) - y_true.sum()),
            lead_time_mae_hours=lead_mae,
        )

    @staticmethod
    def aggregate(horizon_metrics: List[HorizonMetrics]) -> Dict:
        return {
            "horizons": [m.to_dict() for m in horizon_metrics],
            "mean_f1": round(float(np.mean([m.f1 for m in horizon_metrics])), 4),
            "mean_sensitivity": round(float(np.mean([m.sensitivity for m in horizon_metrics])), 4),
            "mean_specificity": round(float(np.mean([m.specificity for m in horizon_metrics])), 4),
        }