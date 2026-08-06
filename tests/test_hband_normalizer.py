"""Testes do contrato HBand e HBandNormalizer."""

from __future__ import annotations

from src.datalake.schemas.base import MetricType, TelemetrySource
from src.ingestion.real.hband_adapter import HBandCompanionAdapter, normalize_hband_payload
from src.ingestion.real.hband_normalizer import HBandNormalizer
from src.ingestion.real.hband_schemas import (
    HBandDeviceInfo,
    HBandOriginBatch,
    HBandOriginSample,
    HBandRealtimeIngest,
)


DEVICE = HBandDeviceInfo(
    device_id="HBAND-AA:BB:CC:DD:EE:FF",
    vendor="hband",
    model="HBand-Test",
    origin_protocol_version=3,
    watchday=7,
)


def test_realtime_to_ingest_body():
    n = HBandNormalizer()
    payload = HBandRealtimeIngest(
        patient_id="PAT-HBAND-001",
        device=DEVICE,
        heart_rate=78.0,
        spo2=97.0,
        skin_temp=33.4,
        hrv_rmssd=42.0,
        ppg_signal=[120.0, 125.0, 130.0, 128.0],
        filter_type="BMO",
        blood_pressure_sys=118.0,
        blood_pressure_dia=76.0,
        sdk_source="startDetectHeart",
    )
    body = n.to_wearable_ingest(payload)
    assert body["patient_id"] == "PAT-HBAND-001"
    assert body["device_id"] == "HBAND-AA:BB:CC:DD:EE:FF"
    assert body["heart_rate"] == 78.0
    assert body["spo2"] == 97.0
    assert body["ppg_signal"][0] == 120.0
    assert body["_hband"]["blood_pressure_sys"] == 118.0
    assert body["_hband"]["sdk_source"] == "startDetectHeart"


def test_realtime_to_bronze_metrics():
    n = HBandNormalizer()
    records = n.from_realtime(
        {
            "patient_id": "PAT-HBAND-001",
            "device": DEVICE.model_dump(),
            "heart_rate": 80.0,
            "spo2": 98.0,
            "blood_pressure_sys": 120.0,
            "blood_pressure_dia": 80.0,
            "timestamp": "2026-08-06T12:00:00Z",
        }
    )
    types = {r.metric_type for r in records}
    assert MetricType.HEART_RATE in types
    assert MetricType.SPO2 in types
    assert MetricType.BLOOD_PRESSURE_SYS in types
    assert MetricType.BLOOD_PRESSURE_DIA in types
    assert all(r.vendor == "hband" for r in records)
    assert all(r.source == TelemetrySource.DEVICE_STREAM for r in records)


def test_origin_batch_five_minute_mapping():
    n = HBandNormalizer()
    batch = HBandOriginBatch(
        patient_id="PAT-HBAND-001",
        device=DEVICE,
        day_offset=0,
        samples=[
            HBandOriginSample(
                timestamp="2026-08-06 08:00:00",
                package_number=1,
                rate_value=72,
                spo2_value=98,
                hrv=44,
                step_value=120,
                high_value=118,
                low_value=76,
                base_temperature=33.2,
                respiration_rate=16,
                sport_value=1000,
            )
        ],
    )
    records = n.from_origin_batch(batch)
    types = {r.metric_type for r in records}
    assert MetricType.HEART_RATE in types
    assert MetricType.STEPS in types
    assert MetricType.HRV in types
    assert MetricType.BLOOD_PRESSURE_SYS in types
    assert MetricType.RESPIRATORY_RATE in types
    assert MetricType.STRESS_INDEX in types
    assert all(r.source == TelemetrySource.BATCH_SYNC for r in records)


def test_sleep_batch_and_sport():
    n = HBandNormalizer()
    sleep_recs = n.from_sleep_batch(
        {
            "patient_id": "PAT-HBAND-001",
            "device": DEVICE.model_dump(),
            "records": [
                {
                    "date": "2026-08-05",
                    "sleep_quality": 8,
                    "all_sleep_time_min": 420,
                    "deep_sleep_time_min": 100,
                    "light_sleep_time_min": 280,
                    "sleep_line": "0011220011",
                    "precision_sleep": False,
                }
            ],
        }
    )
    assert any(r.metric_type == MetricType.SLEEP_STAGE for r in sleep_recs)

    sport = n.from_sport(
        {
            "patient_id": "PAT-HBAND-001",
            "device": DEVICE.model_dump(),
            "step": 8500,
            "distance_km": 6.2,
            "kcal": 320.5,
        }
    )
    stypes = {r.metric_type for r in sport}
    assert MetricType.STEPS in stypes
    assert MetricType.DISTANCE_KM in stypes
    assert MetricType.CALORIES in stypes


def test_ppg_stream_ingest_body():
    n = HBandNormalizer()
    body, recs = n.from_ppg_stream(
        {
            "patient_id": "PAT-HBAND-001",
            "device": DEVICE.model_dump(),
            "green_light": [100 + i for i in range(50)],
            "sample_rate_hz": 25.0,
            "mode": "realtime",
        }
    )
    assert "ppg_signal" in body
    assert len(body["ppg_signal"]) == 50
    assert body["filter_type"] == "BMO"


def test_envelope_router_origin():
    n = HBandNormalizer()
    records, body = n.normalize_envelope(
        {
            "message_type": "origin_batch",
            "schema_version": "1.0.0",
            "payload": {
                "patient_id": "PAT-HBAND-001",
                "device": DEVICE.model_dump(),
                "samples": [
                    {
                        "timestamp": "2026-08-06T09:00:00Z",
                        "rate_value": 70,
                        "spo2_value": 97,
                    }
                ],
            },
        }
    )
    assert len(records) >= 2
    assert body is None


def test_companion_adapter_injected_payloads():
    envelopes = [
        {
            "message_type": "realtime_ingest",
            "payload": {
                "patient_id": "PAT-HBAND-001",
                "device": DEVICE.model_dump(),
                "heart_rate": 77.0,
                "spo2": 96.0,
            },
        }
    ]
    result = HBandCompanionAdapter(payloads=envelopes).fetch_records()
    assert result.success or result.count > 0
    assert result.metadata["vendor"] == "hband"
    assert result.count >= 2


def test_normalize_hband_payload_helper():
    result = normalize_hband_payload(
        {
            "message_type": "sport_snapshot",
            "payload": {
                "patient_id": "PAT-HBAND-001",
                "device": DEVICE.model_dump(),
                "step": 1000,
                "kcal": 50,
            },
        }
    )
    assert result.count >= 1
    assert any(r.metric_type == MetricType.STEPS for r in result.records)


def test_registry_includes_hband():
    from src.ingestion.real.orchestrator import ADAPTER_REGISTRY

    assert "hband" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["hband"] is HBandCompanionAdapter
