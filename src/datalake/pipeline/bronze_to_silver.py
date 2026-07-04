import logging
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DataLayer, MetricType, QualityFlag
from src.datalake.storage.interface import LakehouseStore

logger = logging.getLogger(__name__)


class BronzeToSilverTransformer:
    """
    ETL Bronze → Silver:
    - Filtra registros inválidos
    - Reconcilia leituras redundantes de múltiplos dispositivos
    - Enriquece com contexto de sono/atividade
    - Detecta anomalias por janela temporal
    """

    ANOMALY_THRESHOLDS = {
        MetricType.HEART_RATE: {"low": 45, "high": 120, "critical_high": 150},
        MetricType.SPO2: {"low": 92, "high": 100},
        MetricType.HRV: {"low": 15, "high": 200},
        MetricType.STRESS_INDEX: {"low": 0, "high": 75, "critical_high": 85},
    }

    def __init__(self, store: LakehouseStore, config: LakehouseConfig):
        self.store = store
        self.config = config

    def transform(
        self,
        partition_dates: Optional[List[str]] = None,
        patient_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        bronze_df = self.store.read_layer(
            layer=DataLayer.BRONZE,
            partition_dates=partition_dates,
            patient_ids=patient_ids,
        )

        if bronze_df.empty:
            logger.warning("Bronze vazio — nada para transformar")
            return pd.DataFrame()

        bronze_df = bronze_df[
            ~bronze_df.get("quality_flags", pd.Series([""] * len(bronze_df))).astype(str).str.contains("out_of_range")
        ].copy()

        bronze_df["timestamp_utc"] = pd.to_datetime(bronze_df["timestamp_utc"], utc=True)
        silver_records = []

        for (patient_id, metric_type), group in bronze_df.groupby(["patient_id", "metric_type"]):
            silver_records.extend(
                self._reconcile_patient_metric(group, patient_id, metric_type)
            )

        if not silver_records:
            return pd.DataFrame()

        silver_df = pd.DataFrame(silver_records)
        self._persist_silver(silver_df)
        return silver_df

    def _reconcile_patient_metric(
        self,
        group: pd.DataFrame,
        patient_id: str,
        metric_type: str,
    ) -> List[dict]:
        window = f"{self.config.reconciliation_window_seconds}s"
        group = group.sort_values("timestamp_utc")

        reconciled = group.groupby(
            pd.Grouper(key="timestamp_utc", freq=window)
        ).agg(
            metric_value=("metric_value", "mean"),
            metric_std=("metric_value", "std"),
            devices_involved=("device_id", lambda x: list(set(x))),
            reading_count=("event_id", "count"),
            avg_confidence=("signal_confidence", "mean"),
            activity_context=("raw_payload", lambda x: self._extract_context(x, "activity_context")),
            sleep_context=("raw_payload", lambda x: self._extract_context(x, "sleep_context")),
        ).dropna(subset=["metric_value"]).reset_index()

        records = []
        window_secs = self.config.reconciliation_window_seconds

        for _, row in reconciled.iterrows():
            value = float(row["metric_value"])
            std = float(row["metric_std"]) if pd.notna(row["metric_std"]) else 0.0
            confidence = float(row["avg_confidence"])
            quality_score = min(1.0, confidence * (1.0 - min(std / max(value, 1), 0.3)))

            is_anomaly, anomaly_score = self._detect_anomaly(
                metric_type, value,
                activity_context=row["activity_context"],
                sleep_context=row["sleep_context"],
            )
            flags = [QualityFlag.RECONCILED.value]
            if is_anomaly:
                flags.append(QualityFlag.OUT_OF_RANGE.value)

            window_start = row["timestamp_utc"].to_pydatetime().replace(tzinfo=None)
            records.append({
                "record_id": str(uuid.uuid4()),
                "patient_id": patient_id,
                "window_start": window_start.isoformat(),
                "window_end": (window_start + timedelta(seconds=window_secs)).isoformat(),
                "metric_type": metric_type,
                "metric_value": round(value, 2),
                "metric_std": round(std, 2),
                "unit": self._resolve_unit(metric_type),
                "devices_involved": row["devices_involved"],
                "reading_count": int(row["reading_count"]),
                "quality_score": round(quality_score, 3),
                "quality_flags": flags,
                "is_anomaly": is_anomaly,
                "anomaly_score": round(anomaly_score, 3),
                "activity_context": row["activity_context"],
                "sleep_context": row["sleep_context"],
                "processed_at": datetime.utcnow().isoformat(),
                "partition_date": window_start.strftime("%Y-%m-%d"),
            })

        return records

    @staticmethod
    def _extract_context(payloads, key: str) -> str:
        for p in payloads:
            if isinstance(p, dict) and key in p:
                return p[key]
        return "unknown"

    def _detect_anomaly(
        self,
        metric_type: str,
        value: float,
        activity_context: str = "unknown",
        sleep_context: str = "unknown",
    ) -> tuple:
        try:
            metric = MetricType(metric_type)
        except ValueError:
            return False, 0.0

        thresholds = dict(self.ANOMALY_THRESHOLDS.get(metric, {}))
        if not thresholds:
            return False, 0.0

        if metric == MetricType.HEART_RATE:
            if activity_context == "active":
                thresholds["high"] = 160
                thresholds["critical_high"] = 190
            elif sleep_context in ("deep_sleep", "light_sleep"):
                thresholds["high"] = 90
                thresholds["low"] = 40

        score = 0.0
        is_anomaly = False

        if "low" in thresholds and value < thresholds["low"]:
            is_anomaly = True
            score = min(1.0, (thresholds["low"] - value) / thresholds["low"])

        if "high" in thresholds and value > thresholds["high"]:
            is_anomaly = True
            score = max(score, min(1.0, (value - thresholds["high"]) / thresholds["high"]))

        if "critical_high" in thresholds and value > thresholds["critical_high"]:
            is_anomaly = True
            score = 1.0

        return is_anomaly, score

    @staticmethod
    def _resolve_unit(metric_type: str) -> str:
        units = {
            MetricType.HEART_RATE.value: "bpm",
            MetricType.SPO2.value: "%",
            MetricType.HRV.value: "ms",
            MetricType.STEPS.value: "count",
            MetricType.STRESS_INDEX.value: "index",
        }
        return units.get(metric_type, "unit")

    def _persist_silver(self, silver_df: pd.DataFrame) -> None:
        for partition_str, group in silver_df.groupby("partition_date"):
            partition_date = date.fromisoformat(str(partition_str))
            self.store.write_silver(group.drop(columns=["partition_date"], errors="ignore"), partition_date)