from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


GOLD_HOURLY_VITALS_SCHEMA: Dict[str, str] = {
    "patient_id": "string",
    "hour_bucket": "timestamp",
    "avg_heart_rate": "float",
    "min_heart_rate": "float",
    "max_heart_rate": "float",
    "avg_spo2": "float",
    "avg_hrv": "float",
    "total_steps": "integer",
    "avg_stress": "float",
    "reading_coverage": "float",
    "anomaly_count": "integer",
    "risk_score": "float",
    "partition_date": "date",
}

GOLD_DAILY_SUMMARY_SCHEMA: Dict[str, str] = {
    "patient_id": "string",
    "summary_date": "date",
    "avg_resting_hr": "float",
    "max_hr": "float",
    "min_hr": "float",
    "total_steps": "integer",
    "sleep_hours": "float",
    "deep_sleep_pct": "float",
    "avg_spo2": "float",
    "avg_hrv": "float",
    "stress_peak": "float",
    "anomaly_episodes": "integer",
    "coverage_24h": "float",
    "clinical_risk_level": "string",
    "partition_date": "date",
}

GOLD_PATIENT_ALERTS_SCHEMA: Dict[str, str] = {
    "alert_id": "string",
    "patient_id": "string",
    "alert_type": "string",
    "severity": "string",
    "metric_type": "string",
    "trigger_value": "float",
    "threshold": "float",
    "window_start": "timestamp",
    "window_end": "timestamp",
    "duration_minutes": "float",
    "devices_involved": "array<string>",
    "created_at": "timestamp",
}


@dataclass
class GoldHourlyVitals:
    patient_id: str
    hour_bucket: datetime
    avg_heart_rate: float
    min_heart_rate: float
    max_heart_rate: float
    avg_spo2: float
    avg_hrv: float
    total_steps: int
    avg_stress: float
    reading_coverage: float
    anomaly_count: int
    risk_score: float

    @property
    def partition_date(self) -> str:
        return self.hour_bucket.strftime("%Y-%m-%d")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["partition_date"] = self.partition_date
        return data


@dataclass
class GoldDailySummary:
    patient_id: str
    summary_date: date
    avg_resting_hr: float
    max_hr: float
    min_hr: float
    total_steps: int
    sleep_hours: float
    deep_sleep_pct: float
    avg_spo2: float
    avg_hrv: float
    stress_peak: float
    anomaly_episodes: int
    coverage_24h: float
    clinical_risk_level: str

    @property
    def partition_date(self) -> str:
        return self.summary_date.isoformat()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["summary_date"] = self.summary_date.isoformat()
        data["partition_date"] = self.partition_date
        return data


@dataclass
class GoldPatientAlert:
    alert_id: str
    patient_id: str
    alert_type: str
    severity: str
    metric_type: str
    trigger_value: float
    threshold: float
    window_start: datetime
    window_end: datetime
    duration_minutes: float
    devices_involved: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        return data