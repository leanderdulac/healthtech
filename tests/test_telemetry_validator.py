"""Testes do validador de telemetria Bronze."""

from __future__ import annotations

from datetime import datetime, timezone

from src.datalake.config import LakehouseConfig
from src.datalake.quality.validators import TelemetryValidator
from src.datalake.schemas.base import DeviceType, MetricType, QualityFlag
from src.datalake.schemas.bronze import BronzeTelemetryRecord


def _record(**kwargs) -> BronzeTelemetryRecord:
    now = datetime.now(timezone.utc)
    base = dict(
        event_id="evt-1",
        patient_id="PAT-001",
        device_id="DEV-001",
        device_type=DeviceType.SMARTWATCH,
        vendor="test",
        metric_type=MetricType.HEART_RATE,
        metric_value=72.0,
        unit="/min",
        timestamp_utc=now,
        ingested_at=now,
        signal_confidence=0.95,
        battery_level=0.8,
        raw_payload={},
    )
    base.update(kwargs)
    return BronzeTelemetryRecord(**base)


def test_valid_heart_rate():
    v = TelemetryValidator(LakehouseConfig())
    result = v.validate_bronze(_record())
    assert result.is_valid is True
    assert result.quality_score >= 0.8


def test_out_of_range_heart_rate():
    v = TelemetryValidator(LakehouseConfig())
    result = v.validate_bronze(_record(metric_value=300.0))
    assert QualityFlag.OUT_OF_RANGE in result.flags
    assert result.is_valid is False


def test_low_confidence_flag():
    v = TelemetryValidator(LakehouseConfig())
    result = v.validate_bronze(_record(signal_confidence=0.2))
    assert QualityFlag.LOW_CONFIDENCE in result.flags
