"""GET /api/v1/ops/devices/{id}: authz, cadastro sem nomes, sem GPS."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ops.dashboard_routes import router as dashboard_ops_router
from src.ops.device_detail import (
    attach_app_version,
    build_device_detail,
    normalize_app_version,
)
from src.ops.device_detail_routes import router as device_detail_router
from src.ops.device_registry import clear_all, upsert_frame

ROOT = Path(__file__).resolve().parents[1]
READ_HEADERS = {"X-API-Key": "ht_read_test_key_32chars_long_token"}
INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}

DEVICE_ID = "VE30-AA:BB:CC:DD:EE:FF"
PATIENT_ID = "PAT-KEEP"


def _ops_app() -> FastAPI:
    application = FastAPI()
    application.include_router(dashboard_ops_router)
    application.include_router(device_detail_router)
    return application


client = TestClient(_ops_app())


def setup_function() -> None:
    clear_all()


def teardown_function() -> None:
    clear_all()


def _upsert_watch(**extra) -> None:
    frame = {
        "patient_id": PATIENT_ID,
        "device_id": DEVICE_ID,
        "timestamp": "2026-11-14T19:40:00+00:00",
        "received_at": "2026-11-14T19:40:00+00:00",
        "ingest_source": "ble_hband",
        "app_version": "1.4.2",
        "device_label": "iPhone de teste",
        "extra": {"app_version": "1.4.2", "device_label": "iPhone de teste"},
        "raw_telemetry": {
            "heart_rate_bpm": 86,
            "spo2_percent": 97,
            "steps": 1678,
            "blood_pressure_sys": 118,
            "blood_pressure_dia": 76,
            "device_model": "Galaxy Watch8 (4WHN)",
        },
        "cleaned_telemetry": {"heart_rate_clean": 86},
    }
    frame.update(extra)
    upsert_frame(frame)


def test_normalize_app_version_trims_and_caps():
    assert normalize_app_version("  1.4.2  ") == "1.4.2"
    assert normalize_app_version("") is None
    assert normalize_app_version("x" * 80) == "x" * 64


def test_attach_app_version_writes_extra_and_frame():
    frame: dict = {"device_id": DEVICE_ID}
    extra = attach_app_version(frame, {}, "1.4.2")
    assert extra["app_version"] == "1.4.2"
    assert frame["app_version"] == "1.4.2"
    assert frame["extra"]["app_version"] == "1.4.2"


def test_device_detail_requires_read_scope():
    _upsert_watch()
    assert client.get(f"/api/v1/ops/devices/{DEVICE_ID}").status_code == 401
    denied = client.get(f"/api/v1/ops/devices/{DEVICE_ID}", headers=INGEST_HEADERS)
    assert denied.status_code == 403
    assert "municipality_id" not in denied.text


def test_device_detail_idor_blocks_other_patient(monkeypatch):
    _upsert_watch()
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-OTHER")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        res = client.get(f"/api/v1/ops/devices/{DEVICE_ID}", headers=READ_HEADERS)
    finally:
        get_settings.cache_clear()
    assert res.status_code == 403
    assert "municipality_id" not in res.text
    assert "ubs_id" not in res.text
    assert DEVICE_ID not in (res.json().get("device_id") or "")


def test_device_detail_returns_cadastro_ids_without_names():
    _upsert_watch()
    enrollment = {
        "patient_id": PATIENT_ID,
        "municipality_id": "3118007",
        "ubs_id": "ubs-1",
        "display_name": "não deve vazar",
        "municipality_name": "Congonhas",
    }
    with patch("src.ops.operational_patients.get_patient", return_value=enrollment):
        res = client.get(f"/api/v1/ops/devices/{DEVICE_ID}", headers=READ_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["device_id"] == DEVICE_ID
    assert body["patient_id"] == PATIENT_ID
    assert body["device_model"] == "Galaxy Watch8 (4WHN)"
    assert body["device_label"] == "iPhone de teste"
    assert body["ingest_source"] == "ble_hband"
    assert body["app_version"] == "1.4.2"
    assert body["vitals"]["steps"] == 1678
    assert body["vitals"]["blood_pressure_sys"] == 118
    assert body["region"]["municipality_id"] == "3118007"
    assert body["region"]["ubs_id"] == "ubs-1"
    assert body["region"]["source"] == "cadastro"
    assert "municipality_name" not in body["region"]
    assert "ubs_name" not in body["region"]
    assert "display_name" not in body
    for forbidden in ("latitude", "longitude", "gps", "location", "municipality_name"):
        assert forbidden not in body
        assert forbidden not in body["region"]


def test_device_detail_missing_enrollment_ids_are_null():
    _upsert_watch()
    with patch(
        "src.ops.operational_patients.get_patient",
        return_value={"patient_id": PATIENT_ID, "municipality_id": None, "ubs_id": None},
    ):
        res = client.get(f"/api/v1/ops/devices/{DEVICE_ID}", headers=READ_HEADERS)
    assert res.status_code == 200
    assert res.json()["region"]["municipality_id"] is None
    assert res.json()["region"]["ubs_id"] is None
    assert res.json()["region"]["source"] == "cadastro"


def test_device_detail_unknown_device_is_404():
    res = client.get("/api/v1/ops/devices/missing-watch", headers=READ_HEADERS)
    assert res.status_code == 404


def test_ingest_header_lands_on_device_detail():
    frame = {
        "patient_id": PATIENT_ID,
        "device_id": "VE30-APP-VER",
        "timestamp": "2026-11-14T19:40:00+00:00",
        "received_at": "2026-11-14T19:40:00+00:00",
        "ingest_source": "ble_hband",
        "heart_rate": 72.0,
        "raw_telemetry": {"heart_rate_bpm": 72},
    }
    attach_app_version(frame, {}, "1.4.2")
    upsert_frame(frame)
    detail = client.get("/api/v1/ops/devices/VE30-APP-VER", headers=READ_HEADERS)
    assert detail.status_code == 200
    assert detail.json()["app_version"] == "1.4.2"


def test_secure_ingest_persists_x_app_version_header(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("APP_MODE", "secure")
    monkeypatch.setenv("SECRET_SALT", "test-salt-not-for-production-use-32c")
    from app.config import get_settings
    from app.main import create_app
    from app.services import telemetry_store

    get_settings.cache_clear()
    telemetry_store.clear_all()
    clear_all()
    application = create_app()
    try:
        with TestClient(application) as secure:
            ingested = secure.post(
                "/api/v1/wearables/ingest",
                headers={**INGEST_HEADERS, "X-App-Version": "1.4.2"},
                json={
                    "patient_id": PATIENT_ID,
                    "device_id": "VE30-APP-VER",
                    "heart_rate": 72.0,
                    "ingest_source": "ble_hband",
                },
            )
            assert ingested.status_code == 200, ingested.text
            body = ingested.json()
            assert body.get("app_version") == "1.4.2"
            assert (body.get("extra") or {}).get("app_version") == "1.4.2"
            detail = secure.get("/api/v1/ops/devices/VE30-APP-VER", headers=READ_HEADERS)
            assert detail.status_code == 200
            assert detail.json()["app_version"] == "1.4.2"
    finally:
        telemetry_store.clear_all()
        clear_all()
        get_settings.cache_clear()


def test_fleet_summary_strips_region_even_if_source_has_it(monkeypatch):
    monkeypatch.setattr(
        "src.ops.dashboard_fleet.present_fleet",
        lambda **kwargs: {
            "source": "test",
            "counts": {"total": 1, "online": 0, "offline": 1},
            "limit": 50,
            "offset": 0,
            "coverage": "fleet",
            "include_synthetic": False,
            "devices": [
                {
                    "device_id": DEVICE_ID,
                    "patient_id": PATIENT_ID,
                    "municipality_id": "3118007",
                    "ubs_id": "ubs-1",
                    "region": {"municipality_id": "3118007"},
                    "latitude": -20.5,
                    "app_version": "1.4.2",
                }
            ],
        },
    )
    res = client.get("/api/v1/ops/fleet-summary?limit=50")
    assert res.status_code == 200
    row = res.json()["devices"][0]
    assert row["device_id"] == DEVICE_ID
    for forbidden in (
        "municipality_id",
        "ubs_id",
        "region",
        "latitude",
        "longitude",
        "app_version",
        "gps",
        "ingest_source",
        "device_label",
    ):
        assert forbidden not in row


def test_build_device_detail_never_copies_location_keys():
    payload = build_device_detail(
        {
            "device_id": DEVICE_ID,
            "patient_id": PATIENT_ID,
            "online": True,
            "latitude": -20.1,
            "municipality_name": "Congonhas",
            "latest": {"extra": {"app_version": "1.0"}},
        }
    )
    assert "latitude" not in payload
    assert "municipality_name" not in payload
    assert payload["region"]["source"] == "cadastro"
    assert "municipality_name" not in payload["region"]


def test_openapi_declares_ops_device_detail():
    yaml_text = (ROOT / "docs" / "openapi" / "hband-wearable.yaml").read_text(encoding="utf-8")
    assert "/api/v1/ops/devices/{device_id}" in yaml_text
    assert "X-App-Version" in yaml_text
    assert "enum: [cadastro]" in yaml_text
    spec = client.app.openapi()
    assert "/api/v1/ops/devices/{device_id}" in spec["paths"]
    for path in ("src/api_server.py", "src/api_monolith_runtime.py"):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "device_detail_router" in source
        assert "X-App-Version" in source


def test_dashboard_device_details_drawer_markup():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "dashboard" / "style.css").read_text(encoding="utf-8")
    app_js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    details_js = (ROOT / "dashboard" / "device_details.js").read_text(encoding="utf-8")
    assert 'id="device-details-panel"' in html
    assert "Detalhes do relógio" in html
    assert "device_details.js?v=20261114v" in html
    assert "bindDeviceDetailsPanel" in app_js
    assert "fetchDeviceDetail" in app_js
    assert "onRequestApiAccess" in app_js
    assert 'switchTab("api-access")' in app_js
    assert "renderAuthPrompt" in details_js
    assert "rejectedKey" in details_js
    assert "body.device-details-open" in css
    assert "municipality_id" in details_js
    assert "municipality_name" not in details_js
    assert "gps" not in app_js.lower()
    assert "latitude" not in app_js.lower()


def test_device_details_js_suite():
    import shutil
    import subprocess

    node = shutil.which("node") or shutil.which("nodejs")
    assert node, "node is required to verify dashboard/device_details.js"
    script = ROOT / "tests" / "js" / "test_device_details.js"
    result = subprocess.run([node, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
