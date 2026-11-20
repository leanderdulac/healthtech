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



def test_apply_to_rows_loads_overrides_once(monkeypatch):
    from src.ops import device_patient_overrides as dpo

    dpo.clear_memory()
    dpo.upsert_override(
        device_id=DEVICE,
        patient_id=CANONICAL,
        created_by="test",
        motivo="lote",
    )
    calls = {"get": 0, "list": 0}
    real_get = dpo.get_override
    real_list = dpo.list_overrides

    def counting_get(*args, **kwargs):
        calls["get"] += 1
        return real_get(*args, **kwargs)

    def counting_list(*args, **kwargs):
        calls["list"] += 1
        return real_list(*args, **kwargs)

    monkeypatch.setattr(dpo, "get_override", counting_get)
    monkeypatch.setattr(dpo, "list_overrides", counting_list)

    rows = [
        {"device_id": f"10:20:30:40:50:{i:02X}", "patient_id": "PAT-TEST-XXXX"}
        for i in range(20)
    ]
    rows[0]["device_id"] = DEVICE
    rows[0]["patient_id"] = REPORTED
    out = dpo.apply_to_rows(rows)
    assert calls["list"] == 1
    assert calls["get"] == 0
    assert out[0]["patient_id"] == CANONICAL
    assert out[0]["reported_patient_id"] == REPORTED
    assert out[1]["patient_id"] == "PAT-TEST-XXXX"
    assert not out[1].get("reported_patient_id")
    dpo.clear_memory()


def test_compact_devices_from_frames_does_not_query_override_per_device(monkeypatch):
    from src.ops import device_patient_overrides as dpo
    from src.ops.live_devices import compact_devices_from_frames

    dpo.clear_memory()
    dpo.upsert_override(
        device_id=DEVICE,
        patient_id=CANONICAL,
        created_by="test",
        motivo="frota",
    )
    calls = {"get": 0, "list": 0}
    real_get = dpo.get_override
    real_list = dpo.list_overrides
    monkeypatch.setattr(dpo, "get_override", lambda *a, **k: calls.__setitem__("get", calls["get"] + 1) or real_get(*a, **k))
    monkeypatch.setattr(dpo, "list_overrides", lambda *a, **k: calls.__setitem__("list", calls["list"] + 1) or real_list(*a, **k))

    frames = []
    for i in range(12):
        frames.append(
            {
                "device_id": f"10:20:30:40:50:{i:02X}",
                "patient_id": "PAT-TEST-XXXX",
                "timestamp": "2026-11-20T12:00:00+00:00",
                "raw_telemetry": {"heart_rate_bpm": 70},
            }
        )
    frames[0]["device_id"] = DEVICE
    frames[0]["patient_id"] = REPORTED
    rows = compact_devices_from_frames(frames)
    assert calls["list"] == 1
    assert calls["get"] == 0
    match = next(row for row in rows if row["device_id"] == DEVICE)
    assert match["patient_id"] == CANONICAL
    assert match["reported_patient_id"] == REPORTED
    dpo.clear_memory()


def test_pool_int_clamps_and_defaults(monkeypatch):
    from src.ops.operational_patients import _pool_int

    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    assert _pool_int("DB_POOL_SIZE", 2, 1, 8) == 2
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    assert _pool_int("DB_POOL_SIZE", 2, 1, 8) == 5
    monkeypatch.setenv("DB_POOL_SIZE", "99")
    assert _pool_int("DB_POOL_SIZE", 2, 1, 8) == 8
    monkeypatch.setenv("DB_POOL_SIZE", "0")
    assert _pool_int("DB_POOL_SIZE", 2, 1, 8) == 1
    monkeypatch.setenv("DB_POOL_SIZE", "nope")
    assert _pool_int("DB_POOL_SIZE", 2, 1, 8) == 2
