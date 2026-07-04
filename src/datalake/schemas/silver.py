from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.datalake.schemas.base import DeviceType, MetricType, QualityFlag


SILVER_TELEMETRY_SCHEMA: Dict[str, str] = {
    "record_id": "string",
    "patient_id": "string",
    "window_start": "timestamp",
    "window_end": "timestamp",
    "metric_type": "string",
    "metric_value": "float",
    "metric_std": "float",
    "unit": "string",
    "devices_involved": "array<string>",
    "reading_count": "integer",
    "quality_score": "float",
    "quality_flags": "array<string>",
    "is_anomaly": "boolean",
    "anomaly_score": "float",
    "activity_context": "string",
    "sleep_context": "string",
    "processed_at": "timestamp",
    "partition_date": "date",
}


@dataclass
class SilverTelemetryRecord:
    """
    Camada Silver — telemetria reconciliada, validada e enriquecida.
    Uma janela temporal consolida leituras redundantes de múltiplos sensores.
    """

    record_id: str
    patient_id: str
    window_start: datetime
    window_end: datetime
    metric_type: MetricType
    metric_value: float
    metric_std: float
    unit: str
    devices_involved: List[str]
    reading_count: int
    quality_score: float
    quality_flags: List[QualityFlag] = field(default_factory=list)
    is_anomaly: bool = False
    anomaly_score: float = 0.0
    activity_context: Optional[str] = None
    sleep_context: Optional[str] = None
    processed_at: Optional[datetime] = None
    device_types: List[DeviceType] = field(default_factory=list)

    @property
    def partition_date(self) -> str:
        return self.window_start.strftime("%Y-%m-%d")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["metric_type"] = self.metric_type.value
        data["quality_flags"] = [f.value for f in self.quality_flags]
        data["device_types"] = [d.value for d in self.device_types]
        data["partition_date"] = self.partition_date
        if self.processed_at:
            data["processed_at"] = self.processed_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SilverTelemetryRecord":
        processed = data.get("processed_at")
        return cls(
            record_id=data["record_id"],
            patient_id=data["patient_id"],
            window_start=datetime.fromisoformat(str(data["window_start"])),
            window_end=datetime.fromisoformat(str(data["window_end"])),
            metric_type=MetricType(data["metric_type"]),
            metric_value=float(data["metric_value"]),
            metric_std=float(data.get("metric_std", 0.0)),
            unit=data["unit"],
            devices_involved=list(data.get("devices_involved", [])),
            reading_count=int(data.get("reading_count", 1)),
            quality_score=float(data.get("quality_score", 1.0)),
            quality_flags=[QualityFlag(f) for f in data.get("quality_flags", [])],
            is_anomaly=bool(data.get("is_anomaly", False)),
            anomaly_score=float(data.get("anomaly_score", 0.0)),
            activity_context=data.get("activity_context"),
            sleep_context=data.get("sleep_context"),
            processed_at=datetime.fromisoformat(str(processed)) if processed else None,
            device_types=[
                DeviceType(d) for d in data.get("device_types", [])
            ],
        )