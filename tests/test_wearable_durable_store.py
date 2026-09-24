"""Persistência durável de leituras (SQLite no CI; mesmo SQL que o Postgres)."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("AUTH_DISABLED", "false")
os.environ.setdefault("APP_MODE", "secure")
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32c")

from app.config import get_settings  # noqa: E402
from app.services import durable_readings, telemetry_store  # noqa: E402
from src.ops import operational_patients  # noqa: E402

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
READ_KEY = "ht_read_test_key_32chars_long_token"
INGEST_HEADERS = {"X-API-Key": INGEST_KEY}
READ_HEADERS = {"X-API-Key": READ_KEY}


def _reset_ops_engine() -> None:
    operational_patients.reset_engine()


@pytest.fixture
def sqlite_engine(tmp_path):
    path = tmp_path / "wearable_readings.db"
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    operational_patients.set_engine(engine)
    durable_readings.apply_schema(engine)
    telemetry_store.clear_all()
    yield engine
    telemetry_store.clear_all()
    _reset_ops_engine()
    engine.dispose()


@pytest.fixture
def durable_client(sqlite_engine):
    get_settings.cache_clear()
    from app.main import create_app

    application = create_app()
    with TestClient(application) as client:
        yield client
    get_settings.cache_clear()


def test_apply_schema_is_idempotent(sqlite_engine):
    durable_readings.apply_schema(sqlite_engine)
    durable_readings.apply_schema(sqlite_engine)
    with sqlite_engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")
            )
        }
    assert "wearable_readings" in names
    assert "uq_wearable_readings_client_reading" in names
    assert "uq_wearable_readings_idempotency" in names
    assert "uq_wearable_readings_natural" in names


def test_upsert_duplicate_and_extra_payload(sqlite_engine):
    frame = {
        "patient_id": "PAT-DUR-1",
        "device_id": "HBAND-1",
        "timestamp": "2026-09-24T12:00:00.000Z",
        "received_at": "2026-09-24T12:00:01.000Z",
        "raw_telemetry": {"heart_rate_bpm": 80.0, "spo2_percent": 97.0},
        "cleaned_telemetry": {"heart_rate_clean": 80.0},
    }
    extra = {"heart_rate": 80.0, "spo2": 97.0, "steps": 1234, "calories": 56.7}
    first, status = durable_readings.upsert_reading(
        "PAT-DUR-1",
        frame,
        dedup_keys=["cid:PAT-DUR-1:room-dur-1"],
        extra=extra,
        client_reading_id="room-dur-1",
        measured_at="2026-09-24T12:00:00Z",
        metric_type="heart_rate",
    )
    assert status == "accepted"
    second, status2 = durable_readings.upsert_reading(
        "PAT-DUR-1",
        {**frame, "raw_telemetry": {"heart_rate_bpm": 99.0}},
        dedup_keys=["cid:PAT-DUR-1:room-dur-1"],
        extra=extra,
        client_reading_id="room-dur-1",
        measured_at="2026-09-24T12:00:00Z",
        metric_type="heart_rate",
    )
    assert status2 == "duplicate"
    assert second["reading_id"] == first["reading_id"]
    hist = durable_readings.get_history("PAT-DUR-1", limit=10)
    assert len(hist) == 1
    assert hist[0]["extra"]["steps"] == 1234
    assert hist[0]["extra"]["calories"] == 56.7
    latest = durable_readings.get_latest("PAT-DUR-1")
    assert latest["raw_telemetry"]["heart_rate_bpm"] == 80.0


def test_natural_key_conflict(sqlite_engine):
    frame = {
        "patient_id": "PAT-DUR-NAT",
        "device_id": "DEV-9",
        "timestamp": "2026-09-24T08:00:00.000Z",
        "received_at": "2026-09-24T08:00:01.000Z",
        "raw_telemetry": {"heart_rate_bpm": 70.0},
        "cleaned_telemetry": {"heart_rate_clean": 70.0},
    }
    key = "nat:PAT-DUR-NAT:DEV-9:2026-09-24T08:00:00.000Z:heart_rate"
    _, s1 = durable_readings.upsert_reading(
        "PAT-DUR-NAT",
        frame,
        dedup_keys=[key],
        measured_at="2026-09-24T08:00:00Z",
        metric_type="heart_rate",
    )
    _, s2 = durable_readings.upsert_reading(
        "PAT-DUR-NAT",
        frame,
        dedup_keys=[key],
        measured_at="2026-09-24T08:00:00+00:00",
        metric_type="heart_rate",
    )
    assert s1 == "accepted"
    assert s2 == "duplicate"
    assert len(durable_readings.get_history("PAT-DUR-NAT")) == 1


def test_concurrent_same_client_reading_id(sqlite_engine):
    results: list[str] = []

    def _write(idx: int) -> None:
        frame = {
            "patient_id": "PAT-DUR-RACE",
            "device_id": "DEV-R",
            "timestamp": "2026-09-24T11:00:00.000Z",
            "received_at": "2026-09-24T11:00:01.000Z",
            "raw_telemetry": {"heart_rate_bpm": 60.0 + idx},
            "cleaned_telemetry": {"heart_rate_clean": 60.0 + idx},
        }
        _stored, status = durable_readings.upsert_reading(
            "PAT-DUR-RACE",
            frame,
            dedup_keys=["cid:PAT-DUR-RACE:room-race"],
            client_reading_id="room-race",
            measured_at="2026-09-24T11:00:00Z",
        )
        results.append(status)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("accepted") == 1
    assert results.count("duplicate") == 7
    assert len(durable_readings.get_history("PAT-DUR-RACE")) == 1


@pytest.mark.critical
def test_http_durable_resend_and_history_survives_new_app(durable_client, sqlite_engine):
    payload = {
        "patient_id": "PAT-DUR-HTTP",
        "device_id": "HBAND-DUR",
        "heart_rate": 81.0,
        "spo2": 96.0,
        "timestamp": "2026-09-24T13:00:00Z",
        "client_reading_id": "room-http-1",
        "steps": 4000,
        "calories": 12.5,
    }
    first = durable_client.post(
        "/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload
    )
    second = durable_client.post(
        "/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload
    )
    assert first.status_code == 200
    assert first.json()["ingest_status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["ingest_status"] == "duplicate"
    assert first.json().get("extra", {}).get("steps") == 4000

    history = durable_client.get(
        "/api/v1/wearables/patient/PAT-DUR-HTTP/history", headers=READ_HEADERS
    )
    assert history.status_code == 200
    assert history.json()["total_records"] == 1

    from app.main import create_app

    with TestClient(create_app()) as restarted:
        again = restarted.get(
            "/api/v1/wearables/patient/PAT-DUR-HTTP/history", headers=READ_HEADERS
        )
        assert again.status_code == 200
        assert again.json()["total_records"] == 1
        latest = restarted.get(
            "/api/v1/wearables/patient/PAT-DUR-HTTP/latest", headers=READ_HEADERS
        )
        assert latest.status_code == 200
        assert latest.json()["client_reading_id"] == "room-http-1"


@pytest.mark.critical
def test_http_durable_auth_unchanged(durable_client):
    payload = {"patient_id": "PAT-DUR-AUTH", "heart_rate": 70.0}
    assert (
        durable_client.post("/api/v1/wearables/ingest", json=payload).status_code == 401
    )
    denied = durable_client.post(
        "/api/v1/wearables/ingest", headers=READ_HEADERS, json=payload
    )
    assert denied.status_code == 403
    ok = durable_client.post(
        "/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload
    )
    assert ok.status_code == 200


@pytest.mark.critical
def test_http_durable_batch_partial_duplicates(durable_client):
    seed = {
        "patient_id": "PAT-DUR-BATCH",
        "heart_rate": 64.0,
        "timestamp": "2026-09-24T14:00:00Z",
        "client_reading_id": "room-batch-1",
    }
    durable_client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=seed)
    response = durable_client.post(
        "/api/v1/wearables/batch-ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-DUR-BATCH",
            "readings": [
                seed,
                {
                    "patient_id": "PAT-DUR-BATCH",
                    "heart_rate": 65.0,
                    "timestamp": "2026-09-24T14:05:00Z",
                    "client_reading_id": "room-batch-2",
                },
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["duplicate_count"] == 1
    assert body["accepted_count"] == 1


def test_configured_but_unreachable_db_returns_503(monkeypatch):
    _reset_ops_engine()
    monkeypatch.setenv("DATABASE_URL", "postgresql://healthtech_app:x@127.0.0.1:1/none")
    _reset_ops_engine()
    get_settings.cache_clear()
    from app.main import create_app

    try:
        with TestClient(create_app()) as client:
            ingest = client.post(
                "/api/v1/wearables/ingest",
                headers=INGEST_HEADERS,
                json={
                    "patient_id": "PAT-DUR-DOWN",
                    "heart_rate": 70.0,
                    "client_reading_id": "should-stay-queued",
                },
            )
            assert ingest.status_code == 503
            assert "indisponível" in ingest.json()["detail"]
            hist = client.get(
                "/api/v1/wearables/patient/PAT-DUR-DOWN/history",
                headers=READ_HEADERS,
            )
            assert hist.status_code == 503
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        _reset_ops_engine()
        get_settings.cache_clear()
        telemetry_store.clear_all()


def test_anonymize_removes_durable_rows(sqlite_engine):
    durable_readings.upsert_reading(
        "PAT-DUR-LGPD",
        {
            "patient_id": "PAT-DUR-LGPD",
            "device_id": "DEV-L",
            "raw_telemetry": {"heart_rate_bpm": 71.0},
            "cleaned_telemetry": {"heart_rate_clean": 71.0},
        },
        dedup_keys=["cid:PAT-DUR-LGPD:lgpd-1"],
        client_reading_id="lgpd-1",
    )
    assert durable_readings.anonymize_patient("PAT-DUR-LGPD") is True
    assert durable_readings.get_latest("PAT-DUR-LGPD") is None
