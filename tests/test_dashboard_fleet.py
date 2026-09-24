"""Frota do dashboard: status online, filtro sintético e bootstrap sem chave."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from src.api_server import app
from src.ops.device_registry import clear_all, is_synthetic_device, list_devices, upsert_frame
from src.ops.fleet_online import resolve_fleet_online
from src.ops.timestamps import ONLINE_WITHIN_SECONDS

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def _stale_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()


def _fresh_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_function() -> None:
    clear_all()


def teardown_function() -> None:
    clear_all()


def test_resolve_fleet_online_focus_does_not_fake_status():
    stale = {
        "device_id": "ve30-smoke",
        "online": False,
        "timestamp": _stale_iso(),
        "received_at": _stale_iso(),
    }
    assert resolve_fleet_online({"online": False}, stale, from_live_ingest=False) is False
    recent_but_focus = {
        "device_id": "ve30-smoke",
        "timestamp": _fresh_iso(),
        "received_at": _fresh_iso(),
    }
    assert resolve_fleet_online({"online": False}, recent_but_focus, from_live_ingest=False) is False
    assert resolve_fleet_online({}, recent_but_focus, from_live_ingest=False) is False


def test_resolve_fleet_online_live_ws_uses_recency():
    now = datetime.now(timezone.utc)
    live = {"device_id": "VE30-REAL-001", "received_at": now.isoformat()}
    assert resolve_fleet_online({}, live, from_live_ingest=True, now=now) is True
    stale = {
        "device_id": "VE30-REAL-001",
        "received_at": (now - timedelta(seconds=ONLINE_WITHIN_SECONDS + 30)).isoformat(),
    }
    assert resolve_fleet_online({}, stale, from_live_ingest=True, now=now) is False
    assert resolve_fleet_online({}, {"online": True}, from_live_ingest=False, now=now) is True


def test_is_synthetic_device_known_patterns():
    assert is_synthetic_device({"device_id": "ve30-smoke", "patient_id": "smoke-alert-aa"})
    assert is_synthetic_device({"device_id": "VE30-PROBE-001", "patient_id": "PAT-1"})
    assert is_synthetic_device({"device_id": "VE30-TIMECHECK", "patient_id": "PAT-2"})
    assert is_synthetic_device({"device_id": "watch-1", "patient_id": "smoke-pr14"})
    assert is_synthetic_device({"device_id": "clinic-01", "synthetic": True})
    assert not is_synthetic_device({"device_id": "VE30-AA:BB:CC:DD:EE:FF", "patient_id": "PAT-KEEP"})


def test_list_devices_hides_synthetic_by_default_and_opt_in():
    upsert_frame(
        {
            "patient_id": "PAT-KEEP",
            "device_id": "VE30-REAL-001",
            "timestamp": _stale_iso(),
            "raw_telemetry": {"heart_rate_bpm": 70, "spo2_percent": 97},
        }
    )
    upsert_frame(
        {
            "patient_id": "smoke-alert-zz",
            "device_id": "ve30-smoke",
            "timestamp": _stale_iso(),
            "raw_telemetry": {"heart_rate_bpm": 88, "spo2_percent": 96},
        }
    )
    hidden = list_devices(limit=50)
    ids = {row["device_id"] for row in hidden["devices"]}
    assert "VE30-REAL-001" in ids
    assert "ve30-smoke" not in ids
    assert hidden["include_synthetic"] is False
    shown = list_devices(limit=50, include_synthetic=True)
    ids_all = {row["device_id"] for row in shown["devices"]}
    assert "ve30-smoke" in ids_all
    assert shown["include_synthetic"] is True


def test_dashboard_bootstrap_omits_key_even_if_env_set(monkeypatch):
    monkeypatch.setenv("READ_API_KEY", "ht_read_test_key_32chars_long_token")
    monkeypatch.setenv("API_KEY", "ht_admin_test_key_32chars_long_token")
    res = client.get("/api/v1/ops/dashboard-bootstrap")
    assert res.status_code == 200
    body = res.json()
    assert "api_key" not in body
    assert "READ_API_KEY" not in res.text
    assert "API_KEY" not in body
    for env_name in ("READ_API_KEY", "API_KEY"):
        value = os.environ.get(env_name)
        if value:
            assert value not in res.text
    assert body["fleet_summary_path"] == "/api/v1/ops/fleet-summary"


def test_fleet_summary_is_public_and_hides_synthetics():
    upsert_frame(
        {
            "patient_id": "PAT-KEEP",
            "device_id": "VE30-REAL-001",
            "timestamp": _stale_iso(),
            "raw_telemetry": {"heart_rate_bpm": 71, "spo2_percent": 98},
        }
    )
    upsert_frame(
        {
            "patient_id": "smoke-alert-zz",
            "device_id": "VE30-PROBE-001",
            "timestamp": _stale_iso(),
            "raw_telemetry": {"heart_rate_bpm": 90, "spo2_percent": 95},
        }
    )
    public = client.get("/api/v1/ops/fleet-summary?limit=500")
    assert public.status_code == 200
    body = public.json()
    assert body["public"] is True
    assert "api_key" not in body
    ids = {row["device_id"] for row in body["devices"]}
    assert "VE30-REAL-001" in ids
    assert "VE30-PROBE-001" not in ids
    for row in body["devices"]:
        assert "latest" not in row
        assert set(row).issubset(
            {
                "device_id",
                "patient_id",
                "last_seen",
                "received_at",
                "last_seen_local",
                "device_time_local",
                "online",
                "age_seconds",
                "heart_rate",
                "spo2",
                "synthetic",
            }
        )
        assert row["online"] is False

    opted = client.get("/api/v1/ops/fleet-summary?limit=500&include_synthetic=true")
    assert opted.status_code == 200
    opted_ids = {row["device_id"] for row in opted.json()["devices"]}
    assert "VE30-PROBE-001" in opted_ids


def test_authenticated_devices_default_hides_synthetic():
    upsert_frame(
        {
            "patient_id": "PAT-KEEP",
            "device_id": "VE30-REAL-002",
            "timestamp": _stale_iso(),
            "raw_telemetry": {"heart_rate_bpm": 66, "spo2_percent": 97},
        }
    )
    upsert_frame(
        {
            "patient_id": "PAT-KEEP",
            "device_id": "smoke-pr14",
            "timestamp": _stale_iso(),
            "raw_telemetry": {"heart_rate_bpm": 80, "spo2_percent": 96},
        }
    )
    listed = client.get(
        "/api/v1/wearables/devices?limit=200",
        headers={"X-API-Key": "ht_read_test_key_32chars_long_token"},
    )
    assert listed.status_code == 200
    ids = {row["device_id"] for row in listed.json()["devices"]}
    assert "VE30-REAL-002" in ids
    assert "smoke-pr14" not in ids
    shown = client.get(
        "/api/v1/wearables/devices?limit=200&include_synthetic=true",
        headers={"X-API-Key": "ht_read_test_key_32chars_long_token"},
    )
    assert "smoke-pr14" in {row["device_id"] for row in shown.json()["devices"]}


def test_ingest_endpoints_still_require_write_scope():
    payload = {
        "patient_id": "PAT-KEEP",
        "device_id": "VE30-REAL-INGEST",
        "heart_rate": 74.0,
    }
    denied = client.post("/api/v1/wearables/ingest", json=payload)
    assert denied.status_code in {401, 403}
    ok = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": "ht_ingest_test_key_32chars_long_token"},
        json=payload,
    )
    assert ok.status_code == 200
    batch = client.post(
        "/api/v1/wearables/batch-ingest",
        headers={"X-API-Key": "ht_ingest_test_key_32chars_long_token"},
        json={"patient_id": "PAT-KEEP", "readings": [payload]},
    )
    assert batch.status_code == 200


def test_fleet_logic_js_focus_does_not_fake_online():
    import shutil

    node = shutil.which("node") or shutil.which("nodejs")
    assert node, "node is required to verify dashboard/fleet_logic.js"
    script = ROOT / "tests" / "js" / "test_fleet_logic.js"
    result = subprocess.run(
        [node, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
