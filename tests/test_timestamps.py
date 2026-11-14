"""Timestamps da frota — UTC canônico e horário de Brasília."""

from datetime import datetime, timezone

from src.ops.live_devices import summarize_frame
from src.ops.timestamps import (
    ONLINE_WITHIN_MS,
    ONLINE_WITHIN_SECONDS,
    is_online,
    local_display,
    parse_timestamp,
    stamp_ingest,
    utc_iso,
)


def test_utc_instant_displays_brasilia():
    dt = parse_timestamp("2026-08-24T21:14:37Z")
    assert dt is not None
    assert utc_iso(dt).startswith("2026-08-24T21:14:37")
    assert local_display(dt) == "24/08/2026 18:14:37"


def test_naive_timestamp_is_america_sao_paulo():
    dt = parse_timestamp("2026-08-24 18:14:37")
    assert dt is not None
    assert dt.astimezone(timezone.utc).hour == 21


def test_stamp_ingest_keeps_received_at_for_liveness():
    stamps = stamp_ingest(
        "2026-08-01T10:00:00Z",
        received=datetime(2026, 8, 24, 21, 15, 0, tzinfo=timezone.utc),
    )
    assert stamps["timestamp"].startswith("2026-08-01T10:00:00")
    assert stamps["received_at"].startswith("2026-08-24T21:15:00")
    assert stamps["last_seen_local"] == "24/08/2026 18:15:00"


def test_summarize_uses_received_at_for_online_status():
    now = datetime(2026, 8, 24, 21, 16, 0, tzinfo=timezone.utc)
    row = summarize_frame(
        {
            "device_id": "VE30-1",
            "patient_id": "PAT-1",
            "timestamp": "2026-08-01T10:00:00Z",
            "received_at": "2026-08-24T21:15:50Z",
            "raw_telemetry": {"heart_rate_bpm": 80, "spo2_percent": 98},
            "cleaned_telemetry": {"heart_rate_clean": 80},
        },
        now=now,
    )
    assert row["online"] is True
    assert row["last_seen_local"] == "24/08/2026 18:15:50"


def test_is_online_two_hour_window_covers_ios_background_gap():
    now = datetime(2026, 8, 24, 21, 16, 0, tzinfo=timezone.utc)
    assert ONLINE_WITHIN_SECONDS == 2 * 60 * 60
    assert ONLINE_WITHIN_MS == 2 * 60 * 60 * 1000
    fifty_min = datetime(2026, 8, 24, 20, 26, 0, tzinfo=timezone.utc)
    assert is_online(fifty_min, now=now) is True
    two_hours = datetime(2026, 8, 24, 19, 16, 0, tzinfo=timezone.utc)
    assert is_online(two_hours, now=now) is True
    over = datetime(2026, 8, 24, 19, 15, 59, tzinfo=timezone.utc)
    assert is_online(over, now=now) is False
