"""Frota que o painel mostra.

A API segura é onde o app da pulseira grava. Quando ela responde, o painel
mostra só esses relógios. A frota local antiga entra apenas se a ponte
não estiver configurada ou a consulta falhar sem cache.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.ops.device_registry import is_synthetic_device, list_devices
from src.ops.live_watch_bridge import fetch_secure_fleet
from src.ops.timestamps import age_seconds, is_online, local_display, now_utc, parse_timestamp, utc_iso


def _normalize(row: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    device_id = str(row.get("device_id") or "").strip()
    if not device_id:
        return None
    received = parse_timestamp(row.get("received_at"))
    sample = parse_timestamp(row.get("last_seen") or row.get("timestamp"))
    live = received or sample
    item: Dict[str, Any] = {
        "device_id": device_id,
        "patient_id": row.get("patient_id"),
        "last_seen": utc_iso(live) if live else row.get("last_seen"),
        "received_at": utc_iso(received or live) if (received or live) else None,
        "last_seen_local": row.get("last_seen_local") or (local_display(live) if live else None),
        "device_time_local": row.get("device_time_local") or (local_display(sample) if sample else None),
        "online": is_online(live, now=now) if live else False,
        "age_seconds": age_seconds(live, now=now) if live else None,
        "heart_rate": row.get("heart_rate"),
        "spo2": row.get("spo2"),
        "steps": row.get("steps"),
        "blood_pressure_sys": row.get("blood_pressure_sys"),
        "blood_pressure_dia": row.get("blood_pressure_dia"),
        "device_model": row.get("device_model"),
    }
    if is_synthetic_device(row) or is_synthetic_device(item):
        item["synthetic"] = True
    return item


def _page(
    rows: List[Dict[str, Any]],
    *,
    q: str,
    online: Optional[bool],
    limit: int,
    offset: int,
    include_synthetic: bool,
    patient_id: Optional[str],
    source: str,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    wanted = (patient_id or "").strip() or None
    if wanted:
        rows = [row for row in rows if str(row.get("patient_id") or "") == wanted]
    if not include_synthetic:
        rows = [row for row in rows if not is_synthetic_device(row)]
    needle = (q or "").strip().lower()
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
    total = len(rows)
    online_count = sum(1 for row in rows if row.get("online"))
    payload: Dict[str, Any] = {
        "counts": {
            "total": total,
            "online": online_count,
            "offline": max(0, total - online_count),
        },
        "limit": limit,
        "offset": offset,
        "devices": rows[offset : offset + limit],
        "coverage": "patient" if wanted else "fleet",
        "include_synthetic": bool(include_synthetic),
        "source": source,
    }
    if wanted:
        payload["patient_id"] = wanted
    return payload


def present_fleet(
    *,
    q: str = "",
    online: Optional[bool] = None,
    limit: int = 200,
    offset: int = 0,
    include_latest: bool = False,
    include_synthetic: bool = False,
    patient_id: Optional[str] = None,
) -> Dict[str, Any]:
    remote = fetch_secure_fleet()
    if remote is not None:
        now = now_utc()
        rows: List[Dict[str, Any]] = []
        for raw in remote:
            if not isinstance(raw, dict):
                continue
            item = _normalize(raw, now)
            if item is not None:
                rows.append(item)
        return _page(
            rows,
            q=q,
            online=online,
            limit=limit,
            offset=offset,
            include_synthetic=include_synthetic,
            patient_id=patient_id,
            source="secure-api",
        )
    payload = list_devices(
        q=q,
        online=online,
        limit=limit,
        offset=offset,
        include_latest=include_latest,
        patient_id=patient_id,
        include_synthetic=include_synthetic,
    )
    payload["source"] = "local"
    return payload
