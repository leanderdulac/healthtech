"""Relógios/wearables vistos recentemente (histórico em memória)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.ops.timestamps import (
    age_seconds,
    is_online,
    local_display,
    parse_timestamp,
    utc_iso,
)

COMPACT_FIELDS = (
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
    "steps",
    "blood_pressure_sys",
    "blood_pressure_dia",
    "device_model",
    "last_steps_at",
    "last_bp_at",
    "ingest_source",
    "device_label",
    "app_version",
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


def _as_positive(value: Any) -> Optional[float]:
    """Número medido e > 0. Zero, negativo e lixo não entram na frota."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def valid_steps(value: Any) -> Optional[int]:
    number = _as_positive(value)
    if number is None:
        return None
    return int(number)


def valid_blood_pressure(
    systolic: Any, diastolic: Any
) -> tuple[Optional[float], Optional[float]]:
    sys_val = _as_positive(systolic)
    dia_val = _as_positive(diastolic)
    if sys_val is None or dia_val is None:
        return None, None
    return sys_val, dia_val


def _activity_stamp(row: Mapping[str, Any]) -> Optional[str]:
    return row.get("received_at") or row.get("last_seen") or row.get("timestamp")


def _device_model(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:80] if stripped else None


def _optional_text(value: Any, max_len: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:max_len] if stripped else None


def _keep_text(
    row: Dict[str, Any],
    prev: Mapping[str, Any],
    key: str,
    *,
    max_len: int,
) -> None:
    current = _optional_text(row.get(key), max_len)
    if current:
        row[key] = current
        return
    previous = _optional_text(prev.get(key), max_len)
    if previous:
        row[key] = previous


def compact_row(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """Linha compacta da frota — sem `latest`."""
    item = {key: summary.get(key) for key in COMPACT_FIELDS}
    item["device_id"] = item.get("device_id") or "unknown"
    return item


def summarize_frame(frame: Mapping[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    raw = frame.get("raw_telemetry") or {}
    received = parse_timestamp(frame.get("received_at")) or parse_timestamp(frame.get("timestamp"))
    sample = parse_timestamp(frame.get("timestamp")) or received
    live_ref = received or sample
    stamp = utc_iso(received) if received else frame.get("received_at")
    extra = frame.get("extra") if isinstance(frame.get("extra"), dict) else {}
    steps = raw.get("steps")
    sys_val = raw.get("blood_pressure_sys")
    dia_val = raw.get("blood_pressure_dia")
    valid_sys, valid_dia = valid_blood_pressure(sys_val, dia_val)
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
        "steps": steps,
        "blood_pressure_sys": sys_val,
        "blood_pressure_dia": dia_val,
        "device_model": _device_model(raw.get("device_model") or frame.get("device_model")),
        "last_steps_at": stamp if valid_steps(steps) is not None else None,
        "last_bp_at": stamp if valid_sys is not None and valid_dia is not None else None,
        "ingest_source": _optional_text(
            frame.get("ingest_source") or extra.get("ingest_source") or raw.get("ingest_source"),
            32,
        ),
        "device_label": _optional_text(
            frame.get("device_label") or extra.get("device_label"),
            80,
        ),
        "app_version": _optional_text(
            frame.get("app_version") or extra.get("app_version"),
            64,
        ),
        "latest": dict(frame),
    }


def carry_last_activity(
    previous: Optional[Mapping[str, Any]],
    incoming: Mapping[str, Any],
) -> Dict[str, Any]:
    """Mantém o último BP/passos válidos (>0) quando o frame novo só traz FC.

    Não inventa valor: se nunca houve medição, o campo fica ausente/None.
    """
    row = dict(incoming)
    prev = dict(previous or {})

    incoming_steps = valid_steps(row.get("steps"))
    if incoming_steps is not None:
        row["steps"] = incoming_steps
        row["last_steps_at"] = row.get("last_steps_at") or _activity_stamp(row)
    elif valid_steps(prev.get("steps")) is not None:
        row["steps"] = prev.get("steps")
        row["last_steps_at"] = prev.get("last_steps_at") or _activity_stamp(prev)
    else:
        row["steps"] = None
        row["last_steps_at"] = None

    incoming_sys, incoming_dia = valid_blood_pressure(
        row.get("blood_pressure_sys"), row.get("blood_pressure_dia")
    )
    if incoming_sys is not None and incoming_dia is not None:
        row["blood_pressure_sys"] = incoming_sys
        row["blood_pressure_dia"] = incoming_dia
        row["last_bp_at"] = row.get("last_bp_at") or _activity_stamp(row)
    else:
        prev_sys, prev_dia = valid_blood_pressure(
            prev.get("blood_pressure_sys"), prev.get("blood_pressure_dia")
        )
        if prev_sys is not None and prev_dia is not None:
            row["blood_pressure_sys"] = prev_sys
            row["blood_pressure_dia"] = prev_dia
            row["last_bp_at"] = prev.get("last_bp_at") or _activity_stamp(prev)
        else:
            row["blood_pressure_sys"] = None
            row["blood_pressure_dia"] = None
            row["last_bp_at"] = None

    if _device_model(row.get("device_model")) is None:
        prev_model = _device_model(prev.get("device_model"))
        if prev_model is not None:
            row["device_model"] = prev_model

    _keep_text(row, prev, "ingest_source", max_len=32)
    _keep_text(row, prev, "device_label", max_len=80)
    _keep_text(row, prev, "app_version", max_len=64)

    return row


def compact_devices_from_frames(
    frames: Iterable[Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
    include_latest: bool = False,
) -> List[Dict[str, Any]]:
    """Uma linha compacta por device, reusando summarize_frame e last-valid."""
    now = now or datetime.now(timezone.utc)
    by_device: Dict[str, Dict[str, Any]] = {}
    latest: Dict[str, Mapping[str, Any]] = {}

    def _sort_key(frame: Mapping[str, Any]) -> str:
        return str(frame.get("received_at") or frame.get("timestamp") or "")

    for frame in sorted(frames, key=_sort_key):
        compact = compact_row(summarize_frame(frame, now=now))
        device_id = str(compact.get("device_id") or "unknown")
        compact["device_id"] = device_id
        by_device[device_id] = carry_last_activity(by_device.get(device_id), compact)
        latest[device_id] = frame
    rows = list(by_device.values())
    if include_latest:
        for row in rows:
            frame = latest.get(str(row.get("device_id")))
            if frame is not None:
                row["latest"] = dict(frame)
    return rows


def devices_from_patient_history(
    history: Mapping[str, Iterable[Mapping[str, Any]]],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    frames: List[Mapping[str, Any]] = []
    for group in history.values():
        frames.extend(group)
    rows = compact_devices_from_frames(frames, now=now, include_latest=True)
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    return rows


def merge_device_lists(*lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for group in lists:
        for row in group:
            device_id = str(row.get("device_id") or "unknown")
            prev = by_id.get(device_id)
            incoming_seen = str(row.get("last_seen") or "")
            prev_seen = str((prev or {}).get("last_seen") or "")
            if prev is None:
                by_id[device_id] = dict(row)
            elif incoming_seen >= prev_seen:
                by_id[device_id] = carry_last_activity(prev, row)
            else:
                by_id[device_id] = carry_last_activity(row, prev)
    rows = list(by_id.values())
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    return rows
