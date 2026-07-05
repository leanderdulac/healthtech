"""
Split Conformal Prediction multi-horizonte com garantia de cobertura.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

HORIZON_NAMES = ["event_6h", "event_24h", "event_72h"]


class SplitConformalPredictor:
    """
    Conformal prediction para classificação binária por horizonte.

    Nonconformity score: 1 - P(Y = y_true | X)
    Intervalo de probabilidade: [p - q_hat, p + q_hat] com cobertura 1 - alpha.
    """

    def __init__(self, alpha: float = 0.10):
        self.alpha = alpha
        self.q_hat: Dict[str, float] = {}
        self.calibrated = False
        self._calibration_stats: Dict[str, Dict] = {}

    def calibrate(
        self,
        probs: np.ndarray,
        labels: np.ndarray,
        horizon_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict]:
        """
        Calibra q_hat por horizonte no conjunto de calibração.

        Args:
            probs: (N, n_horizons) probabilidades preditas
            labels: (N, n_horizons) labels binários
        """
        names = horizon_names or HORIZON_NAMES[: probs.shape[1]]
        results = {}

        for h, name in enumerate(names):
            p_h = probs[:, h]
            y_h = labels[:, h].astype(float)

            scores = np.where(y_h >= 0.5, 1.0 - p_h, p_h)
            n = len(scores)
            q_level = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
            q_hat = float(np.quantile(scores, q_level))

            self.q_hat[name] = q_hat
            coverage = self._empirical_coverage(p_h, y_h, q_hat)

            results[name] = {
                "q_hat": round(q_hat, 4),
                "alpha": self.alpha,
                "target_coverage": round(1 - self.alpha, 3),
                "empirical_coverage": round(coverage, 3),
                "n_calibration": n,
            }

        self._calibration_stats = results
        self.calibrated = True
        logger.info("Conformal calibrado: %s", results)
        return results

    def predict_interval(self, prob: float, horizon: str) -> Tuple[float, float]:
        if not self.calibrated or horizon not in self.q_hat:
            margin = 0.15
            return max(0.0, prob - margin), min(1.0, prob + margin)

        q = self.q_hat[horizon]
        return max(0.0, prob - q), min(1.0, prob + q)

    def predict_set(self, prob: float, horizon: str) -> List[int]:
        """Conjunto preditivo conformal — classes incluídas com garantia 1-alpha."""
        if not self.calibrated or horizon not in self.q_hat:
            return [1] if prob > 0.5 else [0]

        q = self.q_hat[horizon]
        prediction_set = []
        if 1.0 - prob <= q:
            prediction_set.append(1)
        if prob <= q:
            prediction_set.append(0)
        return prediction_set or ([1] if prob > 0.5 else [0])

    def to_dict(self) -> Dict:
        return {
            "alpha": self.alpha,
            "horizons": self._calibration_stats,
            "q_hat": {k: round(v, 4) for k, v in self.q_hat.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SplitConformalPredictor":
        predictor = cls(alpha=data.get("alpha", 0.10))
        predictor.q_hat = data.get("q_hat", {})
        for name, stats in data.get("horizons", {}).items():
            if name not in predictor.q_hat and "q_hat" in stats:
                predictor.q_hat[name] = stats["q_hat"]
        predictor._calibration_stats = data.get("horizons", {})
        predictor.calibrated = bool(predictor.q_hat)
        return predictor

    @staticmethod
    def _empirical_coverage(probs: np.ndarray, labels: np.ndarray, q_hat: float) -> float:
        covered = 0
        for p, y in zip(probs, labels):
            y_int = int(y >= 0.5)
            score = 1.0 - p if y_int == 1 else p
            if score <= q_hat:
                covered += 1
        return covered / max(len(probs), 1)