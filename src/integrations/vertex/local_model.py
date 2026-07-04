import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.integrations.vertex.feature_builder import FEATURE_COLUMNS, ONLINE_FEATURE_COLUMNS

logger = logging.getLogger(__name__)


class LocalAnomalyModel:
    """
    Modelo local de detecção de anomalias (Isolation Forest).
    Funciona como substituto do Vertex quando GCP não está configurado.
    """

    MODEL_FILENAME = "anomaly_detector.pkl"
    METADATA_FILENAME = "anomaly_detector_meta.json"

    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._model: Optional[IsolationForest] = None
        self._scaler: Optional[StandardScaler] = None
        self._feature_columns: List[str] = FEATURE_COLUMNS
        self._online_columns: List[str] = ONLINE_FEATURE_COLUMNS

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def train(self, features_df: pd.DataFrame) -> Dict:
        if features_df.empty or len(features_df) < 2:
            logger.warning("Dados insuficientes para treino — usando modelo heurístico")
            return {"status": "skipped", "reason": "insufficient_data"}

        X = features_df[self._feature_columns].fillna(0).values
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        contamination = min(0.3, max(0.05, features_df["risk_label"].mean() / 3))
        self._model = IsolationForest(
            n_estimators=100,
            contamination=contamination,
            random_state=42,
        )
        self._model.fit(X_scaled)

        predictions = self._model.predict(X_scaled)
        anomaly_rate = (predictions == -1).mean()

        self._save()
        logger.info("Modelo local treinado: %d amostras, taxa anomalia=%.1f%%",
                      len(features_df), anomaly_rate * 100)

        return {
            "status": "trained",
            "samples": len(features_df),
            "anomaly_rate": round(anomaly_rate, 3),
            "model_path": str(self.model_path),
        }

    def predict_batch(self, features_df: pd.DataFrame) -> pd.DataFrame:
        if not self.is_trained:
            self._load()
        if not self.is_trained:
            return self._heuristic_batch(features_df)

        X = features_df[self._feature_columns].fillna(0).values
        X_scaled = self._scaler.transform(X)
        raw = self._model.predict(X_scaled)
        scores = self._model.decision_function(X_scaled)

        result = features_df.copy()
        result["is_anomaly"] = raw == -1
        result["anomaly_score"] = np.clip(1 - (scores + 0.5), 0, 1)
        result["modo"] = "Local ML (IsolationForest)"
        return result

    def predict_online(self, instance: Dict) -> Dict:
        bpm = float(instance.get("bpm", 70))
        spo2 = float(instance.get("spo2", 97))
        stress = float(instance.get("stress", 0))
        is_active = int(instance.get("is_active", 0))
        is_sleeping = int(instance.get("is_sleeping", 0))

        hr_high = 160 if is_active else (90 if is_sleeping else 120)
        hr_low = 40 if is_sleeping else 45

        is_anomaly = bpm > hr_high or bpm < hr_low or spo2 < 92 or stress > 80
        score = 0.0
        if bpm > hr_high:
            score = max(score, min(1.0, (bpm - hr_high) / hr_high))
        if bpm < hr_low:
            score = max(score, min(1.0, (hr_low - bpm) / hr_low))
        if spo2 < 92:
            score = max(score, 0.9)
        if not is_anomaly:
            score = 0.1

        return {
            "alerta": bool(is_anomaly),
            "score": round(score, 3),
            "valor_atual": bpm,
            "spo2": spo2,
            "stress": stress,
            "patient_id": instance.get("patient_id"),
            "timestamp": instance.get("timestamp"),
            "status": "ALERTA CRÍTICO" if is_anomaly else "Normal",
            "modo": "Local ML (Contextual)",
        }

    def _heuristic_batch(self, features_df: pd.DataFrame) -> pd.DataFrame:
        result = features_df.copy()
        result["is_anomaly"] = (
            (result.get("avg_resting_hr", 0) > 100)
            | (result.get("avg_spo2", 100) < 93)
            | (result.get("anomaly_episodes", 0) > 5)
        )
        result["anomaly_score"] = result["is_anomaly"].astype(float) * 0.9
        result["modo"] = "Heurística Local"
        return result

    @property
    def model_path(self) -> Path:
        return self.model_dir / self.MODEL_FILENAME

    def _save(self) -> None:
        with open(self.model_path, "wb") as f:
            pickle.dump({"model": self._model, "scaler": self._scaler}, f)
        meta = {
            "feature_columns": self._feature_columns,
            "online_columns": self._online_columns,
        }
        with open(self.model_dir / self.METADATA_FILENAME, "w") as f:
            json.dump(meta, f)

    def _load(self) -> bool:
        if not self.model_path.exists():
            return False
        with open(self.model_path, "rb") as f:
            data = pickle.load(f)
        self._model = data["model"]
        self._scaler = data.get("scaler")
        return True