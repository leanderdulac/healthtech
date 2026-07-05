"""
Custom Predictor Vertex AI — 3 TCNs independentes (6h / 24h / 72h).

Compatível com google.cloud.aiplatform.prediction.Predictor
e execução local para testes.
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

HORIZON_NAMES = ["event_6h", "event_24h", "event_72h"]
HORIZON_LABELS = ["6h", "24h", "72h"]


class TCNTemporalPredictor:
    """
    Carrega 3 modelos SingleHorizonTCN + scaler e serve predições multi-horizonte.

    Instância de entrada:
      {"sequence": [[f1, f2, ...], ...]}  — (seq_len, n_features)
      ou {"sequences": [batch de sequências]}
    """

    def __init__(self):
        self._horizon_models: List = []
        self._scaler = None
        self._meta: Dict = {}
        self._device = "cpu"
        self._conformal: Optional[Dict] = None
        self._loaded = False

    def load(self, artifacts_uri: str) -> None:
        """Carrega artefatos do diretório local ou GCS (via download prévio)."""
        base = Path(artifacts_uri)
        if not base.exists():
            raise FileNotFoundError(f"Artefatos não encontrados: {artifacts_uri}")

        from src.clinical_intelligence.temporal_model import TemporalModelWrapper

        wrapper = TemporalModelWrapper(base)
        wrapper._load_checkpoint()
        self._horizon_models = wrapper._horizon_models
        self._scaler = wrapper._scaler
        self._meta = wrapper._meta
        self._device = wrapper._device

        conformal_path = base / "conformal_calibration.json"
        if conformal_path.exists():
            with open(conformal_path) as f:
                self._conformal = json.load(f)

        if not self._horizon_models:
            raise FileNotFoundError("Nenhum modelo TCN carregado — verifique artefatos .pt")

        self._loaded = True
        logger.info("TCN Predictor carregado: %d horizontes", len(self._horizon_models))

    def predict(self, instances: List[Dict]) -> List[Dict]:
        if not self._loaded:
            raise RuntimeError("Predictor não carregado — chame load() primeiro")

        results = []
        for inst in instances:
            seq = self._extract_sequence(inst)
            if seq is None:
                results.append({"error": "sequence ausente ou inválida"})
                continue
            results.append(self._predict_one(seq))
        return results

    def _predict_one(self, sequence: np.ndarray) -> Dict:
        if sequence.ndim == 2:
            sequence = sequence[np.newaxis, ...]

        n_samples, seq_len, n_features = sequence.shape
        flat = sequence.reshape(-1, n_features)
        if self._scaler is not None:
            flat = self._scaler.transform(flat)
        X_scaled = flat.reshape(n_samples, seq_len, n_features)

        probs = []
        intervals = []
        for h_idx, model in enumerate(self._horizon_models):
            with torch.no_grad():
                X_t = torch.tensor(X_scaled, dtype=torch.float32, device=self._device)
                p = float(model(X_t).squeeze(-1).cpu().numpy()[0])
            probs.append(p)
            intervals.append(self._conformal_interval(p, h_idx))

        pred = np.array(probs)
        return {
            "prob_6h": round(probs[0], 4),
            "prob_24h": round(probs[1], 4),
            "prob_72h": round(probs[2], 4),
            "max_probability": round(float(pred.max()), 4),
            "horizon_at_risk": HORIZON_LABELS[int(pred.argmax())],
            "modo": "Vertex-TCN-per-horizon",
            "architecture": self._meta.get("architecture", "TCN-per-horizon"),
            "conformal_intervals": {
                HORIZON_LABELS[i]: intervals[i] for i in range(3)
            },
            "alerta": bool(pred.max() > 0.5),
        }

    def _conformal_interval(self, prob: float, horizon_idx: int) -> List[float]:
        if not self._conformal:
            margin = 0.15
            return [round(max(0, prob - margin), 4), round(min(1, prob + margin), 4)]

        h_key = HORIZON_NAMES[horizon_idx]
        cal = self._conformal.get("horizons", {}).get(h_key, {})
        q_hat = cal.get("q_hat", 0.15)
        return [round(max(0.0, prob - q_hat), 4), round(min(1.0, prob + q_hat), 4)]

    @staticmethod
    def _extract_sequence(inst: Dict) -> Optional[np.ndarray]:
        if "sequence" in inst:
            arr = np.array(inst["sequence"], dtype=np.float32)
            return arr if arr.ndim == 2 else None
        if "sequences" in inst:
            batch = np.array(inst["sequences"], dtype=np.float32)
            return batch[0] if batch.ndim == 3 else None
        keys = [k for k in inst if k.startswith("f_") or k in ("hr", "spo2")]
        if keys:
            logger.warning("Instância sem sequence — formato legado não suportado no TCN endpoint")
        return None


try:
    from google.cloud.aiplatform.prediction.predictor import Predictor as VertexPredictorBase

    class VertexTCNPredictor(TCNTemporalPredictor, VertexPredictorBase):
        """Wrapper registrável no Vertex AI Model Registry."""

        def load(self, artifacts_uri: str):
            super().load(artifacts_uri)

        def predict(self, instances: List[Dict]) -> List[Dict]:
            return super().predict(instances)

except ImportError:
    VertexTCNPredictor = TCNTemporalPredictor