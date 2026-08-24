"""
test_wearable_api.py — Testes dos endpoints de ingestão e monitoramento de wearables
"""

import pytest
from fastapi.testclient import TestClient
from src.api_server import app

client = TestClient(app)

INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
READ_HEADERS = {"X-API-Key": "ht_read_test_key_32chars_long_token"}


def test_wearable_ingest_endpoint():
    payload = {
        "patient_id": "TEST_PATIENT_101",
        "device_id": "pixel_watch_pro",
        "heart_rate": 78.5,
        "hrv_rmssd": 42.0,
        "skin_temp": 33.2,
        "spo2": 98.0,
        "activity_level": 0.2,
        "filter_type": "BMO"
    }
    response = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "TEST_PATIENT_101"
    assert data["device_id"] == "pixel_watch_pro"
    assert "phantom_data" in data
    assert "systolic_bp" in data["phantom_data"]
    assert "diastolic_bp" in data["phantom_data"]
    assert "anomaly_detection" in data
    assert "diagnostic_hypotheses" in data
    assert "clinical_codes" in data


def test_wearable_get_latest_and_history():
    # Ingerir duas leituras
    client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json={
        "patient_id": "TEST_PATIENT_102",
        "heart_rate": 72.0,
        "hrv_rmssd": 45.0
    })
    client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json={
        "patient_id": "TEST_PATIENT_102",
        "heart_rate": 115.0,
        "hrv_rmssd": 18.0
    })

    # Buscar última leitura
    resp_latest = client.get("/api/v1/wearables/patient/TEST_PATIENT_102/latest", headers=READ_HEADERS)
    assert resp_latest.status_code == 200
    latest_data = resp_latest.json()
    assert latest_data["raw_telemetry"]["heart_rate_bpm"] == 115.0

    # Buscar histórico
    resp_hist = client.get("/api/v1/wearables/patient/TEST_PATIENT_102/history?limit=10", headers=READ_HEADERS)
    assert resp_hist.status_code == 200
    hist_data = resp_hist.json()
    assert hist_data["patient_id"] == "TEST_PATIENT_102"
    assert len(hist_data["records"]) == 2


def test_live_devices_summary_marks_recent_watch_online():
    from datetime import datetime, timezone

    from src.ops.live_devices import devices_from_patient_history

    now = datetime(2026, 8, 24, 19, 40, tzinfo=timezone.utc)
    history = {
        "PAT-VE30-001": [
            {
                "patient_id": "PAT-VE30-001",
                "device_id": "VE30-E4:65:08:AA:BB:CC",
                "timestamp": "2026-08-24T19:39:50+00:00",
                "raw_telemetry": {"heart_rate_bpm": 72.0, "spo2_percent": 98.0},
                "cleaned_telemetry": {"heart_rate_clean": 71.4},
            }
        ]
    }
    rows = devices_from_patient_history(history, now=now)
    assert len(rows) == 1
    assert rows[0]["online"] is True
    assert rows[0]["heart_rate"] == 71.4


def test_wearable_devices_lists_ingested_watch():
    payload = {
        "patient_id": "TEST_PATIENT_VE30",
        "device_id": "VE30-AA:BB:CC:DD:EE:FF",
        "heart_rate": 74.0,
        "hrv_rmssd": 38.0,
        "spo2": 97.0,
    }
    ingested = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert ingested.status_code == 200
    listed = client.get("/api/v1/wearables/devices", headers=READ_HEADERS)
    assert listed.status_code == 200
    devices = listed.json()["devices"]
    match = next(d for d in devices if d["device_id"] == "VE30-AA:BB:CC:DD:EE:FF")
    assert match["patient_id"] == "TEST_PATIENT_VE30"
    assert match["heart_rate"] == 74.0
    assert match["latest"]["raw_telemetry"]["spo2_percent"] == 97.0
    denied = client.get("/api/v1/wearables/devices", headers=INGEST_HEADERS)
    assert denied.status_code == 403


def test_wearable_batch_ingest():
    batch_payload = {
        "patient_id": "TEST_PATIENT_BATCH",
        "readings": [
            {"patient_id": "TEST_PATIENT_BATCH", "heart_rate": 70.0, "hrv_rmssd": 50.0},
            {"patient_id": "TEST_PATIENT_BATCH", "heart_rate": 75.0, "hrv_rmssd": 48.0},
            {"patient_id": "TEST_PATIENT_BATCH", "heart_rate": 80.0, "hrv_rmssd": 40.0}
        ]
    }
    response = client.post("/api/v1/wearables/batch-ingest", headers=INGEST_HEADERS, json=batch_payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "success"
    assert res["processed_count"] == 3
    assert res["latest_result"]["raw_telemetry"]["heart_rate_bpm"] == 80.0


def test_wearable_batch_ingest_legacy_path():
    """O companion Android ainda chama /ingest/batch; o alias precisa responder igual."""
    batch_payload = {
        "patient_id": "TEST_PATIENT_BATCH_LEGACY",
        "readings": [
            {"patient_id": "TEST_PATIENT_BATCH_LEGACY", "heart_rate": 70.0, "hrv_rmssd": 50.0},
        ],
    }
    response = client.post("/api/v1/wearables/ingest/batch", headers=INGEST_HEADERS, json=batch_payload)
    assert response.status_code == 200
    assert response.json()["processed_count"] == 1

