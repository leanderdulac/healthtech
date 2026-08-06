"""Armazenamento em memória de telemetria por paciente (processo local)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import get_settings

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
