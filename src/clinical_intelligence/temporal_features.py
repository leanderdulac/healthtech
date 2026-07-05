"""
Construtor de sequências temporais com features ghost + fuzzy por timestep.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.clinical_intelligence.fuzzy_engine import FuzzyClinicalEngine
from src.clinical_intelligence.ghost_signals import GhostSignalDetector
from src.clinical_intelligence.models import DenoisedSignal, PatientBaseline
from src.clinical_intelligence.pipeline import ClinicalIntelligencePipeline
from src.clinical_intelligence.prognostic_engine import PrognosticEngine
from src.clinical_intelligence.signal_processing import WearableSignalProcessor

logger = logging.getLogger(__name__)

GHOST_NAMES = [
    "autonomic_imbalance",
    "hidden_hypoxemia",
    "stress_activity_decoupling",
    "pulse_irregularity",
    "recovery_deficit",
    "circadian_desync",
    "hemodynamic_irregularity_proxy",
    "semantic_cardiovascular_risk",
]

TEMPORAL_FEATURE_COLUMNS = (
    ["hr", "spo2", "hrv", "stress", "quality_score"]
    + ["hr_deviation", "spo2_risk", "hrv_suppression", "noise_level",
       "artifact_ratio", "trajectory_slope", "persistence"]
    + [f"ghost_{g}" for g in GHOST_NAMES]
    + ["fuzzy_event_prob", "fuzzy_fp_risk", "fuzzy_noise_gate", "fuzzy_persistence"]
)

HORIZON_NAMES = ["event_6h", "event_24h", "event_72h"]


class TemporalFeatureBuilder:
    """Gera tensores (N, seq_len, n_features) + labels multi-horizonte."""

    def __init__(
        self,
        seq_len: int = 32,
        subsample: int = 60,
        feature_stride: int = 4,
        horizon_steps: Optional[Dict[str, int]] = None,
        reconciliation_seconds: int = 5,
        exclusive_horizons: bool = True,
    ):
        self.seq_len = seq_len
        self.subsample = subsample
        self.feature_stride = feature_stride
        self.reconciliation_seconds = reconciliation_seconds
        self.exclusive_horizons = exclusive_horizons
        self.minutes_per_step = (subsample * reconciliation_seconds) / 60.0
        self.horizon_steps = horizon_steps or self._default_horizon_steps()
        self.processor = WearableSignalProcessor()
        self.ghost_detector = GhostSignalDetector()
        self.fuzzy_engine = FuzzyClinicalEngine()
        self.prognostic = PrognosticEngine()
        self.pipeline = ClinicalIntelligencePipeline()

    def _default_horizon_steps(self) -> Dict[str, int]:
        """Converte horas reais em passos temporais conforme subsample."""
        def steps(hours: float) -> int:
            return max(1, int(hours * 60 / self.minutes_per_step))

        return {
            "event_6h": steps(6),
            "event_24h": steps(24),
            "event_72h": steps(72),
        }

    def horizon_summary(self) -> Dict[str, str]:
        return {
            name: f"{steps} passos ≈ {steps * self.minutes_per_step / 60:.1f}h"
            for name, steps in self.horizon_steps.items()
        }

    def build_from_datalake(
        self,
        query_engine,
        patient_profiles: List,
        partition_dates: Optional[List[str]] = None,
        hemodynamic_scores: Optional[Dict[str, float]] = None,
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        from src.datalake.extraction.filters import QueryFilters

        all_X, all_y = [], []
        patient_ids = []

        for profile in patient_profiles:
            vitals = query_engine.extract("vitals", QueryFilters(
                patient_id=profile.patient_id,
                partition_dates=partition_dates,
            ))
            if vitals.empty or len(vitals) < self.seq_len + 5:
                continue

            baseline = self.pipeline._profile_to_baseline(profile)
            hemo = (hemodynamic_scores or {}).get(profile.patient_id, 0.0)

            X, y = self.build_patient_sequences(vitals, baseline, hemo)
            if len(X) == 0:
                logger.warning(
                    "Sem sequências para %s (vitals=%d, min_necessário≈%d)",
                    profile.patient_id, len(vitals),
                    self.horizon_steps["event_72h"] + self.seq_len + 10,
                )
                continue

            all_X.append(X)
            all_y.append(y)
            patient_ids.extend([profile.patient_id] * len(X))
            logger.info("Sequências %s: %d amostras", profile.patient_id, len(X))

        if not all_X:
            return np.array([]), np.array([]), []

        return np.vstack(all_X), np.vstack(all_y), patient_ids

    def build_patient_sequences(
        self,
        vitals_df: pd.DataFrame,
        baseline: PatientBaseline,
        hemodynamic_score: float = 0.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        vitals_df = self._prepare_vitals(vitals_df)
        self._calibrate_horizons_from_timestamps(vitals_df)
        feature_matrix = self._compute_feature_matrix(vitals_df, baseline, hemodynamic_score)
        risk_series = self._compute_risk_series(vitals_df, baseline)

        sequences_X, sequences_y = [], []
        h6 = self.horizon_steps["event_6h"]
        h24 = self.horizon_steps["event_24h"]
        h72 = self.horizon_steps["event_72h"]
        max_end = len(feature_matrix) - h72

        for end_idx in range(self.seq_len, max_end):
            start_idx = end_idx - self.seq_len
            seq = feature_matrix[start_idx:end_idx]
            if np.any(np.isnan(seq)) or np.any(np.isinf(seq)):
                continue

            current_risk = float(risk_series[end_idx])
            window_6h = risk_series[end_idx:end_idx + h6]
            window_24h = risk_series[end_idx + h6:end_idx + h24]
            window_72h = risk_series[end_idx + h24:end_idx + h72]

            label_vec = [
                1.0 if (len(window_6h) > 0 and window_6h.max() > 0.50 and window_6h.mean() > 0.38) else 0.0,
                1.0 if (len(window_24h) > 0 and window_24h.mean() > 0.36 and window_24h.max() > 0.48) else 0.0,
                1.0 if (
                    len(window_72h) > 0
                    and window_72h.mean() > 0.34
                    and window_72h.max() > 0.44
                    and current_risk < 0.30
                ) else 0.0,
            ]

            sequences_X.append(seq)
            sequences_y.append(label_vec)

        if not sequences_X:
            return np.array([]), np.array([])

        return np.array(sequences_X, dtype=np.float32), np.array(sequences_y, dtype=np.float32)

    def _prepare_vitals(self, vitals_df: pd.DataFrame) -> pd.DataFrame:
        vitals_df = vitals_df.sort_values("window_start").reset_index(drop=True)
        vitals_df = vitals_df.iloc[::self.subsample].reset_index(drop=True)

        for col in ["heart_rate", "spo2", "hrv"]:
            if col not in vitals_df.columns:
                vitals_df[col] = np.nan
        vitals_df[["heart_rate", "spo2", "hrv"]] = vitals_df[
            ["heart_rate", "spo2", "hrv"]
        ].ffill().bfill()

        if "stress_index" not in vitals_df.columns:
            vitals_df["stress_index"] = vitals_df.get("stress", 0.0)
        if "quality_score" not in vitals_df.columns:
            vitals_df["quality_score"] = 1.0
        if "is_anomaly" not in vitals_df.columns:
            vitals_df["is_anomaly"] = False

        return vitals_df

    def _calibrate_horizons_from_timestamps(self, vitals_df: pd.DataFrame) -> None:
        """Calibra passos temporais a partir dos timestamps reais (não assume 5s)."""
        if len(vitals_df) < 2:
            return
        ts = pd.to_datetime(vitals_df["window_start"])
        delta_min = ts.diff().dropna().dt.total_seconds().median() / 60.0
        if delta_min > 0:
            self.minutes_per_step = float(delta_min)
            self.horizon_steps = self._default_horizon_steps()

    def _compute_feature_matrix(
        self,
        vitals_df: pd.DataFrame,
        baseline: PatientBaseline,
        hemodynamic_score: float,
    ) -> np.ndarray:
        n = len(vitals_df)
        n_features = len(TEMPORAL_FEATURE_COLUMNS)
        matrix = np.zeros((n, n_features), dtype=np.float32)
        ontology = self.pipeline._load_ontology_domains()

        denoised = self._denoise_full_series(vitals_df, baseline)

        for t in range(0, n, self.feature_stride):
            end = t + 1
            start = max(0, end - 40)
            window_df = vitals_df.iloc[start:end]
            signals = self._slice_signals(denoised, start, end)

            ghosts = self.ghost_detector.detect(
                signals, baseline, hemodynamic_score, ontology,
            )
            persistence = self.prognostic.compute_persistence(signals, baseline)

            fuzzy = self.fuzzy_engine.assess(
                hr_deviation=self.prognostic.hr_deviation(signals, baseline),
                spo2_risk=self.prognostic.spo2_risk(signals, baseline),
                hrv_suppression=self.prognostic.hrv_suppression(signals, baseline),
                ghost_signals=ghosts,
                noise_level=self.prognostic.noise_level(signals),
                artifact_ratio=self.prognostic.artifact_ratio(signals),
                persistence=persistence,
                trajectory_slope=self.prognostic.trajectory_slope(signals),
                baseline=baseline,
            )

            row = self._build_feature_row(
                vitals_df.iloc[t], signals, ghosts, fuzzy, persistence, baseline,
            )

            for fill_t in range(t, min(t + self.feature_stride, n)):
                matrix[fill_t] = row

        return matrix

    def _denoise_full_series(
        self, vitals_df: pd.DataFrame, baseline: PatientBaseline,
    ) -> Dict[str, DenoisedSignal]:
        signals = {}
        metric_map = {
            "heart_rate": "heart_rate",
            "spo2": "spo2",
            "hrv": "hrv",
            "stress_index": "stress",
        }
        for col, metric in metric_map.items():
            if col not in vitals_df.columns:
                continue
            values = vitals_df[col].ffill().tolist()
            timestamps = vitals_df["window_start"].astype(str).tolist()
            quality = vitals_df["quality_score"].tolist() if "quality_score" in vitals_df.columns else None
            signals[metric] = self.processor.process(
                metric=metric,
                values=values,
                timestamps=timestamps,
                quality_scores=quality,
                baseline=baseline,
            )
        return signals

    def _slice_signals(
        self, denoised: Dict[str, DenoisedSignal], start: int, end: int,
    ) -> Dict[str, DenoisedSignal]:
        sliced = {}
        for metric, sig in denoised.items():
            sliced[metric] = DenoisedSignal(
                metric=metric,
                raw=sig.raw[start:end],
                filtered=sig.filtered[start:end],
                timestamps=sig.timestamps[start:end],
                noise_estimate=sig.noise_estimate,
                artifact_ratio=sig.artifact_ratio,
                quality_score=sig.quality_score,
            )
        return sliced

    def _build_feature_row(
        self,
        row: pd.Series,
        signals: Dict[str, DenoisedSignal],
        ghosts,
        fuzzy,
        persistence: float,
        baseline: PatientBaseline,
    ) -> np.ndarray:
        vec = np.zeros(len(TEMPORAL_FEATURE_COLUMNS), dtype=np.float32)
        idx = 0

        for metric, default in [
            ("heart_rate", baseline.resting_hr),
            ("spo2", baseline.baseline_spo2),
            ("hrv", baseline.baseline_hrv),
            ("stress", 0.0),
        ]:
            sig = signals.get(metric if metric != "stress" else "stress")
            if sig and sig.filtered:
                vec[idx] = float(sig.filtered[-1])
            else:
                col = "stress_index" if metric == "stress" else metric
                vec[idx] = float(row.get(col, default))
            idx += 1

        vec[idx] = float(row.get("quality_score", 1.0))
        idx += 1

        vec[idx] = self.prognostic.hr_deviation(signals, baseline)
        idx += 1
        vec[idx] = self.prognostic.spo2_risk(signals, baseline)
        idx += 1
        vec[idx] = self.prognostic.hrv_suppression(signals, baseline)
        idx += 1
        vec[idx] = self.prognostic.noise_level(signals)
        idx += 1
        vec[idx] = self.prognostic.artifact_ratio(signals)
        idx += 1
        vec[idx] = self.prognostic.trajectory_slope(signals)
        idx += 1
        vec[idx] = persistence
        idx += 1

        ghost_map = {g.name: g.value * g.confidence for g in ghosts}
        for gname in GHOST_NAMES:
            vec[idx] = ghost_map.get(gname, 0.0)
            idx += 1

        vec[idx] = fuzzy.event_probability
        idx += 1
        vec[idx] = fuzzy.false_positive_risk
        idx += 1
        vec[idx] = fuzzy.noise_gate
        idx += 1
        vec[idx] = persistence

        return vec

    def _compute_risk_series(
        self, vitals_df: pd.DataFrame, baseline: PatientBaseline,
    ) -> np.ndarray:
        """Score de risco contínuo [0,1] alinhado com ghost/fuzzy semantics."""
        hr = vitals_df["heart_rate"].values.astype(float)
        spo2 = vitals_df["spo2"].values.astype(float)
        hrv = vitals_df.get("hrv", pd.Series(baseline.baseline_hrv, index=vitals_df.index)).values.astype(float)
        stress = vitals_df.get("stress_index", pd.Series(0, index=vitals_df.index)).values.astype(float)
        anomaly = vitals_df["is_anomaly"].astype(float).values

        hr_risk = np.clip((hr - baseline.resting_hr - 8) / 45, 0, 1)
        spo2_risk = np.clip((baseline.baseline_spo2 - 1.5 - spo2) / 10, 0, 1)
        hrv_risk = np.clip((baseline.baseline_hrv - hrv) / baseline.baseline_hrv, 0, 1)
        stress_risk = np.clip(stress / 100, 0, 1)

        return np.clip(
            0.30 * hr_risk + 0.30 * spo2_risk + 0.20 * hrv_risk + 0.10 * stress_risk + 0.10 * anomaly,
            0, 1,
        )