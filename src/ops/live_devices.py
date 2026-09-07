"""Relógios/wearables vistos recentemente (histórico em memória)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.ops.timestamps import (
    ONLINE_WITHIN_SECONDS,
    age_seconds,
    is_online,
    local_display,
    parse_timestamp,
    utc_iso,
)


def _heart_rate(frame: Mapping[str, Any]) -> Optional[float]:
    cleaned = frame.get("cleaned_telemetry") or {}
    raw = frame.get("raw_telemetry") or {}
    val = cleaned.get("heart_rate_clean")
    if val is None:
        val = raw.get("heart_rate_bpm")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def summarize_frame(frame: Mapping[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    raw = frame.get("raw_telemetry") or {}
    received = parse_timestamp(frame.get("received_at")) or parse_timestamp(frame.get("timestamp"))
    sample = parse_timestamp(frame.get("timestamp")) or received
    live_ref = received or sample
    return {
        "device_id": frame.get("device_id") or "unknown",
        "patient_id": frame.get("patient_id"),
        "last_seen": utc_iso(live_ref) if live_ref else frame.get("timestamp"),
        "received_at": utc_iso(received) if received else frame.get("received_at"),
        "last_seen_local": frame.get("last_seen_local") or (local_display(live_ref) if live_ref else None),
        "device_time_local": frame.get("device_time_local") or (local_display(sample) if sample else None),
        "online": is_online(live_ref, now=now) if live_ref else False,
        "age_seconds": age_seconds(live_ref, now=now),
        "heart_rate": _heart_rate(frame),
        "spo2": raw.get("spo2_percent"),
        "latest": dict(frame),
    }


def devices_from_patient_history(
    history: Mapping[str, Iterable[Mapping[str, Any]]],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    latest_by_device: Dict[str, Mapping[str, Any]] = {}
    for frames in history.values():
        for frame in frames:
            device_id = str(frame.get("device_id") or "unknown")
            ts = parse_timestamp(frame.get("received_at") or frame.get("timestamp"))
            prev = latest_by_device.get(device_id)
            prev_ts = parse_timestamp((prev or {}).get("received_at") or (prev or {}).get("timestamp")) if prev else None
            if prev is None or (ts and prev_ts and ts >= prev_ts) or (ts and not prev_ts):
                latest_by_device[device_id] = frame
    rows = [summarize_frame(frame, now=now) for frame in latest_by_device.values()]
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    return rows


def merge_device_lists(*lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for group in lists:
        for row in group:
            device_id = str(row.get("device_id") or "unknown")
            prev = by_id.get(device_id)
            if prev is None or str(row.get("last_seen") or "") >= str(prev.get("last_seen") or ""):
                by_id[device_id] = row
    rows = list(by_id.values())
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    return rows
