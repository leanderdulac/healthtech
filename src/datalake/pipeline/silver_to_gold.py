import logging
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DataLayer, MetricType
from src.datalake.schemas.gold import GoldDailySummary, GoldHourlyVitals, GoldPatientAlert
from src.datalake.storage.interface import LakehouseStore

logger = logging.getLogger(__name__)


class SilverToGoldTransformer:
    """
    ETL Silver → Gold:
    - Agregações horárias de sinais vitais
    - Resumos diários 24h por paciente
    - Geração de alertas clínicos
    """

    ALERT_RULES = {
        "tachycardia": {"metric": MetricType.HEART_RATE, "threshold": 120, "severity": "high"},
        "bradycardia": {"metric": MetricType.HEART_RATE, "threshold": 45, "severity": "medium", "direction": "below"},
        "hypoxemia": {"metric": MetricType.SPO2, "threshold": 92, "severity": "critical", "direction": "below"},
        "high_stress": {"metric": MetricType.STRESS_INDEX, "threshold": 80, "severity": "medium"},
    }

    def __init__(self, store: LakehouseStore, config: LakehouseConfig):
        self.store = store
        self.config = config

    def transform(
        self,
        partition_dates: Optional[List[str]] = None,
        patient_ids: Optional[List[str]] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        silver_df = self.store.read_layer(
            layer=DataLayer.SILVER,
            partition_dates=partition_dates,
            patient_ids=patient_ids,
        )

        if silver_df.empty:
            logger.warning("Silver vazio — nada para agregar em Gold")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        silver_df["window_start"] = pd.to_datetime(silver_df["window_start"], utc=True)

        hourly_df = self._build_hourly_vitals(silver_df)
        daily_df = self._build_daily_summaries(silver_df, hourly_df)
        alerts_df = self._build_alerts(silver_df)

        self._persist_gold(hourly_df, daily_df, alerts_df)
        return hourly_df, daily_df, alerts_df

    def _build_hourly_vitals(self, silver_df: pd.DataFrame) -> pd.DataFrame:
        silver_df["hour_bucket"] = silver_df["window_start"].dt.floor("h")
        expected_readings_per_hour = 3600 / self.config.reconciliation_window_seconds

        rows = []
        for (patient_id, hour), group in silver_df.groupby(["patient_id", "hour_bucket"]):
            hr = group[group["metric_type"] == MetricType.HEART_RATE.value]
            spo2 = group[group["metric_type"] == MetricType.SPO2.value]
            hrv = group[group["metric_type"] == MetricType.HRV.value]
            steps = group[group["metric_type"] == MetricType.STEPS.value]
            stress = group[group["metric_type"] == MetricType.STRESS_INDEX.value]

            anomaly_count = int(group["is_anomaly"].sum()) if "is_anomaly" in group.columns else 0
            coverage = len(hr) / expected_readings_per_hour if not hr.empty else 0.0

            risk_score = self._compute_risk_score(hr, spo2, stress, anomaly_count)

            rows.append(GoldHourlyVitals(
                patient_id=patient_id,
                hour_bucket=hour.to_pydatetime().replace(tzinfo=None),
                avg_heart_rate=float(hr["metric_value"].mean()) if not hr.empty else 0.0,
                min_heart_rate=float(hr["metric_value"].min()) if not hr.empty else 0.0,
                max_heart_rate=float(hr["metric_value"].max()) if not hr.empty else 0.0,
                avg_spo2=float(spo2["metric_value"].mean()) if not spo2.empty else 0.0,
                avg_hrv=float(hrv["metric_value"].mean()) if not hrv.empty else 0.0,
                total_steps=int(steps["metric_value"].max()) if not steps.empty else 0,
                avg_stress=float(stress["metric_value"].mean()) if not stress.empty else 0.0,
                reading_coverage=min(1.0, coverage),
                anomaly_count=anomaly_count,
                risk_score=risk_score,
            ).to_dict())

        return pd.DataFrame(rows)

    def _build_daily_summaries(
        self,
        silver_df: pd.DataFrame,
        hourly_df: pd.DataFrame,
    ) -> pd.DataFrame:
        silver_df["summary_date"] = silver_df["window_start"].dt.date
        rows = []

        for (patient_id, summary_date), group in silver_df.groupby(["patient_id", "summary_date"]):
            hr = group[group["metric_type"] == MetricType.HEART_RATE.value]
            spo2 = group[group["metric_type"] == MetricType.SPO2.value]
            hrv = group[group["metric_type"] == MetricType.HRV.value]
            steps = group[group["metric_type"] == MetricType.STEPS.value]
            stress = group[group["metric_type"] == MetricType.STRESS_INDEX.value]

            resting_hr = hr[hr.get("activity_context", pd.Series()) == "resting"]["metric_value"]
            if resting_hr.empty and not hr.empty:
                resting_hr = hr.nsmallest(max(1, len(hr) // 4))["metric_value"]

            sleep_hours = len(group[group.get("sleep_context", pd.Series()) != "awake"]) * (
                self.config.reconciliation_window_seconds / 3600
            )

            patient_hourly = hourly_df[hourly_df["patient_id"] == patient_id] if not hourly_df.empty else pd.DataFrame()
            coverage = float(patient_hourly["reading_coverage"].mean()) if not patient_hourly.empty else 0.0
            anomaly_episodes = int(group["is_anomaly"].sum()) if "is_anomaly" in group.columns else 0
            risk = float(patient_hourly["risk_score"].max()) if not patient_hourly.empty else 0.0

            rows.append(GoldDailySummary(
                patient_id=patient_id,
                summary_date=summary_date,
                avg_resting_hr=float(resting_hr.mean()) if len(resting_hr) > 0 else 0.0,
                max_hr=float(hr["metric_value"].max()) if not hr.empty else 0.0,
                min_hr=float(hr["metric_value"].min()) if not hr.empty else 0.0,
                total_steps=int(steps["metric_value"].max()) if not steps.empty else 0,
                sleep_hours=round(sleep_hours, 2),
                deep_sleep_pct=round(sleep_hours / 24 * 100, 1) if sleep_hours else 0.0,
                avg_spo2=float(spo2["metric_value"].mean()) if not spo2.empty else 0.0,
                avg_hrv=float(hrv["metric_value"].mean()) if not hrv.empty else 0.0,
                stress_peak=float(stress["metric_value"].max()) if not stress.empty else 0.0,
                anomaly_episodes=anomaly_episodes,
                coverage_24h=min(1.0, coverage),
                clinical_risk_level=self._risk_level(risk, anomaly_episodes),
            ).to_dict())

        return pd.DataFrame(rows)

    def _build_alerts(self, silver_df: pd.DataFrame) -> pd.DataFrame:
        alerts = []
        anomaly_rows = silver_df[silver_df.get("is_anomaly", False) == True]  # noqa: E712

        for _, row in anomaly_rows.iterrows():
            metric = row["metric_type"]
            value = float(row["metric_value"])
            alert_type, severity, threshold = self._classify_alert(metric, value)

            if not alert_type:
                continue

            window_start = pd.to_datetime(row["window_start"]).to_pydatetime().replace(tzinfo=None)
            window_end = pd.to_datetime(row["window_end"]).to_pydatetime().replace(tzinfo=None)

            alerts.append(GoldPatientAlert(
                alert_id=str(uuid.uuid4()),
                patient_id=row["patient_id"],
                alert_type=alert_type,
                severity=severity,
                metric_type=metric,
                trigger_value=value,
                threshold=threshold,
                window_start=window_start,
                window_end=window_end,
                duration_minutes=(window_end - window_start).total_seconds() / 60,
                devices_involved=row.get("devices_involved", []),
                created_at=datetime.utcnow(),
            ).to_dict())

        return pd.DataFrame(alerts)

    def _classify_alert(self, metric: str, value: float) -> Tuple[Optional[str], str, float]:
        for alert_name, rule in self.ALERT_RULES.items():
            if rule["metric"].value != metric:
                continue
            direction = rule.get("direction", "above")
            threshold = rule["threshold"]
            triggered = value < threshold if direction == "below" else value > threshold
            if triggered:
                return alert_name, rule["severity"], threshold
        return None, "", 0.0

    @staticmethod
    def _compute_risk_score(hr, spo2, stress, anomaly_count: int) -> float:
        score = 0.0
        if not hr.empty:
            avg_hr = hr["metric_value"].mean()
            if avg_hr > 100:
                score += min(0.4, (avg_hr - 100) / 100)
            if avg_hr < 50:
                score += 0.3
        if not spo2.empty and spo2["metric_value"].mean() < 94:
            score += 0.3
        if not stress.empty and stress["metric_value"].mean() > 70:
            score += 0.2
        score += min(0.3, anomaly_count * 0.05)
        return min(1.0, round(score, 3))

    @staticmethod
    def _risk_level(risk_score: float, anomaly_episodes: int) -> str:
        if risk_score >= 0.7 or anomaly_episodes >= 10:
            return "critical"
        if risk_score >= 0.4 or anomaly_episodes >= 5:
            return "elevated"
        if risk_score >= 0.2:
            return "moderate"
        return "low"

    def _persist_gold(
        self,
        hourly_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        alerts_df: pd.DataFrame,
    ) -> None:
        if not hourly_df.empty:
            for partition_str, group in hourly_df.groupby("partition_date"):
                self.store.write_gold("hourly_vitals", group, date.fromisoformat(str(partition_str)))

        if not daily_df.empty:
            for partition_str, group in daily_df.groupby("partition_date"):
                self.store.write_gold("daily_summary", group, date.fromisoformat(str(partition_str)))

        if not alerts_df.empty:
            self.store.write_gold("patient_alerts", alerts_df)