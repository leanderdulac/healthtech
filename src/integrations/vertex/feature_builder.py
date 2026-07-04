import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.datalake.extraction.filters import QueryFilters
from src.datalake.extraction.query_engine import DatalakeQueryEngine
from src.datalake.schemas.base import DataLayer, MetricType

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "avg_resting_hr",
    "max_hr",
    "min_hr",
    "avg_spo2",
    "avg_hrv",
    "total_steps",
    "sleep_hours",
    "stress_peak",
    "anomaly_episodes",
    "coverage_24h",
    "total_alerts",
]

ONLINE_FEATURE_COLUMNS = [
    "bpm",
    "spo2",
    "hrv",
    "stress",
    "quality_score",
    "hour_of_day",
    "is_active",
    "is_sleeping",
]


class DatalakeFeatureBuilder:
    """Constrói features de ML a partir das camadas Gold/Silver do datalake."""

    def __init__(self, query_engine: DatalakeQueryEngine):
        self.query_engine = query_engine

    def build_batch_features(
        self,
        min_risk_score: float = 0.0,
        partition_dates: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        cohort = self.query_engine.extract("cohort", QueryFilters(
            min_risk_score=min_risk_score,
            partition_dates=partition_dates,
        ))

        if cohort.empty:
            logger.warning("Coorte vazia — gerando features a partir de daily_summary")
            cohort = self.query_engine.store.read_layer(
                layer=DataLayer.GOLD,
                table="daily_summary",
                partition_dates=partition_dates,
            )

        if cohort.empty:
            return pd.DataFrame()

        features = cohort.copy()
        for col in FEATURE_COLUMNS:
            if col not in features.columns:
                features[col] = 0.0

        features[FEATURE_COLUMNS] = features[FEATURE_COLUMNS].fillna(0)
        features["risk_label"] = features["clinical_risk_level"].map({
            "low": 0, "moderate": 1, "elevated": 2, "critical": 3,
        }).fillna(0).astype(int)

        return features

    def build_online_instances(
        self,
        patient_id: str,
        partition_date: str,
        max_records: Optional[int] = 50,
    ) -> List[Dict]:
        vitals = self.query_engine.extract("vitals", QueryFilters(
            patient_id=patient_id,
            partition_dates=[partition_date],
        ))

        if vitals.empty:
            return []

        vitals = vitals.sort_values("window_start")
        if max_records:
            vitals = vitals.tail(max_records)

        def _safe_float(val, default: float) -> float:
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return default
            return float(val)

        instances = []
        for _, row in vitals.iterrows():
            ts = pd.to_datetime(row["window_start"])
            instances.append({
                "patient_id": patient_id,
                "bpm": _safe_float(row.get("heart_rate"), 0),
                "spo2": _safe_float(row.get("spo2"), 97),
                "hrv": _safe_float(row.get("hrv"), 50),
                "stress": 0.0,
                "quality_score": _safe_float(row.get("quality_score"), 1.0),
                "hour_of_day": ts.hour,
                "is_active": 1 if 8 <= ts.hour < 18 else 0,
                "is_sleeping": 1 if ts.hour < 6 or ts.hour >= 22 else 0,
                "timestamp": ts.isoformat(),
            })

        return instances

    def build_training_matrix(self, features_df: pd.DataFrame) -> tuple:
        if features_df.empty:
            return np.array([]), np.array([])

        X = features_df[FEATURE_COLUMNS].values.astype(float)
        y = features_df.get("risk_label", pd.Series([0] * len(features_df))).values
        return X, y