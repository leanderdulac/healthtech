"""
Normalizador unificado: payloads heterogêneos → BronzeTelemetryRecord.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.datalake.schemas.base import DeviceType, MetricType, TelemetrySource
from src.datalake.schemas.bronze import BronzeTelemetryRecord

logger = logging.getLogger(__name__)

METRIC_UNITS = {
    MetricType.HEART_RATE: "bpm",
    MetricType.SPO2: "%",
    MetricType.HRV: "ms",
    MetricType.STEPS: "count",
    MetricType.SLEEP_STAGE: "stage",
    MetricType.STRESS_INDEX: "index",
    MetricType.SKIN_TEMP: "celsius",
    MetricType.RESPIRATORY_RATE: "breaths/min",
}


class TelemetryNormalizer:
    """Converte leituras de qualquer adaptador para o schema Bronze."""

    def __init__(self, default_vendor: str = "unknown"):
        self.default_vendor = default_vendor

    def from_raw_reading(
        self,
        patient_id: str,
        device_id: str,
        metric_type: MetricType,
        value: float,
        timestamp: datetime,
        vendor: Optional[str] = None,
        device_type: DeviceType = DeviceType.SMARTWATCH,
        source: TelemetrySource = TelemetrySource.DEVICE_STREAM,
        unit: Optional[str] = None,
        confidence: float = 1.0,
        battery_level: Optional[float] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> BronzeTelemetryRecord:
        ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        event_key = f"{patient_id}:{device_id}:{metric_type.value}:{ts.isoformat()}:{value}"
        event_id = hashlib.sha256(event_key.encode()).hexdigest()[:16]

        return BronzeTelemetryRecord(
            event_id=event_id,
            patient_id=patient_id,
            device_id=device_id,
            device_type=device_type,
            vendor=vendor or self.default_vendor,
            metric_type=metric_type,
            metric_value=float(value),
            unit=unit or METRIC_UNITS.get(metric_type, "unit"),
            timestamp_utc=ts,
            ingested_at=datetime.now(timezone.utc),
            source=source,
            battery_level=battery_level,
            signal_confidence=confidence,
            raw_payload=raw_payload or {},
        )

    def batch_from_dicts(
        self,
        readings: List[Dict[str, Any]],
        patient_id: str,
        device_id: str,
        vendor: str,
        source: TelemetrySource = TelemetrySource.BATCH_SYNC,
    ) -> List[BronzeTelemetryRecord]:
        records = []
        for row in readings:
            try:
                metric = MetricType(row["metric_type"])
                ts = row["timestamp"]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                records.append(self.from_raw_reading(
                    patient_id=patient_id,
                    device_id=device_id,
                    metric_type=metric,
                    value=float(row["value"]),
                    timestamp=ts,
                    vendor=vendor,
                    device_type=DeviceType(row.get("device_type", DeviceType.SMARTWATCH.value)),
                    source=source,
                    unit=row.get("unit"),
                    confidence=float(row.get("confidence", 1.0)),
                    raw_payload=row.get("raw_payload", row),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Leitura ignorada: %s — %s", row, e)
        return records