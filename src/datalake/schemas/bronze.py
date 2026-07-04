from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.datalake.schemas.base import DeviceType, MetricType, QualityFlag, TelemetrySource


BRONZE_TELEMETRY_SCHEMA: Dict[str, str] = {
    "event_id": "string",
    "patient_id": "string",
    "device_id": "string",
    "device_type": "string",
    "vendor": "string",
    "metric_type": "string",
    "metric_value": "float",
    "unit": "string",
    "timestamp_utc": "timestamp",
    "ingested_at": "timestamp",
    "source": "string",
    "battery_level": "float",
    "signal_confidence": "float",
    "raw_payload": "json",
    "partition_date": "date",
}


@dataclass
class BronzeTelemetryRecord:
    """
    Camada Bronze — dados brutos como chegam dos relógios.
    Preserva payload original para auditoria e reprocessamento.
    """

    event_id: str
    patient_id: str
    device_id: str
    device_type: DeviceType
    vendor: str
    metric_type: MetricType
    metric_value: float
    unit: str
    timestamp_utc: datetime
    ingested_at: datetime
    source: TelemetrySource = TelemetrySource.DEVICE_STREAM
    battery_level: Optional[float] = None
    signal_confidence: float = 1.0
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    quality_flags: List[QualityFlag] = field(default_factory=list)

    @property
    def partition_date(self) -> str:
        return self.timestamp_utc.strftime("%Y-%m-%d")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["device_type"] = self.device_type.value
        data["metric_type"] = self.metric_type.value
        data["source"] = self.source.value
        data["quality_flags"] = [f.value for f in self.quality_flags]
        data["partition_date"] = self.partition_date
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BronzeTelemetryRecord":
        return cls(
            event_id=data["event_id"],
            patient_id=data["patient_id"],
            device_id=data["device_id"],
            device_type=DeviceType(data["device_type"]),
            vendor=data["vendor"],
            metric_type=MetricType(data["metric_type"]),
            metric_value=float(data["metric_value"]),
            unit=data["unit"],
            timestamp_utc=data["timestamp_utc"]
            if isinstance(data["timestamp_utc"], datetime)
            else datetime.fromisoformat(str(data["timestamp_utc"])),
            ingested_at=data["ingested_at"]
            if isinstance(data["ingested_at"], datetime)
            else datetime.fromisoformat(str(data["ingested_at"])),
            source=TelemetrySource(data.get("source", TelemetrySource.DEVICE_STREAM.value)),
            battery_level=data.get("battery_level"),
            signal_confidence=float(data.get("signal_confidence", 1.0)),
            raw_payload=data.get("raw_payload", {}),
            quality_flags=[
                QualityFlag(f) for f in data.get("quality_flags", [])
            ],
        )