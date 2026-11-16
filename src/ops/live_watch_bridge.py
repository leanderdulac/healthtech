"""Espelha relógios vivos da API segura no dashboard do monólito."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Evita estouro de GET /devices quando o painel e a ponte pedem a frota ao mesmo tempo.
CACHE_TTL_SECONDS = 2.0

_state: Dict[str, Any] = {
    "cache": [],
    "last_seen": {},
    "cached_at": 0.0,
    "cache_valid": False,
    "inflight": None,
}
_lock = threading.Lock()


def cached_devices() -> List[Dict[str, Any]]:
    return list(_state["cache"])


def reset_bridge_state() -> None:
    """Utilitário de teste — zera cache e voo único."""
    with _lock:
        inflight = _state.get("inflight")
        _state["cache"] = []
        _state["last_seen"] = {}
        _state["cached_at"] = 0.0
        _state["cache_valid"] = False
        _state["inflight"] = None
        if inflight is not None:
            inflight.set()


def _bridge_config() -> Tuple[str, str]:
    base = (os.environ.get("SECURE_API_BASE_URL") or "").rstrip("/")
    key = (
        os.environ.get("SECURE_READ_API_KEY")
        or os.environ.get("SECURE_API_KEY")
        or os.environ.get("READ_API_KEY")
        or ""
    ).strip()
    return base, key


def fetch_secure_fleet(timeout: float = 8.0) -> Optional[List[Dict[str, Any]]]:
    """Lista ao vivo da API segura.

    None quando a ponte não está configurada ou a consulta falhou sem cache.
    Lista vazia é uma resposta real: não há relógio na API segura.
    """
    base, key = _bridge_config()
    if not base or not key:
        return None
    with _lock:
        now = time.monotonic()
        if _state.get("cache_valid") and (now - float(_state.get("cached_at") or 0)) < CACHE_TTL_SECONDS:
            return list(_state["cache"])
        inflight = _state.get("inflight")
        if inflight is not None:
            waiter = inflight
            owner = False
        else:
            waiter = threading.Event()
            _state["inflight"] = waiter
            owner = True
    if not owner:
        waiter.wait(timeout=max(0.1, float(timeout) + 1.0))
        with _lock:
            if _state.get("cache_valid"):
                return list(_state["cache"])
            cached = list(_state["cache"])
            return cached if cached else None
    req = urllib.request.Request(
        f"{base}/api/v1/wearables/devices?limit=500&include_synthetic=true",
        headers={"X-API-Key": key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, list):
            with _lock:
                cached = list(_state["cache"])
                return cached if cached else None
        with _lock:
            _state["cache"] = devices
            _state["cached_at"] = time.monotonic()
            _state["cache_valid"] = True
        return devices
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Falha ao listar relógios na API segura: %s", exc)
        with _lock:
            cached = list(_state["cache"])
            return cached if cached else None
    finally:
        with _lock:
            if _state.get("inflight") is waiter:
                _state["inflight"] = None
            waiter.set()


def fetch_secure_devices(timeout: float = 8.0) -> List[Dict[str, Any]]:
    rows = fetch_secure_fleet(timeout=timeout)
    if rows is None:
        return list(_state["cache"])
    return rows


def new_ingest_frames(devices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    last_seen: Dict[str, str] = _state["last_seen"]
    for row in devices:
        device_id = str(row.get("device_id") or "")
        ts = str(row.get("received_at") or row.get("last_seen") or "")
        latest = row.get("latest")
        if not isinstance(latest, dict):
            latest = {
                "device_id": device_id,
                "patient_id": row.get("patient_id"),
                "timestamp": row.get("last_seen") or ts,
                "received_at": row.get("received_at") or ts,
                "last_seen_local": row.get("last_seen_local"),
                "device_time_local": row.get("device_time_local"),
                "raw_telemetry": {
                    "heart_rate_bpm": row.get("heart_rate"),
                    "spo2_percent": row.get("spo2"),
                    "steps": row.get("steps"),
                    "blood_pressure_sys": row.get("blood_pressure_sys"),
                    "blood_pressure_dia": row.get("blood_pressure_dia"),
                    "device_model": row.get("device_model"),
                },
                "cleaned_telemetry": {"heart_rate_clean": row.get("heart_rate")},
            }
        else:
            latest.setdefault("received_at", row.get("received_at") or ts)
            latest.setdefault("last_seen_local", row.get("last_seen_local"))
        if not device_id:
            continue
        if last_seen.get(device_id) == ts:
            continue
        last_seen[device_id] = ts
        out.append(latest)
    return out


def poll_once() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    devices = fetch_secure_devices()
    return devices, new_ingest_frames(devices)
