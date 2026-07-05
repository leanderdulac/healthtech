"""
Calibração conformal integrada ao pipeline temporal TCN.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from src.clinical_intelligence.conformal.split_conformal import SplitConformalPredictor
from src.clinical_intelligence.temporal_features import HORIZON_NAMES, TemporalFeatureBuilder
from src.clinical_intelligence.temporal_model import TemporalModelWrapper

logger = logging.getLogger(__name__)


class ConformalCalibrator:
    """Calibra intervalos conformais nos modelos TCN treinados."""

    CALIBRATION_FILENAME = "conformal_calibration.json"

    def __init__(
        self,
        model_dir: Path,
        alpha: float = 0.10,
        cal_fraction: float = 0.25,
    ):
        self.model_dir = Path(model_dir)
        self.alpha = alpha
        self.cal_fraction = cal_fraction
        self.predictor = SplitConformalPredictor(alpha=alpha)
        self.model = TemporalModelWrapper(self.model_dir)

    def calibrate_from_datalake(
        self,
        query_engine,
        patient_profiles,
        partition_dates=None,
        subsample: int = 30,
    ) -> Dict:
        builder = TemporalFeatureBuilder(seq_len=32, subsample=subsample, feature_stride=4)
        X, y, _ = builder.build_from_datalake(
            query_engine=query_engine,
            patient_profiles=patient_profiles,
            partition_dates=partition_dates,
        )

        if len(X) < 20:
            return {"status": "skipped", "reason": "insufficient_data", "samples": len(X)}

        return self.calibrate_from_arrays(X, y)

    def calibrate_from_arrays(self, X: np.ndarray, y: np.ndarray) -> Dict:
        if not self.model.is_trained:
            self.model._load_checkpoint()

        n = len(X)
        split = int(n * (1 - self.cal_fraction))
        X_cal, y_cal = X[split:], y[split:]

        if len(X_cal) < 10:
            X_cal, y_cal = X, y

        probs = self.model.predict(X_cal)
        stats = self.predictor.calibrate(probs, y_cal, HORIZON_NAMES[: y.shape[1]])

        payload = {
            "status": "calibrated",
            "alpha": self.alpha,
            "calibration_samples": len(X_cal),
            "horizons": stats,
            "q_hat": {k: round(v, 4) for k, v in self.predictor.q_hat.items()},
        }

        out_path = self.model_dir / self.CALIBRATION_FILENAME
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)

        logger.info("Calibração conformal salva em %s", out_path)
        return {**payload, "path": str(out_path)}

    def load(self) -> Optional[SplitConformalPredictor]:
        path = self.model_dir / self.CALIBRATION_FILENAME
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return SplitConformalPredictor.from_dict(data)

    def apply_to_prediction(self, probs: np.ndarray) -> Dict[str, Tuple[float, float]]:
        predictor = self.load() or self.predictor
        if not predictor.calibrated:
            return {}

        labels = ["6h", "24h", "72h"]
        intervals = {}
        for h, name in enumerate(HORIZON_NAMES[: len(probs)]):
            lo, hi = predictor.predict_interval(float(probs[h]), name)
            intervals[labels[h]] = (round(lo, 4), round(hi, 4))
        return intervals