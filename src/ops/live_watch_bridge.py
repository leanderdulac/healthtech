"""Espelha relógios vivos da API segura no dashboard do monólito."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_state: Dict[str, Any] = {
    "cache": [],
    "last_seen": {},
}


def cached_devices() -> List[Dict[str, Any]]:
    return list(_state["cache"])


def fetch_secure_devices(timeout: float = 8.0) -> List[Dict[str, Any]]:
    base = (os.environ.get("SECURE_API_BASE_URL") or "").rstrip("/")
    key = (os.environ.get("SECURE_READ_API_KEY") or os.environ.get("SECURE_API_KEY") or "").strip()
    if not base or not key:
        return list(_state["cache"])
    req = urllib.request.Request(
        f"{base}/api/v1/wearables/devices?limit=500",
        headers={"X-API-Key": key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Falha ao listar relógios na API segura: %s", exc)
        return list(_state["cache"])
    devices = payload.get("devices") if isinstance(payload, dict) else None
    if not isinstance(devices, list):
        return list(_state["cache"])
    _state["cache"] = devices
    return devices


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
