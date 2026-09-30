"""Public storage failures must not disclose driver SQL, values or credentials."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import durable_readings, telemetry_store


PRIVATE_MARKER = "synthetic-private-db-detail-DO-NOT-EXPOSE"


def unavailable(*args, **kwargs):
    raise durable_readings.DurableStoreUnavailable(PRIVATE_MARKER)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_MODE", "secure")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("SECRET_SALT", "test-salt-not-for-production-use-32c")
    get_settings.cache_clear()
    # No startup DB/network access: failures below are injected at store boundaries.
    monkeypatch.setattr(telemetry_store, "log_store_backend", lambda: "durable")
    with TestClient(create_app()) as instance:
        yield instance
    get_settings.cache_clear()


@pytest.mark.parametrize("path,store_method", [
    ("/api/v1/wearables/patient/PAT-PRIVACY/latest", "get_latest"),
    ("/api/v1/wearables/patient/PAT-PRIVACY/history", "get_history"),
    ("/api/v1/wearables/devices", "list_devices"),
    ("/api/v1/connections/status", "iter_patients"),
    ("/api/v1/connections/public", "iter_patients"),
])
def test_read_outage_is_sanitized(client, monkeypatch, caplog, path, store_method):
    monkeypatch.setattr(telemetry_store, store_method, unavailable)
    headers = {"X-API-Key": "ht_read_test_key_32chars_long_token"}
    if "/connections/" in path:
        headers = {}  # Both public routes must be safe without authentication.
    response = client.get(path, headers=headers)
    assert response.status_code == 503
    assert "indisponível" in response.json()["detail"]
    assert response.json()["error_code"] == "HTTP_503"
    assert response.json()["request_id"]
    assert PRIVATE_MARKER not in response.text
    assert PRIVATE_MARKER not in caplog.text


@pytest.mark.parametrize("path", [
    "/api/v1/wearables/ingest",
    "/api/v1/wearables/batch-ingest",
    "/api/v1/wearables/ingest/batch",
])
def test_ingest_outage_is_sanitized(client, monkeypatch, caplog, path):
    monkeypatch.setattr(telemetry_store, "find_duplicate", unavailable)
    reading = {"patient_id": "PAT-PRIVACY", "heart_rate": 70,
               "client_reading_id": "privacy-reading-1"}
    payload = reading if path.endswith("/ingest") else {
        "patient_id": "PAT-PRIVACY", "readings": [reading],
    }
    response = client.post(path, json=payload, headers={
        "X-API-Key": "ht_ingest_test_key_32chars_long_token",
    })
    assert response.status_code == 503
    assert "manter a leitura na fila" in response.json()["detail"]
    assert response.json()["error_code"] == "HTTP_503"
    assert PRIVATE_MARKER not in response.text
    assert PRIVATE_MARKER not in caplog.text


def test_startup_outage_does_not_log_exception_or_connection(monkeypatch, caplog):
    monkeypatch.setattr(durable_readings, "is_configured", lambda: True)
    monkeypatch.setattr(durable_readings, "database_url", lambda:
                        "postgresql://user:password@host/db?private=" + PRIVATE_MARKER)
    monkeypatch.setattr(durable_readings, "apply_schema", unavailable)
    with caplog.at_level(logging.INFO):
        assert durable_readings.log_backend() == "durable-unavailable"
    assert "no in-memory fallback" in caplog.text
    assert PRIVATE_MARKER not in caplog.text
    assert "password" not in caplog.text


def test_healthy_startup_does_not_log_connection_options(monkeypatch, caplog):
    monkeypatch.setattr(durable_readings, "is_configured", lambda: True)
    monkeypatch.setattr(durable_readings, "database_url", lambda:
                        "postgresql://user:password@host/db?private=" + PRIVATE_MARKER)
    monkeypatch.setattr(durable_readings, "apply_schema", lambda: "postgresql")
    monkeypatch.setattr(durable_readings, "ping", lambda: None)
    with caplog.at_level(logging.INFO):
        assert durable_readings.log_backend() == "durable"
    assert "Wearable telemetry store: durable" in caplog.text
    assert PRIVATE_MARKER not in caplog.text
    assert "password" not in caplog.text
