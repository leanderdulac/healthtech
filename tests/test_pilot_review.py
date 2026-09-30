"""Registro e resumo do piloto. ble_sim não entra na taxa."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))

from app.services.pilot_review import mark_event, record_ingest, summary  # noqa: E402


def _frame(source: str, *, alert: bool, rule: str = "spo2_5", ts: str = "2026-09-26T12:00:00Z"):
    return {
        "patient_id": "PAT-PILOT-001",
        "device_id": "HBAND-AA",
        "timestamp": ts,
        "ingest_source": source,
        "clinical_alerts": {
            "engine": "alert_matrix_rules",
            "ingest_source": source,
            "pilot_eligible": source == "ble_hband",
            "is_true_alert": alert,
            "severity": "critico" if alert else "none",
            "primary_rule_id": rule if alert else None,
            "primary_alert_name": "hipoxemia" if alert else None,
            "decision": "rule_only" if alert else "stable_or_noise",
            "matrix_version": "next2u-158-971-2026-08-16",
            "provenance": {"git_sha": "abc", "rules_sha256": "ff"},
        },
    }


def test_sim_is_excluded_from_false_alarm_rate(tmp_path):
    path = tmp_path / "events.jsonl"
    sim_id = record_ingest(_frame("ble_sim", alert=True), path)
    real_id = record_ingest(
        _frame("ble_hband", alert=True, ts="2026-09-26T12:00:00Z"),
        path,
    )
    later_id = record_ingest(
        _frame("ble_hband", alert=True, rule="hr_9", ts="2026-09-27T12:00:00Z"),
        path,
    )
    assert sim_id and real_id and later_id
    assert mark_event(sim_id, "false_alarm", path) is True
    assert mark_event(real_id, "false_alarm", path) is True
    assert mark_event(later_id, "correct", path) is True

    report = summary(path)
    assert report["events"] == 3
    assert report["pilot_eligible"] == 2
    assert report["excluded"] == 1
    assert report["false_alarms"] == 1
    assert report["window_hours"] == 24.0
    assert report["false_alarms_per_24h"] == 1.0
    assert report["rules_fired"]["spo2_5"] == 1
    assert report["rules_fired"]["hr_9"] == 1


def test_secure_ingest_frame_stays_on_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("PILOT_REVIEW_PATH", str(tmp_path / "events.jsonl"))
    from app.services.signal_core import process_ingest_frame

    frame = process_ingest_frame(
        {
            "patient_id": "PAT-X",
            "device_id": "HBAND-1",
            "heart_rate": 88,
            "spo2": 88,
            "ingest_source": "ble_hband",
        }
    )
    alerts = frame["clinical_alerts"]
    assert frame["ingest_source"] == "ble_hband"
    assert alerts["engine"] == "alert_matrix_rules"
    assert alerts["pilot_eligible"] is True
    assert alerts["ml"] is None
    assert alerts["review_event_id"]
    report = summary(tmp_path / "events.jsonl")
    assert report["pilot_eligible"] == 1
    assert report["false_alarms_per_24h"] is None


def test_unmarked_pilot_has_no_rate(tmp_path):
    path = tmp_path / "events.jsonl"
    record_ingest(_frame("ble_hband", alert=False), path)
    report = summary(path)
    assert report["marked"] == 0
    assert report["false_alarms_per_24h"] is None
