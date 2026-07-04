"""
Modelo temporal híbrido TCN + LSTM para predição multi-horizonte.

Arquitetura:
  Input (batch, seq_len, n_features)
    → TCN (dilated causal convolutions, receptive field expandido)
    → BiLSTM (dependências de longo alcance)
    → Multi-head sigmoid (6h, 24h, 72h)
"""

import json
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None
    nn = None


if TORCH_AVAILABLE:

    class TCNBlock(nn.Module):
        """Bloco convolucional temporal com dilatação causal."""

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
            return x[:, :, :-self.padding]

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out = self.relu(self._chomp(self.conv1(x)))
            out = self.dropout(out)
            out = self.relu(self._chomp(self.conv2(out)))
            out = self.dropout(out)
            res = x if self.downsample is None else self.downsample(x)
            return self.relu(out + res)

    class TCNLSTMTemporalModel(nn.Module):
        """
        TCN extrai padrões locais (picos HR, dips SpO2);
        BiLSTM captura tendências (deterioração gradual);
        Heads independentes por horizonte preditivo.
        """

        def __init__(
            self,
            n_features: int,
            seq_len: int = 32,
            tcn_channels: int = 64,
            lstm_hidden: int = 128,
            n_horizons: int = 3,
            dropout: float = 0.25,
        ):
            super().__init__()
            self.n_features = n_features
            self.seq_len = seq_len
            self.n_horizons = n_horizons

            self.input_proj = nn.Linear(n_features, tcn_channels)

            self.tcn = nn.Sequential(
                TCNBlock(tcn_channels, tcn_channels, kernel_size=3, dilation=1, dropout=dropout),
                TCNBlock(tcn_channels, tcn_channels, kernel_size=3, dilation=2, dropout=dropout),
                TCNBlock(tcn_channels, tcn_channels * 2, kernel_size=3, dilation=4, dropout=dropout),
            )

            self.lstm = nn.LSTM(
                input_size=tcn_channels * 2,
                hidden_size=lstm_hidden,
                num_layers=2,
                batch_first=True,
                bidirectional=True,
                dropout=dropout,
            )

            self.attention = nn.Sequential(
                nn.Linear(lstm_hidden * 2, 64),
                nn.Tanh(),
                nn.Linear(64, 1),
            )

            self.heads = nn.ModuleList([
                nn.Sequential(
                    nn.Linear(lstm_hidden * 2, 64),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(64, 1),
                )
                for _ in range(n_horizons)
            ])

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            batch, seq, feat = x.shape
            projected = self.input_proj(x)
            tcn_in = projected.transpose(1, 2)
            tcn_out = self.tcn(tcn_in).transpose(1, 2)

            lstm_out, _ = self.lstm(tcn_out)

            attn_weights = F.softmax(self.attention(lstm_out), dim=1)
            context = (attn_weights * lstm_out).sum(dim=1)

            outputs = []
            for head in self.heads:
                outputs.append(torch.sigmoid(head(context)))
            return torch.cat(outputs, dim=1)


class TemporalModelWrapper:
    """Wrapper de treino/inferência com fallback sklearn se PyTorch indisponível."""

    MODEL_FILENAME = "temporal_tcn_lstm.pt"
    FALLBACK_FILENAME = "temporal_mlp_fallback.pkl"
    SCALER_FILENAME = "temporal_scaler.pkl"
    META_FILENAME = "temporal_model_meta.json"

    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._model = None
        self._fallback_models = None
        self._scaler = None
        self._meta: Dict = {}
        self._device = "cpu"
        self._use_fallback = False

    @property
    def is_trained(self) -> bool:
        return (
            self._model is not None
            or (self.model_dir / self.MODEL_FILENAME).exists()
            or (self.model_dir / self.FALLBACK_FILENAME).exists()
        )

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        epochs: int = 50,
        batch_size: int = 32,
        learning_rate: float = 1e-3,
        val_split: float = 0.2,
    ) -> Dict:
        if not TORCH_AVAILABLE:
            return self._train_fallback(X, y)

        if len(X) < 4:
            return {"status": "skipped", "reason": "insufficient_sequences"}

        from sklearn.preprocessing import StandardScaler

        n_samples, seq_len, n_features = X.shape
        self._scaler = StandardScaler()
        flat = X.reshape(-1, n_features)
        self._scaler.fit(flat)
        X_scaled = self._scaler.transform(flat).reshape(n_samples, seq_len, n_features)

        split = int(n_samples * (1 - val_split))
        if split < 2:
            split = max(1, n_samples - 1)

        X_train, X_val = X_scaled[:split], X_scaled[split:]
        y_train, y_val = y[:split], y[split:]

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = TCNLSTMTemporalModel(
            n_features=n_features,
            seq_len=seq_len,
            n_horizons=y.shape[1],
        ).to(self._device)

        pos_weights = []
        for h in range(y.shape[1]):
            pos = y_train[:, h].sum()
            neg = len(y_train) - pos
            pos_weights.append(neg / max(pos, 1.0))
        pos_weight = torch.tensor(pos_weights, device=self._device)

        optimizer = torch.optim.AdamW(self._model.parameters(), lr=learning_rate, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)

        X_train_t = torch.tensor(X_train, dtype=torch.float32, device=self._device)
        y_train_t = torch.tensor(y_train, dtype=torch.float32, device=self._device)
        X_val_t = torch.tensor(X_val, dtype=torch.float32, device=self._device) if len(X_val) > 0 else None
        y_val_t = torch.tensor(y_val, dtype=torch.float32, device=self._device) if len(y_val) > 0 else None

        best_val_loss = float("inf")
        patience_counter = 0
        history = []

        for epoch in range(epochs):
            self._model.train()
            perm = torch.randperm(len(X_train_t))
            epoch_loss = 0.0
            n_batches = 0

            for i in range(0, len(X_train_t), batch_size):
                idx = perm[i:i + batch_size]
                batch_x = X_train_t[idx]
                batch_y = y_train_t[idx]

                optimizer.zero_grad()
                pred = self._model(batch_x)
                loss = F.binary_cross_entropy(pred, batch_y, weight=pos_weight.unsqueeze(0))
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
                n_batches += 1

            avg_loss = epoch_loss / max(n_batches, 1)

            val_loss = avg_loss
            if X_val_t is not None and len(X_val_t) > 0:
                self._model.eval()
                with torch.no_grad():
                    val_pred = self._model(X_val_t)
                    val_loss = F.binary_cross_entropy(val_pred, y_val_t, weight=pos_weight.unsqueeze(0)).item()

            scheduler.step(val_loss)
            history.append({"epoch": epoch + 1, "train_loss": avg_loss, "val_loss": val_loss})

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                self._save_checkpoint()
            else:
                patience_counter += 1
                if patience_counter >= 10:
                    logger.info("Early stopping na época %d", epoch + 1)
                    break

        self._load_checkpoint()
        metrics = self._evaluate(X_scaled, y)

        self._meta = {
            "architecture": "TCN+BiLSTM",
            "n_features": n_features,
            "seq_len": seq_len,
            "n_horizons": y.shape[1],
            "horizon_names": ["event_6h", "event_24h", "event_72h"],
            "train_samples": split,
            "val_samples": n_samples - split,
            "metrics": metrics,
            "history": history[-5:],
        }
        self._save_meta()

        return {
            "status": "trained",
            "architecture": "TCN+BiLSTM",
            "samples": n_samples,
            "epochs_run": len(history),
            "metrics": metrics,
            "model_path": str(self.model_dir / self.MODEL_FILENAME),
        }

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._fallback_models is None and self._model is None:
            self._load_checkpoint()
        if self._use_fallback and self._fallback_models:
            return self._predict_fallback(X)
        if self._model is None:
            return np.zeros((len(X), 3))

        n_samples, seq_len, n_features = X.shape
        flat = X.reshape(-1, n_features)
        if self._scaler:
            flat = self._scaler.transform(flat)
        X_scaled = flat.reshape(n_samples, seq_len, n_features)

        self._model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X_scaled, dtype=torch.float32, device=self._device)
            pred = self._model(X_t).cpu().numpy()
        return pred

    def predict_single(self, sequence: np.ndarray) -> Dict:
        if sequence.ndim == 2:
            sequence = sequence[np.newaxis, ...]
        pred = self.predict(sequence)[0]
        return {
            "prob_6h": round(float(pred[0]), 4),
            "prob_24h": round(float(pred[1]), 4),
            "prob_72h": round(float(pred[2]), 4),
            "max_probability": round(float(pred.max()), 4),
            "horizon_at_risk": ["6h", "24h", "72h"][int(pred.argmax())],
            "modo": "MLP-fallback (ghost+fuzzy)" if self._use_fallback else "TCN+BiLSTM (ghost+fuzzy)",
        }

    def _evaluate(self, X: np.ndarray, y: np.ndarray) -> Dict:
        pred = self.predict(X)

        metrics = {}
        horizon_names = ["event_6h", "event_24h", "event_72h"]
        for h, name in enumerate(horizon_names):
            y_h = y[:, h]
            p_h = pred[:, h]
            tp = ((p_h > 0.5) & (y_h > 0.5)).sum()
            fp = ((p_h > 0.5) & (y_h < 0.5)).sum()
            fn = ((p_h <= 0.5) & (y_h > 0.5)).sum()
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-6)
            metrics[name] = {
                "precision": round(float(precision), 3),
                "recall": round(float(recall), 3),
                "f1": round(float(f1), 3),
                "positive_rate": round(float(y_h.mean()), 3),
            }
        return metrics

    def _train_fallback(self, X: np.ndarray, y: np.ndarray) -> Dict:
        from sklearn.neural_network import MLPClassifier
        from sklearn.preprocessing import StandardScaler

        logger.warning("PyTorch indisponível — usando MLP temporal fallback")
        n_samples, seq_len, n_features = X.shape
        self._scaler = StandardScaler()
        flat = X.reshape(n_samples, seq_len * n_features)
        X_scaled = self._scaler.fit_transform(flat)

        self._fallback_models = []
        metrics = {}
        horizon_names = ["event_6h", "event_24h", "event_72h"]

        for h in range(y.shape[1]):
            clf = MLPClassifier(
                hidden_layer_sizes=(256, 128, 64),
                activation="relu",
                max_iter=200,
                early_stopping=True,
                validation_fraction=0.15,
                random_state=42,
            )
            clf.fit(X_scaled, y[:, h].astype(int))
            self._fallback_models.append(clf)
            y_h = y[:, h]
            pred = clf.predict(X_scaled)
            tp = ((pred == 1) & (y_h == 1)).sum()
            fp = ((pred == 1) & (y_h == 0)).sum()
            fn = ((pred == 0) & (y_h == 1)).sum()
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-6)
            metrics[horizon_names[h]] = {
                "accuracy": round(float(clf.score(X_scaled, y_h)), 3),
                "precision": round(float(precision), 3),
                "recall": round(float(recall), 3),
                "f1": round(float(f1), 3),
                "positive_rate": round(float(y_h.mean()), 3),
            }

        self._use_fallback = True
        with open(self.model_dir / self.FALLBACK_FILENAME, "wb") as f:
            pickle.dump({"models": self._fallback_models, "scaler": self._scaler}, f)

        self._meta = {
            "architecture": "MLP-fallback",
            "n_features": n_features,
            "seq_len": seq_len,
            "n_horizons": y.shape[1],
            "metrics": metrics,
        }
        self._save_meta()

        return {
            "status": "trained_fallback",
            "architecture": "MLP-fallback",
            "samples": n_samples,
            "metrics": metrics,
            "model_path": str(self.model_dir / self.FALLBACK_FILENAME),
        }

    def _predict_fallback(self, X: np.ndarray) -> np.ndarray:
        n_samples = X.shape[0]
        flat = X.reshape(n_samples, -1)
        if self._scaler:
            flat = self._scaler.transform(flat)
        preds = []
        for clf in self._fallback_models:
            proba = clf.predict_proba(flat)
            preds.append(proba[:, 1] if proba.shape[1] > 1 else proba[:, 0])
        return np.column_stack(preds)

    def _save_checkpoint(self) -> None:
        if self._model is None:
            return
        torch.save({
            "model_state": self._model.state_dict(),
            "n_features": self._model.n_features,
            "seq_len": self._model.seq_len,
            "n_horizons": self._model.n_horizons,
        }, self.model_dir / self.MODEL_FILENAME)
        if self._scaler:
            with open(self.model_dir / self.SCALER_FILENAME, "wb") as f:
                pickle.dump(self._scaler, f)

    def _load_checkpoint(self) -> bool:
        fb_path = self.model_dir / self.FALLBACK_FILENAME
        if fb_path.exists():
            with open(fb_path, "rb") as f:
                data = pickle.load(f)
            self._fallback_models = data["models"]
            self._scaler = data.get("scaler")
            self._use_fallback = True
            meta_path = self.model_dir / self.META_FILENAME
            if meta_path.exists():
                with open(meta_path) as f:
                    self._meta = json.load(f)
            return True

        path = self.model_dir / self.MODEL_FILENAME
        if not path.exists() or not TORCH_AVAILABLE:
            return False
        ckpt = torch.load(path, map_location=self._device, weights_only=False)
        self._model = TCNLSTMTemporalModel(
            n_features=ckpt["n_features"],
            seq_len=ckpt["seq_len"],
            n_horizons=ckpt["n_horizons"],
        ).to(self._device)
        self._model.load_state_dict(ckpt["model_state"])
        self._model.eval()

        scaler_path = self.model_dir / self.SCALER_FILENAME
        if scaler_path.exists():
            with open(scaler_path, "rb") as f:
                self._scaler = pickle.load(f)

        meta_path = self.model_dir / self.META_FILENAME
        if meta_path.exists():
            with open(meta_path) as f:
                self._meta = json.load(f)
        return True

    def _save_meta(self) -> None:
        with open(self.model_dir / self.META_FILENAME, "w") as f:
            json.dump(self._meta, f, indent=2)