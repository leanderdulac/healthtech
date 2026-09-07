"""Timestamps da frota: UTC canônico, exibição em America/Sao_Paulo."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")
ONLINE_WITHIN_SECONDS = 120.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any, default_tz: ZoneInfo = DISPLAY_TZ) -> Optional[datetime]:
    """Interpreta instante do relógio/app. Sem fuso → horário de Brasília."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=default_tz)
        return dt.astimezone(timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return parse_timestamp(int(raw), default_tz=default_tz)
    normalized = raw.replace("Z", "+00:00")
    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        dt = None
    if dt is None:
        for fmt, size in (
            ("%Y-%m-%d %H:%M:%S", 19),
            ("%Y-%m-%d %H:%M", 16),
            ("%d/%m/%Y %H:%M:%S", 19),
            ("%d/%m/%Y %H:%M", 16),
            ("%Y.%m.%d %H:%M:%S", 19),
            ("%Y-%m-%d", 10),
            ("%Y%m%d", 8),
        ):
            try:
                dt = datetime.strptime(raw[:size], fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_display(dt: datetime) -> str:
    return dt.astimezone(DISPLAY_TZ).strftime("%d/%m/%Y %H:%M:%S")


def stamp_ingest(device_ts: Any, received: Optional[datetime] = None) -> Dict[str, str]:
    """Normaliza o pacote: sample time do device + hora em que a plataforma recebeu."""
    received = received or now_utc()
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    received = received.astimezone(timezone.utc)
    sample = parse_timestamp(device_ts) or received
    return {
        "timestamp": utc_iso(sample),
        "received_at": utc_iso(received),
        "last_seen_local": local_display(received),
        "device_time_local": local_display(sample),
    }


def age_seconds(value: Any, now: Optional[datetime] = None) -> Optional[float]:
    dt = parse_timestamp(value)
    if dt is None:
        return None
    now = now or now_utc()
    age = (now - dt).total_seconds()
    if age < 0:
        return 0.0
    return age


def is_online(value: Any, now: Optional[datetime] = None, window: float = ONLINE_WITHIN_SECONDS) -> bool:
    age = age_seconds(value, now=now)
    return age is not None and age <= window
