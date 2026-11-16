"""Passos e pressão na frota compacta — sem inventar valor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.schemas import WearableTelemetryRequest
from app.services.telemetry_store import _list_devices_from_frames, clear_all
from src.ops.device_registry import list_devices, upsert_frame
from src.ops.live_devices import carry_last_activity, compact_devices_from_frames, summarize_frame


def setup_function() -> None:
    clear_all()


def teardown_function() -> None:
    clear_all()


def _frame(
    *,
    device_id: str = "40:35:E6:40:C5:D8",
    patient_id: str = "PAT-HBAND-1975",
    timestamp: str,
    received_at: Optional[str] = None,
    heart_rate: float = 86,
    spo2: Optional[float] = 97,
    steps: Optional[int] = None,
    sys: Optional[float] = None,
    dia: Optional[float] = None,
    device_model: Optional[str] = "Galaxy Watch8 (4WHN)",
) -> dict:
    raw: dict = {"heart_rate_bpm": heart_rate}
    if spo2 is not None:
        raw["spo2_percent"] = spo2
    if steps is not None:
        raw["steps"] = steps
    if sys is not None:
        raw["blood_pressure_sys"] = sys
    if dia is not None:
        raw["blood_pressure_dia"] = dia
    if device_model:
        raw["device_model"] = device_model
    return {
        "patient_id": patient_id,
        "device_id": device_id,
        "timestamp": timestamp,
        "received_at": received_at or timestamp,
        "raw_telemetry": raw,
        "cleaned_telemetry": {"heart_rate_clean": heart_rate},
    }


def test_summarize_frame_copies_steps_bp_received_at_and_model():
    frame = _frame(
        timestamp="2026-09-30T16:40:32+00:00",
        steps=1678,
        sys=118,
        dia=76,
    )
    row = summarize_frame(frame, now=datetime(2026, 9, 30, 16, 41, tzinfo=timezone.utc))
    assert row["steps"] == 1678
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76
    assert row["device_model"] == "Galaxy Watch8 (4WHN)"
    assert str(row["received_at"]).startswith("2026-09-30T16:40:32")
    assert row["last_steps_at"]
    assert row["last_bp_at"]


def test_list_devices_from_frames_copies_raw_telemetry_vitals():
    payload = _list_devices_from_frames(
        [
            _frame(
                timestamp="2026-09-30T16:40:32+00:00",
                steps=1678,
                sys=118,
                dia=76,
            )
        ],
        q="",
        online=None,
        limit=200,
        offset=0,
        include_latest=False,
        patient_id=None,
    )
    row = payload["devices"][0]
    assert row["heart_rate"] == 86
    assert row["spo2"] == 97
    assert row["steps"] == 1678
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76
    assert row["device_model"] == "Galaxy Watch8 (4WHN)"
    assert row["received_at"]
    assert "latest" not in row


def test_later_hr_only_frame_keeps_last_valid_steps_and_bp():
    rows = compact_devices_from_frames(
        [
            _frame(
                timestamp="2026-09-30T16:40:32+00:00",
                steps=1678,
                sys=118,
                dia=76,
                heart_rate=86,
            ),
            _frame(
                timestamp="2026-09-30T16:45:00+00:00",
                heart_rate=90,
                spo2=98,
                steps=None,
                sys=None,
                dia=None,
                device_model=None,
            ),
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["heart_rate"] == 90
    assert row["spo2"] == 98
    assert row["steps"] == 1678
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76
    assert row["device_model"] == "Galaxy Watch8 (4WHN)"
    assert str(row["last_steps_at"]).startswith("2026-09-30T16:40:32")
    assert str(row["last_bp_at"]).startswith("2026-09-30T16:40:32")


def test_later_hr_only_frame_keeps_last_valid_spo2():
    rows = compact_devices_from_frames(
        [
            _frame(
                timestamp="2026-09-30T16:40:32+00:00",
                spo2=97,
                heart_rate=86,
            ),
            _frame(
                timestamp="2026-09-30T16:45:00+00:00",
                heart_rate=90,
                spo2=None,
                steps=None,
                sys=None,
                dia=None,
            ),
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["heart_rate"] == 90
    assert row["spo2"] == 97
    assert str(row["last_spo2_at"]).startswith("2026-09-30T16:40:32")


def test_carry_does_not_invent_steps_or_bp():
    incoming = summarize_frame(
        _frame(timestamp="2026-09-30T16:45:00+00:00", heart_rate=72, spo2=None),
        now=datetime(2026, 9, 30, 16, 46, tzinfo=timezone.utc),
    )
    row = carry_last_activity(None, incoming)
    assert row["steps"] is None
    assert row["blood_pressure_sys"] is None
    assert row["blood_pressure_dia"] is None
    assert row["last_steps_at"] is None
    assert row["last_bp_at"] is None
    assert row["spo2"] is None
    assert row["last_spo2_at"] is None


def test_zero_or_partial_bp_is_not_treated_as_valid():
    older = compact_devices_from_frames(
        [_frame(timestamp="2026-09-30T16:40:32+00:00", steps=1200, sys=118, dia=76)]
    )[0]
    incoming = {
        "device_id": older["device_id"],
        "heart_rate": 80,
        "steps": 0,
        "blood_pressure_sys": 130,
        "blood_pressure_dia": None,
        "received_at": "2026-09-30T16:50:00+00:00",
        "last_seen": "2026-09-30T16:50:00+00:00",
    }
    row = carry_last_activity(older, incoming)
    assert row["steps"] == 1200
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76


def test_device_registry_keeps_last_valid_across_upserts():
    upsert_frame(
        _frame(timestamp="2026-09-30T16:40:32+00:00", steps=1678, sys=118, dia=76)
    )
    upsert_frame(
        _frame(
            timestamp="2026-09-30T16:45:00+00:00",
            heart_rate=111,
            spo2=None,
            steps=None,
            sys=None,
            dia=None,
            device_model=None,
        )
    )
    row = list_devices(q="40:35:E6:40:C5:D8")["devices"][0]
    assert row["heart_rate"] == 111
    assert row["spo2"] == 97
    assert row["steps"] == 1678
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76
    assert row["device_model"] == "Galaxy Watch8 (4WHN)"
    assert row["last_steps_at"]
    assert row["last_bp_at"]


def test_schema_declares_optional_non_negative_steps():
    omitted = WearableTelemetryRequest.model_validate(
        {"patient_id": "PAT-STEPS-001", "heart_rate": 80}
    )
    assert omitted.steps is None

    accepted = WearableTelemetryRequest.model_validate(
        {"patient_id": "PAT-STEPS-001", "heart_rate": 80, "steps": 1678}
    )
    assert accepted.steps == 1678

    zero = WearableTelemetryRequest.model_validate(
        {"patient_id": "PAT-STEPS-001", "heart_rate": 80, "steps": 0}
    )
    assert zero.steps == 0

    try:
        WearableTelemetryRequest.model_validate(
            {"patient_id": "PAT-STEPS-001", "heart_rate": 80, "steps": -1}
        )
    except ValidationError:
        return
    raise AssertionError("steps negativo deveria falhar")


def test_fleet_summary_exposes_steps_and_bp(monkeypatch):
    from fastapi import FastAPI

    from src.ops.dashboard_routes import router as dashboard_ops_router

    fresh = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        "src.ops.dashboard_fleet.fetch_secure_fleet",
        lambda timeout=8.0: [
            {
                "device_id": "40:35:E6:40:C5:D8",
                "patient_id": "PAT-HBAND-1975",
                "last_seen": fresh,
                "received_at": fresh,
                "online": True,
                "heart_rate": 86,
                "spo2": 97,
                "steps": 1678,
                "blood_pressure_sys": 118,
                "blood_pressure_dia": 76,
                "device_model": "Galaxy Watch8 (4WHN)",
                "last_steps_at": fresh,
                "last_bp_at": fresh,
            }
        ],
    )
    app = FastAPI()
    app.include_router(dashboard_ops_router)
    client = TestClient(app)
    res = client.get("/api/v1/ops/fleet-summary?limit=50")
    assert res.status_code == 200
    row = res.json()["devices"][0]
    assert row["steps"] == 1678
    assert row["blood_pressure_sys"] == 118
    assert row["blood_pressure_dia"] == 76
    assert row["device_model"] == "Galaxy Watch8 (4WHN)"
    assert row["last_steps_at"]
    assert row["last_bp_at"]


def test_dashboard_js_uses_pt_br_formatters():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
    html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "fleetLogic.formatSteps" in app_js
    assert "fleetLogic.formatBloodPressure" in app_js
    assert "fleetLogic.carryLastActivity" in app_js
    assert "devicePollInFlight" in app_js
    assert ">Passos</th>" in html
    assert ">Pressão</th>" in html
