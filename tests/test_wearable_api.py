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

