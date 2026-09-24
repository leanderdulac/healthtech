"""Armazenamento em memória de telemetria por paciente (processo local)."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.config import get_settings

ONLINE_WITHIN_SECONDS = 120.0
_SYNTHETIC_TOKENS = ("smoke", "probe", "timecheck")
_MAX_REQUEST_CACHE = 2048

_lock = threading.Lock()

# patient_id -> lista de frames processados
_patient_history: Dict[str, List[Dict[str, Any]]] = {}
# dedup_key -> (patient_id, reading_id)
_dedup_index: Dict[str, Tuple[str, str]] = {}
# Idempotency-Key da request HTTP -> resposta já produzida
_request_cache: Dict[str, Any] = {}
_request_cache_order: List[str] = []


def _is_synthetic_fallback(row: Dict[str, Any]) -> bool:
    flag = row.get("synthetic")
    if flag is True:
        return True
    device_id = str(row.get("device_id") or "").lower()
    patient_id = str(row.get("patient_id") or "").lower()
    if patient_id.startswith("smoke-"):
        return True
    haystack = f"{device_id} {patient_id}"
    return any(token in haystack for token in _SYNTHETIC_TOKENS)


def _lookup_unlocked(dedup_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not dedup_key:
        return None
    loc = _dedup_index.get(dedup_key)
    if not loc:
        return None
    patient_id, reading_id = loc
    for frame in _patient_history.get(patient_id, []):
        if frame.get("reading_id") == reading_id:
            return frame
    _dedup_index.pop(dedup_key, None)
    return None


def _drop_index_for_frames(patient_id: str, frames: List[Dict[str, Any]]) -> None:
    dropped_ids = {frame.get("reading_id") for frame in frames if frame.get("reading_id")}
    if not dropped_ids:
        return
    stale = [
        key
        for key, (pid, rid) in _dedup_index.items()
        if pid == patient_id and rid in dropped_ids
    ]
    for key in stale:
        _dedup_index.pop(key, None)


def _as_key_list(dedup_key: Optional[str] = None, dedup_keys: Optional[List[str]] = None) -> List[str]:
    keys: List[str] = []
    if dedup_keys:
        keys.extend(k for k in dedup_keys if k)
    if dedup_key:
        keys.append(dedup_key)
    seen = set()
    unique: List[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def find_duplicate(
    dedup_key: Optional[str] = None,
    dedup_keys: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Retorna o frame já persistido para qualquer chave informada."""
    with _lock:
        for key in _as_key_list(dedup_key, dedup_keys):
            found = _lookup_unlocked(key)
            if found is not None:
                return dict(found)
        return None


def upsert_reading(
    patient_id: str,
    frame: Dict[str, Any],
    dedup_key: Optional[str] = None,
    dedup_keys: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Persiste a leitura se nenhuma das chaves ainda existir.

    Retorna ``(frame, "accepted"|"duplicate")``. Duplicate devolve o frame
    original (first write wins) sem acrescentar histórico.
    """
    settings = get_settings()
    keys = _as_key_list(dedup_key, dedup_keys)
    stored: Dict[str, Any]
    with _lock:
        for key in keys:
            existing = _lookup_unlocked(key)
            if existing is not None:
                return dict(existing), "duplicate"
        stored = dict(frame)
        stored.setdefault("reading_id", uuid4().hex)
        if patient_id not in _patient_history:
            _patient_history[patient_id] = []
        _patient_history[patient_id].append(stored)
        max_n = settings.history_max_per_patient
        hist = _patient_history[patient_id]
        if len(hist) > max_n:
            dropped = hist[:-max_n]
            _patient_history[patient_id] = hist[-max_n:]
            _drop_index_for_frames(patient_id, dropped)
        reading_id = str(stored["reading_id"])
        for key in keys:
            _dedup_index[key] = (patient_id, reading_id)
    try:
        from src.ops.device_registry import upsert_frame

        upsert_frame(stored)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Falha ao registrar relógio na frota: %s", exc)
    return dict(stored), "accepted"


def append_reading(
    patient_id: str,
    frame: Dict[str, Any],
    dedup_key: Optional[str] = None,
    dedup_keys: Optional[List[str]] = None,
) -> None:
    """Compat: sempre tenta persistir (com dedup se houver chave)."""
    upsert_reading(patient_id, frame, dedup_key=dedup_key, dedup_keys=dedup_keys)


def get_cached_response(cache_key: Optional[str]) -> Optional[Any]:
    if not cache_key:
        return None
    with _lock:
        cached = _request_cache.get(cache_key)
        return cached if cached is None else _clone_cached(cached)


def put_cached_response(cache_key: Optional[str], response: Any) -> None:
    if not cache_key:
        return
    with _lock:
        if cache_key not in _request_cache:
            _request_cache_order.append(cache_key)
        _request_cache[cache_key] = _clone_cached(response)
        while len(_request_cache_order) > _MAX_REQUEST_CACHE:
            old = _request_cache_order.pop(0)
            _request_cache.pop(old, None)


def _clone_cached(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clone_cached(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_cached(item) for item in value]
    return value


def get_latest(patient_id: str) -> Optional[Dict[str, Any]]:
    hist = _patient_history.get(patient_id)
    if not hist:
        return None
    return hist[-1]


def get_history(patient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    hist = _patient_history.get(patient_id) or []
    return hist[-limit:]


def list_devices(
    q: str = "",
    online: Optional[bool] = None,
    limit: int = 200,
    offset: int = 0,
    include_latest: bool = False,
    patient_id: Optional[str] = None,
    include_synthetic: bool = False,
) -> Dict[str, Any]:
    """Última leitura por device_id (frota, payload compacto)."""
    try:
        from src.ops.device_registry import list_devices as fleet_list

        return fleet_list(
            q=q,
            online=online,
            limit=limit,
            offset=offset,
            include_latest=include_latest,
            patient_id=patient_id,
            include_synthetic=include_synthetic,
        )
    except Exception:
        pass
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
        is_online = False
        if isinstance(ts, str) and ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (now - dt).total_seconds()
                is_online = 0 <= age <= ONLINE_WITHIN_SECONDS
            except ValueError:
                is_online = False
        cleaned = frame.get("cleaned_telemetry") or {}
        raw = frame.get("raw_telemetry") or {}
        row = {
            "device_id": frame.get("device_id") or "unknown",
            "patient_id": frame.get("patient_id"),
            "last_seen": ts,
            "online": is_online,
            "heart_rate": cleaned.get("heart_rate_clean", raw.get("heart_rate_bpm")),
            "spo2": raw.get("spo2_percent"),
        }
        if include_latest:
            row["latest"] = frame
        rows.append(row)
    wanted_patient = (patient_id or "").strip() or None
    if wanted_patient:
        rows = [row for row in rows if str(row.get("patient_id") or "") == wanted_patient]
    if not include_synthetic:
        rows = [row for row in rows if not _is_synthetic_fallback(row)]
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    rows.sort(key=lambda row: 0 if row.get("online") else 1)
    if online is True:
        rows = [row for row in rows if row.get("online")]
    elif online is False:
        rows = [row for row in rows if not row.get("online")]
    needle = (q or "").strip().lower()
    if needle:
        rows = [
            row
            for row in rows
            if needle in str(row.get("device_id") or "").lower()
            or needle in str(row.get("patient_id") or "").lower()
        ]
    total = len(rows)
    online_count = sum(1 for row in rows if row.get("online"))
    page = rows[max(0, offset) : max(0, offset) + max(1, min(limit, 500))]
    payload: Dict[str, Any] = {
        "counts": {"total": total, "online": online_count, "offline": max(0, total - online_count)},
        "limit": limit,
        "offset": offset,
        "devices": page,
        "coverage": "patient" if wanted_patient else "fleet",
        "include_synthetic": bool(include_synthetic),
    }
    if wanted_patient:
        payload["patient_id"] = wanted_patient
    return payload


def anonymize_patient(patient_id: str) -> bool:
    """Remove histórico do paciente (LGPD). Retorna True se havia dados."""
    with _lock:
        had = patient_id in _patient_history
        _patient_history.pop(patient_id, None)
        for key, (pid, _rid) in list(_dedup_index.items()):
            if pid == patient_id:
                _dedup_index.pop(key, None)
        stale_cache = [key for key in _request_cache if f":{patient_id}:" in key]
        for key in stale_cache:
            _request_cache.pop(key, None)
            if key in _request_cache_order:
                _request_cache_order.remove(key)
        return had


def stats() -> Dict[str, int]:
    return {
        "patients_tracked": len(_patient_history),
        "history_entries": sum(len(v) for v in _patient_history.values()),
    }


def iter_patients() -> Dict[str, List[Dict[str, Any]]]:
    """Snapshot superficial do histórico em memória (somente leitura)."""
    return _patient_history


def clear_all() -> None:
    """Utilitário de teste."""
    with _lock:
        _patient_history.clear()
        _dedup_index.clear()
        _request_cache.clear()
        _request_cache_order.clear()
    try:
        from src.ops.device_registry import clear_all as clear_fleet

        clear_fleet()
    except Exception:
        pass
