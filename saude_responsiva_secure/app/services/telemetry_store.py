"""Armazenamento em memória de telemetria por paciente (processo local)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings

ONLINE_WITHIN_SECONDS = 120.0

# patient_id -> lista de frames processados
_patient_history: Dict[str, List[Dict[str, Any]]] = {}


def append_reading(patient_id: str, frame: Dict[str, Any]) -> None:
    settings = get_settings()
    if patient_id not in _patient_history:
        _patient_history[patient_id] = []
    _patient_history[patient_id].append(frame)
    max_n = settings.history_max_per_patient
    if len(_patient_history[patient_id]) > max_n:
        _patient_history[patient_id] = _patient_history[patient_id][-max_n:]


def get_latest(patient_id: str) -> Optional[Dict[str, Any]]:
    hist = _patient_history.get(patient_id)
    if not hist:
        return None
    return hist[-1]


def get_history(patient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    hist = _patient_history.get(patient_id) or []
    return hist[-limit:]


def list_devices() -> List[Dict[str, Any]]:
    """Última leitura por device_id (relógios no processo)."""
    now = datetime.now(timezone.utc)
    latest_by_device: Dict[str, Dict[str, Any]] = {}
    for hist in _patient_history.values():
        for frame in hist:
            device_id = str(frame.get("device_id") or "unknown")
            ts = str(frame.get("timestamp") or "")
            prev = latest_by_device.get(device_id)
            if prev is None or ts >= str(prev.get("timestamp") or ""):
                latest_by_device[device_id] = frame
    rows: List[Dict[str, Any]] = []
    for frame in latest_by_device.values():
        ts = frame.get("timestamp")
        online = False
        if isinstance(ts, str) and ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (now - dt).total_seconds()
                online = 0 <= age <= ONLINE_WITHIN_SECONDS
            except ValueError:
                online = False
        cleaned = frame.get("cleaned_telemetry") or {}
        raw = frame.get("raw_telemetry") or {}
        rows.append({
            "device_id": frame.get("device_id") or "unknown",
            "patient_id": frame.get("patient_id"),
            "last_seen": ts,
            "online": online,
            "heart_rate": cleaned.get("heart_rate_clean", raw.get("heart_rate_bpm")),
            "spo2": raw.get("spo2_percent"),
            "latest": frame,
        })
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    return rows


def anonymize_patient(patient_id: str) -> bool:
    """Remove histórico do paciente (LGPD). Retorna True se havia dados."""
    had = patient_id in _patient_history
    _patient_history.pop(patient_id, None)
    return had


def stats() -> Dict[str, int]:
    return {
        "patients_tracked": len(_patient_history),
        "history_entries": sum(len(v) for v in _patient_history.values()),
    }


def clear_all() -> None:
    """Utilitário de teste."""
    _patient_history.clear()
