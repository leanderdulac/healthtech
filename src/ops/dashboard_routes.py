"""Rotas públicas do painel ops (sem chave privilegiada no browser)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/ops", tags=["ops-dashboard"])

_PUBLIC_DEVICE_FIELDS = (
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
    "synthetic",
)


def _public_device_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in _PUBLIC_DEVICE_FIELDS if key in row}


def _refresh_remote_fleet() -> None:
    try:
        from src.ops.device_registry import merge_remote_rows
        from src.ops.live_watch_bridge import cached_devices

        merge_remote_rows(cached_devices())
    except Exception:
        return


@router.get("/dashboard-bootstrap")
def dashboard_bootstrap() -> Dict[str, Any]:
    """Config pública do painel. Nunca inclui chave de API."""
    return {
        "ok": True,
        "fleet_poll_ms": 2000,
        "page_size": 50,
        "max_devices": 500,
        "fleet_summary_path": "/api/v1/ops/fleet-summary",
        "auth_required_for": ["websocket", "ingest", "patient_history"],
    }


@router.get("/fleet-summary")
def fleet_summary(
    q: str = Query(default=""),
    online: Optional[bool] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10000),
    include_synthetic: bool = Query(
        default=False,
        description="Se true, inclui devices de smoke/probe/timecheck. Padrão: ocultos.",
    ),
) -> Dict[str, Any]:
    """Resumo somente-leitura da frota para o dashboard público.

    Expõe no máximo os campos compactos já mostrados na tabela (sem `latest`,
    sem histórico, sem chave). Devices sintéticos ficam de fora por padrão.
    """
    from src.ops.device_registry import list_devices as fleet_list

    _refresh_remote_fleet()
    payload = fleet_list(
        q=q,
        online=online,
        limit=limit,
        offset=offset,
        include_latest=False,
        include_synthetic=include_synthetic,
    )
    return {
        "ok": True,
        "public": True,
        "counts": payload.get("counts") or {},
        "limit": payload.get("limit"),
        "offset": payload.get("offset"),
        "coverage": payload.get("coverage"),
        "include_synthetic": bool(payload.get("include_synthetic")),
        "devices": [_public_device_row(row) for row in (payload.get("devices") or [])],
    }
