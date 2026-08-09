"""
Servidor HTTP self-contained para Vertex AI custom container.

Serve 3 TCNs (6h/24h/72h) em /predict e /health na porta 8080.
Não depende do pacote `src.*` — arquitetura e carga embutidas.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tcn-server")

HORIZON_NAMES = ["event_6h", "event_24h", "event_72h"]
HORIZON_LABELS = ["6h", "24h", "72h"]
AIP_HEALTH_ROUTE = os.environ.get("AIP_HEALTH_ROUTE", "/health")
AIP_PREDICT_ROUTE = os.environ.get("AIP_PREDICT_ROUTE", "/predict")
AIP_STORAGE_URI = os.environ.get("AIP_STORAGE_URI", "/tmp/model")
PORT = int(os.environ.get("AIP_HTTP_PORT", os.environ.get("PORT", "8080")))


class TCNBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, dilation: int, dropout: float = 0.2):
        super().__init__()
        padding = (kernel_size - 1) * dilation
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size, dilation=dilation, padding=padding)
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size, dilation=dilation, padding=padding)
        self.dropout = nn.Dropout(dropout)
        self.relu = nn.ReLU()
        self.downsample = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else None
        self.padding = padding

    def _chomp(self, x: torch.Tensor) -> torch.Tensor:
        if self.padding == 0:
            return x
        return x[:, :, : -self.padding]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.relu(self._chomp(self.conv1(x)))
        out = self.dropout(out)
        out = self.relu(self._chomp(self.conv2(out)))
        out = self.dropout(out)
        res = x if self.downsample is None else self.downsample(x)
        return self.relu(out + res)


class SingleHorizonTCN(nn.Module):
    def __init__(self, n_features: int, tcn_channels: int = 64, lstm_hidden: int = 96, dropout: float = 0.2):
        super().__init__()
        self.n_features = n_features
        self.input_proj = nn.Linear(n_features, tcn_channels)
        self.tcn = nn.Sequential(
            TCNBlock(tcn_channels, tcn_channels, 3, 1, dropout),
            TCNBlock(tcn_channels, tcn_channels * 2, 3, 2, dropout),
            TCNBlock(tcn_channels * 2, tcn_channels * 2, 3, 4, dropout),
        )
        self.lstm = nn.LSTM(tcn_channels * 2, lstm_hidden, 2, batch_first=True, bidirectional=True, dropout=dropout)
        self.head = nn.Sequential(
            nn.Linear(lstm_hidden * 2 + tcn_channels * 2, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        proj = self.input_proj(x)
        tcn_out = self.tcn(proj.transpose(1, 2)).transpose(1, 2)
        tcn_ctx = tcn_out.mean(dim=1)
        lstm_out, _ = self.lstm(tcn_out)
        lstm_ctx = lstm_out[:, -1, :]
        return torch.sigmoid(self.head(torch.cat([lstm_ctx, tcn_ctx], dim=1)))


class TCNRuntime:
    def __init__(self) -> None:
        self.models: List[nn.Module] = []
        self.scaler = None
        self.meta: Dict[str, Any] = {}
        self.conformal: Optional[Dict] = None
        self.device = "cpu"
        self.loaded = False

    def load(self, base: Path) -> None:
        base = Path(base)
        if not base.exists():
            # Vertex monta AIP_STORAGE_URI; local smoke usa diretório de artifacts
            raise FileNotFoundError(f"Artifacts not found: {base}")

        meta_path = base / "temporal_model_meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                self.meta = json.load(f)

        # Prefer JSON scaler (portable across sklearn versions)
        scaler_json = base / "temporal_scaler.json"
        scaler_pkl = base / "temporal_scaler.pkl"
        if scaler_json.exists():
            with open(scaler_json) as f:
                sdata = json.load(f)
            mean = np.asarray(sdata["mean"], dtype=np.float64)
            scale = np.asarray(sdata["scale"], dtype=np.float64)
            scale = np.where(scale == 0, 1.0, scale)

            class _JsonScaler:
                def transform(self, X):
                    X = np.asarray(X, dtype=np.float64)
                    return (X - mean) / scale

            self.scaler = _JsonScaler()
            logger.info("Loaded portable JSON scaler (%d features)", len(mean))
        elif scaler_pkl.exists():
            with open(scaler_pkl, "rb") as f:
                self.scaler = pickle.load(f)
            logger.info("Loaded pickle scaler")

        conf_path = base / "conformal_calibration.json"
        if conf_path.exists():
            with open(conf_path) as f:
                self.conformal = json.load(f)

        self.models = []
        for name in HORIZON_NAMES:
            path = base / f"temporal_horizon_{name}.pt"
            if not path.exists():
                raise FileNotFoundError(f"Missing model file: {path}")
            ckpt = torch.load(path, map_location=self.device, weights_only=False)
            n_features = int(ckpt.get("n_features", self.meta.get("n_features", 24)))
            model = SingleHorizonTCN(n_features=n_features).to(self.device)
            model.load_state_dict(ckpt["state"])
            model.eval()
            self.models.append(model)

        self.loaded = True
        logger.info("Loaded %d horizon models from %s", len(self.models), base)

    def _conformal_interval(self, prob: float, horizon_idx: int) -> List[float]:
        if not self.conformal:
            margin = 0.15
            return [round(max(0.0, prob - margin), 4), round(min(1.0, prob + margin), 4)]
        h_key = HORIZON_NAMES[horizon_idx]
        # suporte a layouts: {horizons:{event_6h:{q_hat}}} ou {q_hat:{event_6h:}}
        horizons = self.conformal.get("horizons", {})
        if h_key in horizons:
            q_hat = float(horizons[h_key].get("q_hat", 0.15))
        else:
            q_map = self.conformal.get("q_hat", {})
            q_hat = float(q_map.get(h_key, 0.15)) if isinstance(q_map, dict) else float(q_map or 0.15)
        return [round(max(0.0, prob - q_hat), 4), round(min(1.0, prob + q_hat), 4)]

    def predict_one(self, sequence: np.ndarray) -> Dict[str, Any]:
        if sequence.ndim == 2:
            sequence = sequence[np.newaxis, ...]
        n_samples, seq_len, n_features = sequence.shape
        flat = sequence.reshape(-1, n_features)
        if self.scaler is not None:
            flat = self.scaler.transform(flat)
        X_scaled = flat.reshape(n_samples, seq_len, n_features)

        probs: List[float] = []
        intervals: List[List[float]] = []
        with torch.no_grad():
            X_t = torch.tensor(X_scaled, dtype=torch.float32, device=self.device)
            for h_idx, model in enumerate(self.models):
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
            "architecture": self.meta.get("architecture", "TCN-per-horizon"),
            "conformal_intervals": {HORIZON_LABELS[i]: intervals[i] for i in range(3)},
            "alerta": bool(pred.max() > 0.5),
        }

    @staticmethod
    def extract_sequence(inst: Dict) -> Optional[np.ndarray]:
        if "sequence" in inst:
            arr = np.array(inst["sequence"], dtype=np.float32)
            return arr if arr.ndim == 2 else None
        if "sequences" in inst:
            batch = np.array(inst["sequences"], dtype=np.float32)
            return batch[0] if batch.ndim == 3 else None
        # lista crua de timesteps
        if isinstance(inst, list):
            arr = np.array(inst, dtype=np.float32)
            return arr if arr.ndim == 2 else None
        return None


runtime = TCNRuntime()
app = Flask(__name__)


def _download_gcs_prefix(gcs_uri: str, dest: Path) -> Path:
    """Baixa prefixo gs://bucket/path para dest local."""
    from google.cloud import storage

    assert gcs_uri.startswith("gs://"), gcs_uri
    parts = gcs_uri[5:].split("/", 1)
    bucket_name = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    dest.mkdir(parents=True, exist_ok=True)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = list(client.list_blobs(bucket_name, prefix=prefix))
    if not blobs:
        raise FileNotFoundError(f"Nenhum blob em {gcs_uri}")
    for blob in blobs:
        rel = blob.name[len(prefix) :].lstrip("/") if prefix else blob.name
        if not rel or blob.name.endswith("/"):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))
        logger.info("Downloaded gs://%s/%s → %s", bucket_name, blob.name, target)
    return dest


def _resolve_artifact_dir() -> Path:
    uri = AIP_STORAGE_URI
    if uri.startswith("gs://"):
        local = Path("/tmp/model")
        if not (local / "temporal_horizon_event_6h.pt").exists():
            _download_gcs_prefix(uri, local)
        return local

    candidates = [
        Path(uri) if uri else Path("/tmp/model"),
        Path("/gcs/model"),
        Path("/tmp/model"),
        Path("data/vertex_deploy/artifacts"),
        Path("."),
    ]
    for c in candidates:
        if (c / "temporal_horizon_event_6h.pt").exists():
            return c
    return candidates[0]


def ensure_loaded() -> None:
    if runtime.loaded:
        return
    artifact_dir = _resolve_artifact_dir()
    logger.info("Loading artifacts from %s", artifact_dir)
    runtime.load(artifact_dir)


@app.before_request
def _lazy_load():
    # health pode responder antes do load; predict exige modelo
    if request.path.rstrip("/") == AIP_HEALTH_ROUTE.rstrip("/"):
        return
    try:
        ensure_loaded()
    except Exception as exc:
        logger.exception("Failed to load model: %s", exc)


@app.route(AIP_HEALTH_ROUTE, methods=["GET"])
def health():
    try:
        ensure_loaded()
    except Exception:
        pass
    return jsonify({"status": "healthy" if runtime.loaded else "loading", "loaded": runtime.loaded}), 200


@app.route(AIP_PREDICT_ROUTE, methods=["POST"])
def predict():
    try:
        ensure_loaded()
    except Exception as exc:
        return jsonify({"error": f"model not loaded: {exc}"}), 503
    if not runtime.loaded:
        return jsonify({"error": "model not loaded"}), 503
    body = request.get_json(force=True, silent=True) or {}
    instances = body.get("instances", body if isinstance(body, list) else [body])
    predictions = []
    for inst in instances:
        if not isinstance(inst, dict):
            inst = {"sequence": inst}
        seq = runtime.extract_sequence(inst)
        if seq is None:
            predictions.append({"error": "sequence ausente ou inválida"})
        else:
            predictions.append(runtime.predict_one(seq))
    return jsonify({"predictions": predictions}), 200


def main() -> None:
    ensure_loaded()
    app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
