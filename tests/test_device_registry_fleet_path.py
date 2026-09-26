"""Persistência local da frota: path configurável, falha não quebra ingest/GCS."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

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
from app.services import telemetry_store  # noqa: E402
from src.ops import device_registry as dr  # noqa: E402

INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
FLEET_LOGGER = "src.ops.device_registry"
REGISTER_WARNING = "Falha ao registrar relógio na frota"
LOCAL_WARNING = "Falha ao gravar frota local"
LOCAL_SUCCESS = "Frota gravada localmente"
GCS_SUCCESS = "Frota gravada no GCS"
SECURE_REQUIREMENTS = SECURE / "requirements.txt"


def _enable_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    """_flush_unlocked short-circuits while pytest sets PYTEST_CURRENT_TEST."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(dr, "FLUSH_EVERY_SECONDS", 0.0)


def _install_fake_storage(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Return the mocked blob; upload_from_string is asserted by callers."""
    blob = MagicMock()
    blob.exists.return_value = False
    client = MagicMock()
    client.bucket.return_value.blob.return_value = blob
    fake_client_cls = MagicMock(return_value=client)
    try:
        from google.cloud import storage as real_storage

        monkeypatch.setattr(real_storage, "Client", fake_client_cls)
    except ImportError:
        storage_mod = types.ModuleType("google.cloud.storage")
        storage_mod.Client = fake_client_cls
        cloud_mod = types.ModuleType("google.cloud")
        cloud_mod.storage = storage_mod
        google_mod = types.ModuleType("google")
        google_mod.cloud = cloud_mod
        monkeypatch.setitem(sys.modules, "google", google_mod)
        monkeypatch.setitem(sys.modules, "google.cloud", cloud_mod)
        monkeypatch.setitem(sys.modules, "google.cloud.storage", storage_mod)
    return blob


def _frame(device_id: str, patient_id: str = "PAT-FLEET-001") -> dict:
    return {
        "patient_id": patient_id,
        "device_id": device_id,
        "timestamp": "2026-09-26T13:00:00+00:00",
        "received_at": "2026-09-26T13:00:01+00:00",
        "raw_telemetry": {"heart_rate_bpm": 72.0, "spo2_percent": 98.0},
        "cleaned_telemetry": {"heart_rate_clean": 72.0},
    }


@pytest.fixture(autouse=True)
def _reset_fleet():
    dr.clear_all()
    telemetry_store.clear_all()
    yield
    dr.clear_all()
    telemetry_store.clear_all()


def _secure_client() -> TestClient:
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


def test_local_fleet_path_env_and_cloud_run_defaults(monkeypatch, tmp_path):
    custom = tmp_path / "custom" / "fleet.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(custom))
    assert dr.local_fleet_path() == custom

    monkeypatch.delenv("FLEET_DEVICES_PATH", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("K_REVISION", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert dr.local_fleet_path() == dr.DEFAULT_LOCAL_FLEET_PATH

    monkeypatch.setenv("K_SERVICE", "healthtech-secure-api")
    assert dr.local_fleet_path() == Path(tempfile.gettempdir()) / "ops" / "fleet_devices.json"

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert dr.local_fleet_path() == Path(tempfile.gettempdir()) / "ops" / "fleet_devices.json"


def test_non_writable_path_ingest_accepted_warning_throttled(
    monkeypatch, tmp_path, caplog
):
    blocked = tmp_path / "blocked"
    blocked.write_text("not-a-directory\n", encoding="utf-8")
    target = blocked / "ops" / "fleet_devices.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(target))
    monkeypatch.delenv("GCS_STAGING_BUCKET", raising=False)
    _enable_flush(monkeypatch)

    client = _secure_client()
    with caplog.at_level(logging.WARNING):
        first = client.post(
            "/api/v1/wearables/ingest",
            headers=INGEST_HEADERS,
            json={
                "patient_id": "PAT-FLEET-NW-001",
                "device_id": "VE30-FLEET-NW",
                "heart_rate": 74.0,
                "client_reading_id": "fleet-nw-1",
            },
        )
        second = client.post(
            "/api/v1/wearables/ingest",
            headers=INGEST_HEADERS,
            json={
                "patient_id": "PAT-FLEET-NW-001",
                "device_id": "VE30-FLEET-NW",
                "heart_rate": 76.0,
                "client_reading_id": "fleet-nw-2",
            },
        )

    assert first.status_code == 200, first.text
    assert first.json().get("ingest_status") == "accepted"
    assert second.status_code == 200, second.text
    assert second.json().get("ingest_status") == "accepted"

    messages = [rec.getMessage() for rec in caplog.records]
    assert not any(REGISTER_WARNING in msg for msg in messages)
    local_warnings = [msg for msg in messages if LOCAL_WARNING in msg]
    assert len(local_warnings) == 1
    assert not target.exists()


def test_configured_writable_path_writes_file(monkeypatch, tmp_path):
    path = tmp_path / "ops" / "fleet_devices.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(path))
    monkeypatch.delenv("GCS_STAGING_BUCKET", raising=False)
    _enable_flush(monkeypatch)

    dr.upsert_frame(_frame("VE30-FLEET-OK"))

    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["devices"][0]["device_id"] == "VE30-FLEET-OK"


def test_gcs_upload_attempted_after_local_failure(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not-a-directory\n", encoding="utf-8")
    target = blocked / "ops" / "fleet_devices.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(target))
    monkeypatch.setenv("GCS_STAGING_BUCKET", "gs://fleet-test-bucket")
    _enable_flush(monkeypatch)

    blob = _install_fake_storage(monkeypatch)

    dr.upsert_frame(_frame("VE30-FLEET-GCS"))

    blob.upload_from_string.assert_called_once()
    uploaded, kwargs = blob.upload_from_string.call_args
    assert kwargs.get("content_type") == "application/json"
    snapshot = json.loads(uploaded[0])
    assert snapshot["count"] == 1
    assert snapshot["devices"][0]["device_id"] == "VE30-FLEET-GCS"
    assert not target.exists()


def test_successful_local_write_logs_info_once(monkeypatch, tmp_path, caplog):
    path = tmp_path / "ops" / "fleet_devices.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(path))
    monkeypatch.delenv("GCS_STAGING_BUCKET", raising=False)
    _enable_flush(monkeypatch)

    with caplog.at_level(logging.INFO, logger=FLEET_LOGGER):
        dr.upsert_frame(_frame("VE30-FLEET-LOG-1"))
        dr.upsert_frame(_frame("VE30-FLEET-LOG-2"))

    hits = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == FLEET_LOGGER and LOCAL_SUCCESS in rec.getMessage()
    ]
    assert len(hits) == 1
    assert str(path) in hits[0]
    assert "1 devices" in hits[0]
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["count"] == 2


def test_successful_gcs_upload_logs_info_once(monkeypatch, tmp_path, caplog):
    path = tmp_path / "ops" / "fleet_devices.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(path))
    monkeypatch.setenv("GCS_STAGING_BUCKET", "gs://healthtech-gcp-2026-vertex-staging")
    _enable_flush(monkeypatch)
    blob = _install_fake_storage(monkeypatch)

    with caplog.at_level(logging.INFO, logger=FLEET_LOGGER):
        dr.upsert_frame(_frame("VE30-FLEET-GCS-LOG-1"))
        dr.upsert_frame(_frame("VE30-FLEET-GCS-LOG-2"))

    assert blob.upload_from_string.call_count == 2
    hits = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == FLEET_LOGGER and GCS_SUCCESS in rec.getMessage()
    ]
    assert len(hits) == 1
    assert "gs://healthtech-gcp-2026-vertex-staging/ops/fleet/devices.json" in hits[0]
    assert "1 devices" in hits[0]
    lowered = hits[0].lower()
    assert "credential" not in lowered
    assert "token" not in lowered
    assert "key" not in lowered


def test_secure_requirements_pins_google_cloud_storage():
    text = SECURE_REQUIREMENTS.read_text(encoding="utf-8")
    assert "google-cloud-storage>=2.10.0" in text
    assert "pandas" not in text
    assert "scikit-learn" not in text


def test_gcs_import_path_works_when_library_present(monkeypatch, tmp_path):
    storage = pytest.importorskip("google.cloud.storage")
    from google.cloud import storage as imported

    assert imported is storage
    assert hasattr(storage, "Client")

    path = tmp_path / "ops" / "fleet_devices.json"
    monkeypatch.setenv("FLEET_DEVICES_PATH", str(path))
    monkeypatch.setenv("GCS_STAGING_BUCKET", "gs://fleet-import-bucket")
    _enable_flush(monkeypatch)

    blob = MagicMock()
    blob.exists.return_value = False
    client = MagicMock()
    client.bucket.return_value.blob.return_value = blob
    monkeypatch.setattr(storage, "Client", MagicMock(return_value=client))

    dr.upsert_frame(_frame("VE30-FLEET-IMPORT"))

    blob.upload_from_string.assert_called_once()
    snapshot = json.loads(blob.upload_from_string.call_args[0][0])
    assert snapshot["devices"][0]["device_id"] == "VE30-FLEET-IMPORT"
