"""Registro de frota de relógios (centenas de devices / apps).

Estado em memória com persistência opcional em GCS para sobreviver a
novas instâncias do Cloud Run. O payload de listagem é compacto — o
frame completo só entra no detalhe de um device.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.ops.live_devices import summarize_frame
from src.ops.timestamps import is_online, parse_timestamp

logger = logging.getLogger(__name__)

MAX_DEVICES = 5000
FLUSH_EVERY_SECONDS = 2.0
LOCAL_FLEET_PATH = Path("data/ops/fleet_devices.json")
GCS_OBJECT = "ops/fleet/devices.json"

_lock = threading.Lock()
_devices: Dict[str, Dict[str, Any]] = {}
_dirty = False
_last_flush = 0.0
_loaded = False
_last_load = 0.0
RELOAD_EVERY_SECONDS = 4.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _compact(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "device_id": summary.get("device_id") or "unknown",
        "patient_id": summary.get("patient_id"),
        "last_seen": summary.get("last_seen"),
        "received_at": summary.get("received_at"),
        "last_seen_local": summary.get("last_seen_local"),
        "device_time_local": summary.get("device_time_local"),
        "online": bool(summary.get("online")),
        "age_seconds": summary.get("age_seconds"),
        "heart_rate": summary.get("heart_rate"),
        "spo2": summary.get("spo2"),
    }


def _refresh_online(row: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    live_ref = row.get("received_at") or row.get("last_seen")
    out = dict(row)
    out["online"] = is_online(live_ref, now=now)
    return out


def _gcs_parts() -> Tuple[Optional[str], str]:
    raw = (os.environ.get("GCS_STAGING_BUCKET") or "").strip()
    if not raw:
        return None, GCS_OBJECT
    path = raw[5:] if raw.startswith("gs://") else raw
    bucket = path.split("/", 1)[0]
    return bucket or None, GCS_OBJECT


def _load_unlocked(force: bool = False) -> None:
    global _loaded, _last_load
    now = time.time()
    if _loaded and not force and now - _last_load < RELOAD_EVERY_SECONDS:
        return
    payload = None
    bucket_name, object_name = _gcs_parts()
    if bucket_name:
        try:
            from google.cloud import storage  # type: ignore

            client = storage.Client()
            blob = client.bucket(bucket_name).blob(object_name)
            if blob.exists():
                payload = json.loads(blob.download_as_text())
        except Exception as exc:
            logger.warning("Não foi possível ler a frota no GCS: %s", exc)
    if payload is None and LOCAL_FLEET_PATH.exists():
        try:
            payload = json.loads(LOCAL_FLEET_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Não foi possível ler a frota local: %s", exc)
            payload = None
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("devices") or []
    elif isinstance(payload, list):
        rows = payload
    for row in rows:
        if not isinstance(row, dict):
            continue
        device_id = str(row.get("device_id") or "")
        if not device_id:
            continue
        prev = _devices.get(device_id)
        if prev is None or str(row.get("last_seen") or "") >= str(prev.get("last_seen") or ""):
            if prev and prev.get("latest") and not row.get("latest"):
                row = dict(row)
                row["latest"] = prev["latest"]
            _devices[device_id] = row
    _loaded = True
    _last_load = now


def _evict_unlocked() -> None:
    extra = len(_devices) - MAX_DEVICES
    if extra <= 0:
        return
    ordered = sorted(
        _devices.items(),
        key=lambda item: str(item[1].get("last_seen") or ""),
    )
    for device_id, _row in ordered[: extra + max(1, MAX_DEVICES // 20)]:
        _devices.pop(device_id, None)


def _flush_unlocked(force: bool = False) -> None:
    global _dirty, _last_flush
    if not _dirty and not force:
        return
    now = time.time()
    if not force and now - _last_flush < FLUSH_EVERY_SECONDS:
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        _dirty = False
        _last_flush = time.time()
        return
    snapshot = {
        "updated_at": _now().isoformat(),
        "count": len(_devices),
        "devices": [_compact(row) for row in _devices.values()],
    }
    text = json.dumps(snapshot, ensure_ascii=False)
    LOCAL_FLEET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOCAL_FLEET_PATH.write_text(text + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Falha ao gravar frota local: %s", exc)
    bucket_name, object_name = _gcs_parts()
    if bucket_name:
        try:
            from google.cloud import storage  # type: ignore

            client = storage.Client()
            blob = client.bucket(bucket_name).blob(object_name)
            blob.upload_from_string(text, content_type="application/json")
        except Exception as exc:
            logger.warning("Falha ao gravar frota no GCS: %s", exc)
    _dirty = False
    _last_flush = now


def upsert_frame(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Atualiza a frota com um frame de ingestão. Retorna a linha compacta."""
    summary = summarize_frame(frame)
    compact = _compact(summary)
    compact["latest"] = dict(frame)
    device_id = compact["device_id"]
    with _lock:
        _load_unlocked()
        prev = _devices.get(device_id) or {}
        prev_rx = parse_timestamp(prev.get("received_at") or prev.get("last_seen"))
        new_rx = parse_timestamp(compact.get("received_at") or compact.get("last_seen"))
        if prev_rx and new_rx and new_rx < prev_rx:
            return _compact(_refresh_online(prev))
        _devices[device_id] = compact
        _evict_unlocked()
        global _dirty
        _dirty = True
        _flush_unlocked()
    return _compact(compact)


def list_devices(
    q: str = "",
    online: Optional[bool] = None,
    limit: int = 200,
    offset: int = 0,
    include_latest: bool = False,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    needle = (q or "").strip().lower()
    with _lock:
        _load_unlocked()
        now = _now()
        rows = [_refresh_online(row, now=now) for row in _devices.values()]
        _flush_unlocked()
    if needle:
        rows = [
            row
            for row in rows
            if needle in str(row.get("device_id") or "").lower()
            or needle in str(row.get("patient_id") or "").lower()
        ]
    if online is True:
        rows = [row for row in rows if row.get("online")]
    elif online is False:
        rows = [row for row in rows if not row.get("online")]
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    rows.sort(key=lambda row: 0 if row.get("online") else 1)
    online_count = sum(1 for row in rows if row.get("online"))
    total = len(rows)
    page = rows[offset : offset + limit]
    out_rows = []
    for row in page:
        item = _compact(row)
        if include_latest and row.get("latest"):
            item["latest"] = row["latest"]
        out_rows.append(item)
    return {
        "counts": {"total": total, "online": online_count, "offline": max(0, total - online_count)},
        "limit": limit,
        "offset": offset,
        "devices": out_rows,
    }


def get_device(device_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        _load_unlocked()
        row = _devices.get(device_id)
        if not row:
            return None
        row = _refresh_online(row)
        item = _compact(row)
        if row.get("latest"):
            item["latest"] = row["latest"]
        return item


def merge_remote_rows(rows: List[Dict[str, Any]]) -> None:
    """Incorpora linhas vindas da API segura / outro processo."""
    if not rows:
        return
    with _lock:
        _load_unlocked()
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            device_id = str(row.get("device_id") or "")
            if not device_id:
                continue
            incoming = dict(row)
            prev = _devices.get(device_id)
            incoming_rx = parse_timestamp(incoming.get("received_at") or incoming.get("last_seen"))
            prev_rx = parse_timestamp(prev.get("received_at") or prev.get("last_seen")) if prev else None
            if prev is None or incoming_rx is None or prev_rx is None or incoming_rx >= prev_rx:
                if prev and prev.get("latest") and not incoming.get("latest"):
                    incoming["latest"] = prev["latest"]
                _devices[device_id] = incoming
                changed = True
        if changed:
            global _dirty
            _dirty = True
            _evict_unlocked()
            _flush_unlocked()


def clear_all() -> None:
    with _lock:
        _devices.clear()
        global _dirty, _loaded
        _dirty = False
        _loaded = True
