"""Relógios/wearables vistos recentemente (histórico em memória)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

ONLINE_WITHIN_SECONDS = 120.0


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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
    ts = frame.get("timestamp")
    dt = _parse_ts(ts) if isinstance(ts, str) else None
    age = (now - dt).total_seconds() if dt else None
    raw = frame.get("raw_telemetry") or {}
    return {
        "device_id": frame.get("device_id") or "unknown",
        "patient_id": frame.get("patient_id"),
        "last_seen": ts,
        "online": bool(age is not None and 0 <= age <= ONLINE_WITHIN_SECONDS),
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
            ts = str(frame.get("timestamp") or "")
            prev = latest_by_device.get(device_id)
            if prev is None or ts >= str(prev.get("timestamp") or ""):
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
