"""
Filtragem de sinais biomédicos wearable.

Pipeline:
  1. Rejeição de artefatos (Hampel / MAD)
  2. Filtro de Kalman 1D (estado: valor + derivada)
  3. Baseline adaptativo personalizado (EWMA)
  4. Estimativa de ruído (variância residual)
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

from src.clinical_intelligence.models import DenoisedSignal, PatientBaseline

logger = logging.getLogger(__name__)


class KalmanFilter1D:
    """
    Filtro de Kalman escalar para sinais vitais.
    Estado: [valor, taxa_de_variacao].
    Modelo de observação: z = Hx + v, com ruído adaptativo.
    """

    def __init__(
        self,
        process_noise: float = 0.5,
        measurement_noise: float = 4.0,
        initial_value: float = 70.0,
    ):
        self.x = np.array([initial_value, 0.0])
        self.P = np.eye(2) * 10.0
        self.F = np.array([[1.0, 1.0], [0.0, 0.95]])
        self.H = np.array([[1.0, 0.0]])
        self.Q = np.eye(2) * process_noise
        self.R = np.array([[measurement_noise]])

    def update(self, measurement: float) -> float:
        x_pred = self.F @ self.x
        P_pred = self.F @ self.P @ self.F.T + self.Q
        y = measurement - (self.H @ x_pred)[0]
        S = self.H @ P_pred @ self.H.T + self.R
        K = P_pred @ self.H.T @ np.linalg.inv(S)
        self.x = x_pred + (K.flatten() * y)
        self.P = (np.eye(2) - K @ self.H) @ P_pred
        return float(self.x[0])

    def filter_series(self, values: np.ndarray) -> np.ndarray:
        out = np.zeros_like(values, dtype=float)
        for i, v in enumerate(values):
            out[i] = self.update(float(v))
        return out


def hampel_filter(
    values: np.ndarray,
    window: int = 7,
    n_sigma: float = 3.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Filtro de Hampel para detecção de outliers (artefatos de movimento,
    poor skin contact, ectopic beats).
    Retorna (valores_corrigidos, máscara_de_artefatos).
    """
    n = len(values)
    if n < 3:
        return values.copy(), np.zeros(n, dtype=bool)

    corrected = values.copy().astype(float)
    artifact_mask = np.zeros(n, dtype=bool)
    half = window // 2

    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        window_vals = corrected[lo:hi]
        median = np.median(window_vals)
        mad = np.median(np.abs(window_vals - median))
        if mad < 1e-6:
            continue
        threshold = n_sigma * 1.4826 * mad
        if abs(corrected[i] - median) > threshold:
            corrected[i] = median
            artifact_mask[i] = True

    return corrected, artifact_mask


def adaptive_baseline(
    values: np.ndarray,
    alpha: float = 0.05,
    initial: Optional[float] = None,
) -> np.ndarray:
    """Baseline EWMA adaptativo — norma personalizada do paciente."""
    baseline = np.zeros(len(values), dtype=float)
    if len(values) == 0:
        return baseline
    baseline[0] = initial if initial is not None else float(values[0])
    for i in range(1, len(values)):
        baseline[i] = alpha * values[i] + (1 - alpha) * baseline[i - 1]
    return baseline


class WearableSignalProcessor:
    """Pipeline completo de denoising para telemetria wearable."""

    METRIC_NOISE = {
        "heart_rate": {"process": 1.0, "measurement": 9.0, "hampel_window": 9},
        "spo2": {"process": 0.1, "measurement": 1.0, "hampel_window": 5},
        "hrv": {"process": 2.0, "measurement": 25.0, "hampel_window": 5},
        "stress": {"process": 1.0, "measurement": 15.0, "hampel_window": 7},
    }

    def process(
        self,
        metric: str,
        values: List[float],
        timestamps: List[str],
        quality_scores: Optional[List[float]] = None,
        baseline: Optional[PatientBaseline] = None,
    ) -> DenoisedSignal:
        arr = np.array(values, dtype=float)
        if len(arr) == 0:
            return DenoisedSignal(
                metric=metric, raw=[], filtered=[], timestamps=[],
                noise_estimate=0.0, artifact_ratio=0.0, quality_score=0.0,
            )

        params = self.METRIC_NOISE.get(metric, {"process": 1.0, "measurement": 5.0, "hampel_window": 7})
        initial = self._baseline_initial(metric, baseline)

        cleaned, artifacts = hampel_filter(arr, window=params["hampel_window"])
        kf = KalmanFilter1D(
            process_noise=params["process"],
            measurement_noise=params["measurement"],
            initial_value=initial or float(cleaned[0]),
        )
        filtered = kf.filter_series(cleaned)

        residual = cleaned - filtered
        noise_est = float(np.std(residual)) if len(residual) > 1 else 0.0
        artifact_ratio = float(artifacts.sum() / len(artifacts))

        if quality_scores:
            q = float(np.mean(quality_scores))
        else:
            q = max(0.0, 1.0 - artifact_ratio * 2)

        return DenoisedSignal(
            metric=metric,
            raw=arr.tolist(),
            filtered=filtered.tolist(),
            timestamps=timestamps,
            noise_estimate=noise_est,
            artifact_ratio=artifact_ratio,
            quality_score=q,
        )

    @staticmethod
    def _baseline_initial(metric: str, baseline: Optional[PatientBaseline]) -> Optional[float]:
        if baseline is None:
            return None
        mapping = {
            "heart_rate": baseline.resting_hr,
            "spo2": baseline.baseline_spo2,
            "hrv": baseline.baseline_hrv,
        }
        return mapping.get(metric)

    def deviation_from_baseline(
        self,
        signal: DenoisedSignal,
        baseline: PatientBaseline,
    ) -> np.ndarray:
        """Desvio normalizado (z-score contextual) em relação ao baseline do paciente."""
        filtered = np.array(signal.filtered)
        if len(filtered) == 0:
            return np.array([])

        ref = {
            "heart_rate": baseline.resting_hr,
            "spo2": baseline.baseline_spo2,
            "hrv": baseline.baseline_hrv,
        }.get(signal.metric, float(np.mean(filtered)))

        std = max(signal.noise_estimate, 1.0)
        return (filtered - ref) / std

    def trajectory_slope(self, signal: DenoisedSignal, window: int = 12) -> float:
        """Inclinação da tendência recente (regressão linear nos últimos N pontos)."""
        y = np.array(signal.filtered[-window:])
        if len(y) < 3:
            return 0.0
        x = np.arange(len(y), dtype=float)
        slope = np.polyfit(x, y, 1)[0]
        return float(slope)