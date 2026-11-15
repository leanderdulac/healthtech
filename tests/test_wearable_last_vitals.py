"""Último SpO₂/passos/pressão válidos sobrevivem a um frame só com FC."""

from __future__ import annotations

from unittest.mock import patch

from app.services import durable_readings
from tests.test_wearable_durable_store import (  # noqa: F401
    INGEST_HEADERS,
    READ_HEADERS,
    durable_client,
    durable_engine,
    pytest_generate_tests,
)

DEVICE_ID = "E9:6B:B9:61:B0:40"
TS_SPO2 = "2026-11-14T23:20:00.000Z"
TS_HR = "2026-11-14T23:24:59.000Z"


def _ingest(client, **overrides):
    payload = {
        "patient_id": "PAT-SPO2-KEEP",
        "device_id": DEVICE_ID,
        "heart_rate": 72.0,
        "timestamp": TS_SPO2,
        "ingest_source": "ble_hband",
    }
    payload.update(overrides)
    return client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)


def _device(client, device_id):
    resp = client.get(
        "/api/v1/wearables/devices",
        headers=READ_HEADERS,
        params={"q": device_id, "include_synthetic": "true"},
    )
    assert resp.status_code == 200, resp.text
    rows = [row for row in resp.json()["devices"] if row["device_id"] == device_id]
    assert len(rows) == 1, resp.json()
    return rows[0]


def test_list_devices_keeps_spo2_after_hr_only_ingest(durable_client):
    first = _ingest(durable_client, spo2=97, steps=431, blood_pressure_sys=124, blood_pressure_dia=89)
    assert first.status_code == 200, first.text
    assert first.json()["ingest_status"] == "accepted"

    later = _ingest(
        durable_client,
        heart_rate=80.0,
        timestamp=TS_HR,
        client_reading_id="hr-only-later",
    )
    assert later.status_code == 200, later.text
    assert later.json()["ingest_status"] == "accepted"

    row = _device(durable_client, DEVICE_ID)
    assert row["heart_rate"] == 80
    assert row["spo2"] == 97
    assert row["steps"] == 431
    assert row["blood_pressure_sys"] == 124
    assert row["blood_pressure_dia"] == 89


def test_durable_list_devices_uses_latest_frames_not_list_frames(durable_client, durable_engine):
    _ingest(durable_client, spo2=98, heart_rate=70)

    def boom():
        raise AssertionError("list_frames não deve ser usado em GET /devices")

    with patch.object(durable_readings, "list_frames", side_effect=boom):
        row = _device(durable_client, DEVICE_ID)
    assert row["spo2"] == 98
    assert row["heart_rate"] == 70
