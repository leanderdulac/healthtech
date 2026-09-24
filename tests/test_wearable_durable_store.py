"""Persistência durável — SQLite e PostgreSQL real (psycopg2, mesmo stack do Cloud SQL)."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

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
from app.services.ingest_idempotency import resolve_dedup_identity  # noqa: E402
from tests.support_wearable_db import (  # noqa: E402
    POSTGRES_URL,
    activate_engine,
    deactivate_engine,
    make_postgres_engine,
    make_sqlite_engine,
    postgres_available,
)

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
READ_KEY = "ht_read_test_key_32chars_long_token"
INGEST_HEADERS = {"X-API-Key": INGEST_KEY}
READ_HEADERS = {"X-API-Key": READ_KEY}

ISO_Z_MS = "2026-09-24T15:54:57.000Z"


def pytest_generate_tests(metafunc):
    if "backend" in metafunc.fixturenames:
        # Sempre os dois. SQLite sozinho foi o que deixou o smoke Cloud SQL passar.
        metafunc.parametrize("backend", ["sqlite", "postgres"])


@pytest.fixture
def durable_engine(backend, tmp_path):
    if backend == "sqlite":
        engine = make_sqlite_engine(tmp_path / "wearable_readings.db")
    else:
        if not postgres_available():
            pytest.fail(
                f"PostgreSQL real é obrigatório neste teste ({POSTGRES_URL}). "
                "Suba o cluster local (role/db wearable_test) ou defina "
                "WEARABLE_TEST_POSTGRES_URL."
            )
        engine = make_postgres_engine()
    previous = activate_engine(engine)
    yield engine
    deactivate_engine(engine, restore=previous)


@pytest.fixture
def durable_client(durable_engine):
    get_settings.cache_clear()
    from app.main import create_app

    application = create_app()
    with TestClient(application) as client:
        yield client
    get_settings.cache_clear()


def test_bind_sql_uses_cast_not_colon_cast():
    source = Path(durable_readings.__file__).read_text(encoding="utf-8")
    assert ":extra::jsonb" not in source
    assert ":frame::jsonb" not in source
    assert "CAST(:extra AS jsonb)" in source
    assert "CAST(:frame AS jsonb)" in source


def test_natural_identity_keeps_iso_colons_and_metric():
    ident = resolve_dedup_identity(
        patient_id="PAT-ISO",
        device_id="HBAND-AA:BB:CC:DD:EE:FF",
        client_reading_id=None,
        idempotency_key=None,
        client_timestamp=ISO_Z_MS,
        fields_set={"heart_rate", "timestamp"},
        metric_type=None,
    )
    assert ident.natural is not None
    assert ident.natural.metric_type == "heart_rate"
    assert ident.natural.measured_at.endswith("Z")
    assert "T15:54:57" in ident.natural.measured_at
    assert ident.natural.device_id == "HBAND-AA:BB:CC:DD:EE:FF"
    assert "54:57.000Z:heart_rate" not in ident.natural.metric_type


def test_apply_schema_is_idempotent(durable_engine, backend):
    durable_readings.apply_schema(durable_engine)
    durable_readings.apply_schema(durable_engine)
    with durable_engine.connect() as conn:
        if backend == "sqlite":
            names = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")
                )
            }
        else:
            names = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'wearable_readings'"
                    )
                )
            }
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE tablename = 'wearable_readings'")
                )
            }
            names |= tables
    assert "wearable_readings" in names
    assert "uq_wearable_readings_client_reading" in names
    assert "uq_wearable_readings_idempotency" in names
    assert "uq_wearable_readings_natural" in names


def test_upsert_duplicate_and_extra_payload(durable_engine):
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
        extra=extra,
        client_reading_id="room-dur-1",
        measured_at="2026-09-24T12:00:00Z",
        metric_type="heart_rate",
    )
    assert status == "accepted"
    second, status2 = durable_readings.upsert_reading(
        "PAT-DUR-1",
        {**frame, "raw_telemetry": {"heart_rate_bpm": 99.0}},
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


def test_natural_key_iso_timestamp_columns(durable_engine, backend):
    frame = {
        "patient_id": "PAT-DUR-NAT",
        "device_id": "HBAND-AA:BB:CC:DD:EE:FF",
        "timestamp": ISO_Z_MS,
        "received_at": "2026-09-24T15:54:58.000Z",
        "raw_telemetry": {"heart_rate_bpm": 70.0},
        "cleaned_telemetry": {"heart_rate_clean": 70.0},
    }
    ident = resolve_dedup_identity(
        patient_id="PAT-DUR-NAT",
        device_id="HBAND-AA:BB:CC:DD:EE:FF",
        client_reading_id=None,
        idempotency_key=None,
        client_timestamp=ISO_Z_MS,
        fields_set={"heart_rate", "timestamp"},
    )
    _, s1 = durable_readings.upsert_reading(
        "PAT-DUR-NAT",
        frame,
        identity=ident,
        measured_at=ISO_Z_MS,
        metric_type=ident.natural.metric_type if ident.natural else "heart_rate",
    )
    _, s2 = durable_readings.upsert_reading(
        "PAT-DUR-NAT",
        frame,
        identity=ident,
        measured_at="2026-09-24T15:54:57+00:00",
        metric_type="heart_rate",
    )
    assert s1 == "accepted"
    assert s2 == "duplicate"
    with durable_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT natural_metric_type, metric_type FROM wearable_readings "
                "WHERE patient_id = :pid"
            ),
            {"pid": "PAT-DUR-NAT"},
        ).fetchone()
    assert row[0] == "heart_rate"
    assert row[1] == "heart_rate"
    assert "54:57" not in str(row[0])


def test_concurrent_same_client_reading_id(durable_engine):
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
def test_http_single_accepted_then_client_id_duplicate(durable_client):
    payload = {
        "patient_id": "PAT-DUR-HTTP",
        "device_id": "HBAND-DUR",
        "heart_rate": 81.0,
        "spo2": 96.0,
        "timestamp": ISO_Z_MS,
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
    assert first.status_code == 200, first.text
    assert first.json()["ingest_status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["ingest_status"] == "duplicate"
    assert first.json().get("extra", {}).get("steps") == 4000
    assert first.json().get("extra", {}).get("calories") == 12.5


@pytest.mark.critical
def test_http_idempotency_key_and_natural_iso(durable_client):
    payload = {
        "patient_id": "PAT-DUR-ISO",
        "device_id": "HBAND-AA:BB:CC:DD:EE:FF",
        "heart_rate": 77.0,
        "timestamp": ISO_Z_MS,
    }
    headers = {**INGEST_HEADERS, "Idempotency-Key": "flush-stable-iso"}
    first = durable_client.post(
        "/api/v1/wearables/ingest", headers=headers, json=payload
    )
    second = durable_client.post(
        "/api/v1/wearables/ingest", headers=headers, json=payload
    )
    assert first.status_code == 200, first.text
    assert first.json()["ingest_status"] == "accepted"
    assert second.json()["ingest_status"] == "duplicate"

    natural_replay = durable_client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-DUR-ISO",
            "device_id": "HBAND-AA:BB:CC:DD:EE:FF",
            "heart_rate": 77.0,
            "timestamp": "2026-09-24T15:54:57+00:00",
        },
    )
    assert natural_replay.status_code == 200, natural_replay.text
    assert natural_replay.json()["ingest_status"] == "duplicate"


@pytest.mark.critical
def test_http_batch_mixed_accepted_duplicate_rejected(durable_client, monkeypatch):
    seed = {
        "patient_id": "PAT-DUR-BATCH",
        "heart_rate": 64.0,
        "timestamp": "2026-09-24T14:00:00.250Z",
        "client_reading_id": "room-batch-1",
    }
    seeded = durable_client.post(
        "/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=seed
    )
    assert seeded.status_code == 200

    from app.api import wearables as wearables_mod

    real = wearables_mod.process_ingest_frame

    def _maybe_fail(data):
        if float(data.get("heart_rate") or 0) == 20.0:
            raise RuntimeError("forced reject")
        return real(data)

    monkeypatch.setattr(wearables_mod, "process_ingest_frame", _maybe_fail)
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
                    "timestamp": "2026-09-24T14:05:00.000Z",
                    "client_reading_id": "room-batch-2",
                },
                {
                    "patient_id": "PAT-DUR-BATCH",
                    "heart_rate": 20.0,
                    "timestamp": "2026-09-24T14:10:00.000Z",
                    "client_reading_id": "room-batch-3",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["status"] for item in body["results"]] == [
        "duplicate",
        "accepted",
        "rejected",
    ]
    assert body["duplicate_count"] == 1
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 1
    assert body["status"] == "partial"


@pytest.mark.critical
def test_http_latest_history_and_restart(durable_client, durable_engine):
    payload = {
        "patient_id": "PAT-DUR-GET",
        "device_id": "HBAND-GET",
        "heart_rate": 88.0,
        "timestamp": ISO_Z_MS,
        "client_reading_id": "room-get-1",
        "steps": 90,
        "calories": 3.3,
    }
    ingested = durable_client.post(
        "/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload
    )
    assert ingested.status_code == 200, ingested.text
    history = durable_client.get(
        "/api/v1/wearables/patient/PAT-DUR-GET/history", headers=READ_HEADERS
    )
    assert history.status_code == 200
    assert history.json()["total_records"] == 1
    latest = durable_client.get(
        "/api/v1/wearables/patient/PAT-DUR-GET/latest", headers=READ_HEADERS
    )
    assert latest.status_code == 200
    assert latest.json()["client_reading_id"] == "room-get-1"
    assert latest.json().get("extra", {}).get("steps") == 90

    from app.main import create_app

    with TestClient(create_app()) as restarted:
        again = restarted.get(
            "/api/v1/wearables/patient/PAT-DUR-GET/history", headers=READ_HEADERS
        )
        assert again.status_code == 200
        assert again.json()["total_records"] == 1


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


def test_postgres_is_reachable():
    assert postgres_available(), (
        f"PostgreSQL real é obrigatório ({POSTGRES_URL}). "
        "O smoke Cloud SQL falhou por código que só rodou em SQLite."
    )


def test_configured_but_unreachable_db_returns_503(monkeypatch):
    from src.ops import operational_patients
    from tests.support_wearable_db import peek_engine, unset_engine

    saved = peek_engine()
    unset_engine(restore=None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://healthtech_app:x@127.0.0.1:1/none")
    get_settings.cache_clear()
    from app.main import create_app

    created = None
    try:
        with TestClient(create_app()) as client:
            ingest = client.post(
                "/api/v1/wearables/ingest",
                headers=INGEST_HEADERS,
                json={
                    "patient_id": "PAT-DUR-DOWN",
                    "heart_rate": 70.0,
                    "client_reading_id": "should-stay-queued",
                    "timestamp": ISO_Z_MS,
                },
            )
            assert ingest.status_code == 503
            assert "indisponível" in ingest.json()["detail"]
            created = peek_engine()
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        unset_engine(restore=saved)
        if created is not None and created is not saved:
            try:
                created.dispose()
            except Exception:
                pass
        get_settings.cache_clear()
        if saved is not None:
            operational_patients.set_engine(saved)
        telemetry_store.clear_all()


def test_anonymize_removes_durable_rows(durable_engine):
    durable_readings.upsert_reading(
        "PAT-DUR-LGPD",
        {
            "patient_id": "PAT-DUR-LGPD",
            "device_id": "DEV-L",
            "raw_telemetry": {"heart_rate_bpm": 71.0},
            "cleaned_telemetry": {"heart_rate_clean": 71.0},
        },
        client_reading_id="lgpd-1",
    )
    assert durable_readings.anonymize_patient("PAT-DUR-LGPD") is True
    assert durable_readings.get_latest("PAT-DUR-LGPD") is None
