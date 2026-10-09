"""O ingest guarda o que o app mediu. Default do schema não vira sinal."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))

from app.api.wearables import _with_timestamp  # noqa: E402
from app.models.schemas import WearableTelemetryRequest  # noqa: E402
from app.services.signal_core import process_ingest_frame  # noqa: E402
from src.ops.device_registry import clear_all, list_devices, upsert_frame  # noqa: E402


def test_schema_omits_are_not_measurements():
    payload = WearableTelemetryRequest.model_validate(
        {"patient_id": "PAT-OMIT-001", "heart_rate": 80}
    )
    assert payload.spo2 is None
    assert payload.hrv_rmssd is None
    assert payload.skin_temp is None
    assert payload.activity_level is None
    assert payload.wear_status is None
    data = _with_timestamp(payload)
    assert "spo2" not in data
    assert "hrv_rmssd" not in data
    assert "skin_temp" not in data
    assert "activity_level" not in data

    from src.api_server import WearableTelemetryRequest as ApiRequest

    api_request = ApiRequest(patient_id="PAT-OMIT-001", heart_rate=80)
    assert api_request.spo2 is None
    assert api_request.activity_level is None
    assert api_request.wear_status is None


def test_server_history_confirms_the_same_patient_within_fifteen_minutes():
    from app.services.telemetry_store import append_reading, clear_all

    clear_all()
    patient = "PAT-CONFIRM-015"
    first = process_ingest_frame(
        {
            "patient_id": patient,
            "heart_rate": 80,
            "spo2": 98,
            "sleep_hours": 5,
            "timestamp": "2026-10-09T15:00:00Z",
            "ingest_source": "ble_hband",
        }
    )
    assert first["clinical_alerts"]["is_true_alert"] is False
    append_reading(patient, first)

    second = process_ingest_frame(
        {
            "patient_id": patient,
            "heart_rate": 82,
            "spo2": 98.4,
            "sleep_hours": 5,
            "timestamp": "2026-10-09T15:10:00Z",
            "ingest_source": "ble_hband",
        }
    )
    alerts = second["clinical_alerts"]
    assert alerts["vitals_used"]["consecutive_valid"] == 2
    assert alerts["is_true_alert"] is True
    assert any(hit["rule_id"] == "n2u_111" for hit in alerts["rule_hits"])

    later = process_ingest_frame(
        {
            "patient_id": patient,
            "heart_rate": 82,
            "spo2": 98.2,
            "sleep_hours": 5,
            "timestamp": "2026-10-09T18:00:00Z",
            "ingest_source": "ble_hband",
        }
    )
    assert later["clinical_alerts"]["vitals_used"]["consecutive_valid"] == 1
    assert later["clinical_alerts"]["is_true_alert"] is False
    clear_all()


def test_omitted_vitals_are_not_filled_with_schema_defaults():
    payload = WearableTelemetryRequest.model_validate(
        {
            "patient_id": "PAT-HBAND-1975",
            "device_id": "40:35:E6:40:C5:D8",
            "heart_rate": 86,
            "steps": 1678,
            "calories": 0,
            "spo2": 97,
            "device_model": "Galaxy Watch8 (4WHN)",
            "blood_pressure": {"systolic": 118, "diastolic": 76},
            "is_real_sensor_data": True,
        }
    )
    data = _with_timestamp(payload)
    assert "hrv_rmssd" not in data
    assert "skin_temp" not in data
    assert data["spo2"] == 97
    assert data["steps"] == 1678
    assert data["blood_pressure"]["systolic"] == 118

    frame = process_ingest_frame(data)
    raw = frame["raw_telemetry"]
    assert raw["heart_rate_bpm"] == 86
    assert raw["spo2_percent"] == 97
    assert raw["steps"] == 1678
    assert raw["blood_pressure_sys"] == 118
    assert raw["blood_pressure_dia"] == 76
    assert raw["device_model"] == "Galaxy Watch8 (4WHN)"
    assert "hrv_rmssd_ms" not in raw
    assert "skin_temp_celsius" not in raw
    assert "calories" not in raw


def test_ppg_waveform_does_not_replace_heart_rate_or_invent_bp():
    frame = process_ingest_frame(
        {
            "patient_id": "PAT-HBAND-1975",
            "device_id": "VE30-E4:65:08:AA:BB:CC",
            "heart_rate": 76,
            "spo2": 98,
            "ppg_signal": [500.0, 520.0, 560.0, 610.0, 580.0, 530.0, 505.0, 495.0],
            "filter_type": "BMO",
        }
    )
    clean = frame["cleaned_telemetry"]
    assert clean["heart_rate_clean"] == 76
    assert clean["heart_rate_source"] == "measured"
    assert clean["ppg_role"] == "waveform"
    assert frame["phantom_data"]["systolic_bp"]["reliable"] is False
    assert frame["phantom_data"]["systolic_bp"]["method"] == "heuristic"
    alerts = frame["clinical_alerts"]
    assert alerts["is_true_alert"] is False
    assert alerts["vitals_used"]["hr"] == 76
    assert alerts["vitals_used"]["pas"] is None
    assert alerts["vitals_used"]["glucose_mgdl"] is None
    assert alerts["vitals_used"]["steps_drop_pct"] is None
    assert alerts["engine"] == "alert_matrix_rules"


def test_heart_rate_alone_does_not_invent_spo2():
    frame = process_ingest_frame(
        {
            "patient_id": "PAT-HBAND-1975",
            "device_id": "40:35:E6:40:C5:D8",
            "heart_rate": 72,
        }
    )
    raw = frame["raw_telemetry"]
    assert raw["heart_rate_bpm"] == 72
    assert "spo2_percent" not in raw
    assert "hrv_rmssd_ms" not in raw
    assert "skin_temp_celsius" not in raw


def test_fleet_row_keeps_steps_and_blood_pressure():
    clear_all()
    upsert_frame(
        {
            "patient_id": "PAT-HBAND-1975",
            "device_id": "40:35:E6:40:C5:D8",
            "timestamp": "2026-09-30T16:40:32+00:00",
            "received_at": "2026-09-30T16:40:32+00:00",
            "raw_telemetry": {
                "heart_rate_bpm": 111,
                "spo2_percent": 97,
                "steps": 1678,
                "blood_pressure_sys": 118,
                "blood_pressure_dia": 76,
                "device_model": "Galaxy Watch8 (4WHN)",
            },
            "cleaned_telemetry": {"heart_rate_clean": 111},
        }
    )
    row = next(
        item
        for item in list_devices(q="40:35:E6:40:C5:D8")["devices"]
        if item["device_id"] == "40:35:E6:40:C5:D8"
    )
    assert row["heart_rate"] == 111
    assert row["spo2"] == 97
    assert row["steps"] == 1678
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76
    assert row["device_model"] == "Galaxy Watch8 (4WHN)"
    clear_all()
