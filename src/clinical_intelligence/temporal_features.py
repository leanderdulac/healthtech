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
        subsample: int = 15,
        feature_stride: int = 3,
        horizon_steps: Optional[Dict[str, int]] = None,
    ):
        self.seq_len = seq_len
        self.subsample = subsample
        self.feature_stride = feature_stride
        self.horizon_steps = horizon_steps or {
            "event_6h": 8,
            "event_24h": 24,
            "event_72h": 48,
        }
        self.processor = WearableSignalProcessor()
        self.ghost_detector = GhostSignalDetector()
        self.fuzzy_engine = FuzzyClinicalEngine()
        self.prognostic = PrognosticEngine()
        self.pipeline = ClinicalIntelligencePipeline()

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
        feature_matrix = self._compute_feature_matrix(vitals_df, baseline, hemodynamic_score)
        labels = self._compute_labels(vitals_df)

        sequences_X, sequences_y = [], []
        max_horizon = max(self.horizon_steps.values())

        for end_idx in range(self.seq_len, len(feature_matrix) - max_horizon):
            start_idx = end_idx - self.seq_len
            seq = feature_matrix[start_idx:end_idx]
            if np.any(np.isnan(seq)) or np.any(np.isinf(seq)):
                continue

            label_vec = []
            for h_name in HORIZON_NAMES:
                h_steps = self.horizon_steps[h_name]
                min_run = 2 if h_name == "event_6h" else 3
                label_vec.append(
                    1.0 if self._future_event(labels, end_idx, h_steps, min_run) else 0.0
                )

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

    def _compute_labels(self, vitals_df: pd.DataFrame) -> np.ndarray:
        hr = vitals_df["heart_rate"].values
        spo2 = vitals_df["spo2"].values
        stress = vitals_df.get("stress_index", pd.Series(0, index=vitals_df.index)).values

        severe = (
            (hr > 130) | (hr < 40) | (spo2 < 90) | (stress > 85)
        )
        moderate = vitals_df["is_anomaly"].astype(bool).values & (
            (hr > 115) | (spo2 < 93)
        )
        return severe | moderate

    def _future_event(self, labels: np.ndarray, start: int, steps: int, min_run: int = 2) -> bool:
        window = labels[start:start + steps]
        if not window.any():
            return False
        run = 0
        for v in window:
            if v:
                run += 1
                if run >= min_run:
                    return True
            else:
                run = 0
        return False