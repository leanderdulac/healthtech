"""Status honesto de conexões app ↔ device."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))

from app.services.connection_status import (  # noqa: E402
    build_connection_status,
    ingest_source_from_frame,
    public_connection_view,
)


def _frame(source: str, age_sec: int, device_id: str = "HBAND-SIM-1", hr: float = 78.0):
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    return {
        "patient_id": "PAT-TEST-001",
        "device_id": device_id,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "ingest_source": source,
        "raw_telemetry": {
            "heart_rate_bpm": hr,
            "ingest_source": source,
        },
        "cleaned_telemetry": {"heart_rate_clean": hr},
    }


def test_ingest_source_from_frame_defaults_to_manual():
    assert ingest_source_from_frame({}) == "companion_manual"
    assert ingest_source_from_frame({"raw_telemetry": {"ingest_source": "ble_sim"}}) == "ble_sim"


def test_ble_sim_is_not_claimed_as_physical_hband():
    payload = build_connection_status({"PAT-TEST-001": [_frame("ble_sim", 5)]})
    assert payload["device"]["status"] == "ble_sim"
    assert payload["device"]["ble_simulated"] is True
    assert payload["device"]["ble_physical"] is False
    assert payload["device"]["pairing_ready"] is True
    assert "não é BLE físico" in payload["device"]["label"]
    sim = [r for r in payload["device"]["roadmap"] if r["id"] == "ble_sim"][0]
    sdk = [r for r in payload["device"]["roadmap"] if r["id"] == "ble_hband_sdk"][0]
    assert sim["done"] is True
    assert sdk["done"] is False


def test_ble_hband_marks_physical_pairing():
    payload = build_connection_status({"PAT-TEST-001": [_frame("ble_hband", 4)]})
    assert payload["device"]["status"] == "ble_hband"
    assert payload["device"]["ble_physical"] is True
    assert payload["device"]["pairing_ready"] is True


def test_manual_http_is_via_app_not_ble():
    payload = build_connection_status({"PAT-TEST-001": [_frame("companion_manual", 3)]})
    assert payload["device"]["status"] == "via_app"
    assert payload["device"]["ble_physical"] is False
    assert payload["device"]["pairing_ready"] is False


def test_public_view_omits_patient_id():
    full = build_connection_status({"PAT-SECRET": [_frame("ble_sim", 2)]})
    pub = public_connection_view(full)
    assert pub["public"] is True
    assert pub["sessions"] == []
    latest = pub["mobile_app"]["latest"]
    assert latest is not None
    assert "patient_id" not in latest
    assert latest["device_id"] == "HBAND-SIM-1"
