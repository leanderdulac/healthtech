"""
Adaptador Apple Health — export XML (HealthKit) ou JSON convertido.
"""

import json
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.datalake.schemas.base import DeviceType, MetricType, TelemetrySource
from src.ingestion.real.base import AdapterResult, TelemetryAdapter
from src.ingestion.real.normalizer import TelemetryNormalizer

logger = logging.getLogger(__name__)

APPLE_METRIC_MAP = {
    "HKQuantityTypeIdentifierHeartRate": MetricType.HEART_RATE,
    "HKQuantityTypeIdentifierOxygenSaturation": MetricType.SPO2,
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": MetricType.HRV,
    "HKQuantityTypeIdentifierStepCount": MetricType.STEPS,
    "HKQuantityTypeIdentifierRespiratoryRate": MetricType.RESPIRATORY_RATE,
    "HKQuantityTypeIdentifierBodyTemperature": MetricType.SKIN_TEMP,
}

SLEEP_TYPE_MAP = {
    "HKCategoryValueSleepAnalysisAsleep": 2,
    "HKCategoryValueSleepAnalysisInBed": 1,
    "HKCategoryValueSleepAnalysisAwake": 0,
}


class AppleHealthAdapter(TelemetryAdapter):
    """Parseia export.xml do Apple Health e normaliza para Bronze."""

    source_name = "apple_health"

    def __init__(
        self,
        export_path: Optional[str] = None,
        patient_id: Optional[str] = None,
        device_id: str = "apple-watch-primary",
    ):
        self.export_path = Path(
            export_path or os.getenv("APPLE_HEALTH_EXPORT_PATH", "data/ingestion/apple_health/export.xml")
        )
        self.patient_id = patient_id or os.getenv("APPLE_HEALTH_PATIENT_ID", "PAT-APPLE-001")
        self.device_id = device_id
        self.normalizer = TelemetryNormalizer(default_vendor="apple")

    def is_available(self) -> bool:
        return self.export_path.exists()

    def fetch_records(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> AdapterResult:
        pid = patient_id or self.patient_id
        if not self.is_available():
            return AdapterResult(
                source=self.source_name,
                errors=[f"Export não encontrado: {self.export_path}"],
            )

        suffix = self.export_path.suffix.lower()
        try:
            if suffix == ".json":
                records = self._parse_json(pid, start_time, end_time)
            else:
                records = self._parse_xml(pid, start_time, end_time)
        except Exception as e:
            logger.exception("Falha ao parsear Apple Health")
            return AdapterResult(source=self.source_name, errors=[str(e)])

        return AdapterResult(
            source=self.source_name,
            records=records,
            metadata={"export_path": str(self.export_path), "format": suffix},
        )

    def _parse_xml(
        self,
        patient_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> List:
        tree = ET.parse(self.export_path)
        root = tree.getroot()
        records = []

        for record in root.iter("Record"):
            rtype = record.get("type", "")
            metric = APPLE_METRIC_MAP.get(rtype)
            if metric is None:
                continue
            ts = self._parse_apple_datetime(record.get("startDate") or record.get("creationDate", ""))
            if not self._in_range(ts, start_time, end_time):
                continue
            value = float(record.get("value", 0))
            if metric == MetricType.SPO2 and value <= 1.0:
                value *= 100.0
            records.append(self.normalizer.from_raw_reading(
                patient_id=patient_id,
                device_id=record.get("device", self.device_id),
                metric_type=metric,
                value=value,
                timestamp=ts,
                vendor="apple",
                device_type=DeviceType.SMARTWATCH,
                source=TelemetrySource.MANUAL_UPLOAD,
                confidence=0.95,
                raw_payload={"type": rtype, "sourceName": record.get("sourceName")},
            ))

        for record in root.iter("Record"):
            if record.get("type") != "HKCategoryTypeIdentifierSleepAnalysis":
                continue
            ts = self._parse_apple_datetime(record.get("startDate", ""))
            if not self._in_range(ts, start_time, end_time):
                continue
            stage_val = SLEEP_TYPE_MAP.get(record.get("value", ""), 1)
            records.append(self.normalizer.from_raw_reading(
                patient_id=patient_id,
                device_id=self.device_id,
                metric_type=MetricType.SLEEP_STAGE,
                value=float(stage_val),
                timestamp=ts,
                vendor="apple",
                source=TelemetrySource.MANUAL_UPLOAD,
                raw_payload={"type": "sleep", "value": record.get("value")},
            ))

        logger.info("Apple Health XML: %d registros para %s", len(records), patient_id)
        return records

    def _parse_json(
        self,
        patient_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> List:
        with open(self.export_path, encoding="utf-8") as f:
            data = json.load(f)

        records = []
        for entry in data.get("records", data if isinstance(data, list) else []):
            rtype = entry.get("type", entry.get("metric_type", ""))
            metric = APPLE_METRIC_MAP.get(rtype) or self._metric_from_name(rtype)
            if metric is None:
                continue
            ts = entry.get("timestamp") or entry.get("startDate")
            if isinstance(ts, str):
                ts = self._parse_apple_datetime(ts)
            if not self._in_range(ts, start_time, end_time):
                continue
            value = float(entry.get("value", 0))
            records.append(self.normalizer.from_raw_reading(
                patient_id=patient_id,
                device_id=entry.get("device_id", self.device_id),
                metric_type=metric,
                value=value,
                timestamp=ts,
                vendor="apple",
                source=TelemetrySource.MANUAL_UPLOAD,
                raw_payload=entry,
            ))
        return records

    @staticmethod
    def _parse_apple_datetime(value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        cleaned = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    @staticmethod
    def _metric_from_name(name: str) -> Optional[MetricType]:
        mapping = {
            "heart_rate": MetricType.HEART_RATE,
            "spo2": MetricType.SPO2,
            "hrv": MetricType.HRV,
            "steps": MetricType.STEPS,
        }
        return mapping.get(name.lower())

    @staticmethod
    def _in_range(ts: datetime, start: Optional[datetime], end: Optional[datetime]) -> bool:
        if start and ts < start:
            return False
        if end and ts > end:
            return False
        return True