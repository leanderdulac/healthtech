"""Vínculo canônico device→paciente: ingestão, frota/detalhe e API admin."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["APP_MODE"] = "secure"
os.environ["AUTH_DISABLED"] = "false"
os.environ["ENVIRONMENT"] = "development"
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32b")

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import create_app  # noqa: E402
from app.services import telemetry_store  # noqa: E402
from src.ops.device_patient_overrides import clear_memory  # noqa: E402
from src.ops.device_detail import build_device_detail  # noqa: E402

ADMIN_HEADERS = {"X-API-Key": "ht_admin_test_key_32chars_long_token"}
INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
READ_HEADERS = {"X-API-Key": "ht_read_test_key_32chars_long_token"}

DEVICE = "AA:BB:CC:11:22:33"
REPORTED = "PAT-TEST-ALEX1"
CANONICAL = "PAT-TEST-FRED1"


def _payload(patient_id: str, device_id: str = DEVICE, **extra):
    body = {
        "patient_id": patient_id,
        "device_id": device_id,
        "heart_rate": 76.0,
        "spo2": 98.0,
        "ingest_source": "companion_manual",
    }
    body.update(extra)
    return body


@pytest.fixture
def client():
    telemetry_store.clear_all()
    clear_memory()
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    telemetry_store.clear_all()
    clear_memory()


def test_ingest_without_override_keeps_reported_patient_id(client: TestClient):
    response = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json=_payload(REPORTED),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["patient_id"] == REPORTED
    assert not data.get("reported_patient_id")

    latest = client.get(
        f"/api/v1/wearables/patient/{REPORTED}/latest",
        headers=READ_HEADERS,
    )
    assert latest.status_code == 200
    assert latest.json()["patient_id"] == REPORTED


def test_override_applied_on_ingest_and_device_detail(client: TestClient):
    created = client.put(
        "/api/v1/admin/device-patient-overrides",
        headers=ADMIN_HEADERS,
        json={
            "device_id": DEVICE.lower(),
            "patient_id": CANONICAL,
            "motivo": "teste de vínculo canônico",
        },
    )
    assert created.status_code == 200, created.text
    override = created.json()["override"]
    assert override["device_id"] == DEVICE
    assert override["patient_id"] == CANONICAL
    assert override["motivo"] == "teste de vínculo canônico"
    assert "***" in (override.get("created_by") or "")

    response = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json=_payload(REPORTED),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["patient_id"] == CANONICAL
    assert data["reported_patient_id"] == REPORTED

    # Histórico fica no paciente canônico, não no enviado pelo app.
    missing = client.get(
        f"/api/v1/wearables/patient/{REPORTED}/latest",
        headers=READ_HEADERS,
    )
    assert missing.status_code == 404
    latest = client.get(
        f"/api/v1/wearables/patient/{CANONICAL}/latest",
        headers=READ_HEADERS,
    )
    assert latest.status_code == 200
    assert latest.json()["patient_id"] == CANONICAL
    assert latest.json()["reported_patient_id"] == REPORTED

    fleet = telemetry_store.list_devices()
    devices = fleet.get("devices") or []
    match = next((row for row in devices if row.get("device_id") == DEVICE), None)
    assert match is not None
    assert match["patient_id"] == CANONICAL

    detail = build_device_detail(match)
    assert detail["patient_id"] == CANONICAL
    assert detail.get("reported_patient_id") == REPORTED

    via_api = client.get(
        f"/api/v1/ops/devices/{DEVICE}",
        headers=READ_HEADERS,
    )
    assert via_api.status_code == 200, via_api.text
    body = via_api.json()
    assert body["patient_id"] == CANONICAL
    assert body.get("reported_patient_id") == REPORTED


def test_non_admin_keys_cannot_create_override(client: TestClient):
    body = {"device_id": DEVICE, "patient_id": CANONICAL, "motivo": "não deve gravar"}
    denied_ingest = client.post(
        "/api/v1/admin/device-patient-overrides",
        headers=INGEST_HEADERS,
        json=body,
    )
    denied_read = client.post(
        "/api/v1/admin/device-patient-overrides",
        headers=READ_HEADERS,
        json=body,
    )
    denied_anon = client.post(
        "/api/v1/admin/device-patient-overrides",
        json=body,
    )
    assert denied_ingest.status_code == 403
    assert denied_read.status_code == 403
    assert denied_anon.status_code == 401

    listed = client.get(
        "/api/v1/admin/device-patient-overrides",
        headers=ADMIN_HEADERS,
    )
    assert listed.status_code == 200
    assert listed.json()["overrides"] == []


def test_upsert_override_is_idempotent(client: TestClient):
    first = client.put(
        "/api/v1/admin/device-patient-overrides",
        headers=ADMIN_HEADERS,
        json={"device_id": DEVICE, "patient_id": CANONICAL, "motivo": "um"},
    )
    second = client.put(
        "/api/v1/admin/device-patient-overrides",
        headers=ADMIN_HEADERS,
        json={"device_id": DEVICE, "patient_id": CANONICAL, "motivo": "dois"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    listed = client.get(
        "/api/v1/admin/device-patient-overrides",
        headers=ADMIN_HEADERS,
    )
    rows = listed.json()["overrides"]
    assert len(rows) == 1
    assert rows[0]["motivo"] == "dois"


def test_apply_schema_004_is_idempotent(tmp_path):
    from tests.support_wearable_db import activate_engine, deactivate_engine, make_sqlite_engine
    from app.services.durable_readings import apply_schema

    engine = make_sqlite_engine(tmp_path / "overrides.sqlite")
    previous = activate_engine(engine)
    try:
        first = apply_schema(engine)
        second = apply_schema(engine)
        assert first == "sqlite"
        assert second == "sqlite"
        with engine.connect() as conn:
            from sqlalchemy import text

            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            assert "device_patient_overrides" in tables
            cols = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(wearable_readings)"))
            }
            assert "reported_patient_id" in cols
    finally:
        deactivate_engine(engine, restore=previous)
