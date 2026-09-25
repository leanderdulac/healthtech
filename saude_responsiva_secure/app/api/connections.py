"""Status de conexão app mobile e device (HBand)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security

from app.config import Settings, get_settings
from app.security.auth import api_key_header, get_key_scopes
from app.services import telemetry_store
from app.services.connection_status import build_connection_status, public_connection_view
from app.services.durable_readings import DurableStoreUnavailable

router = APIRouter(prefix="/api/v1/connections", tags=["connections"])


@router.get("/status")
def get_connection_status(
    request: Request,
    online_threshold_sec: int = Query(default=30, ge=5, le=600),
    stale_threshold_sec: int = Query(default=300, ge=30, le=3600),
    x_api_key: Optional[str] = Security(api_key_header),
    settings: Settings = Depends(get_settings),
):
    """
    Resumo das conexões app mobile → API e device (simulador BLE / HBand SDK).

    - Sem API key: visão pública (status + última amostra sem patient_id).
    - Com wearables:read: inclui sessões por paciente.
    """
    _ = request
    try:
        history = telemetry_store.iter_patients()
    except DurableStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Armazenamento durável de telemetria indisponível. ({exc})",
        ) from exc
    full = build_connection_status(
        history,
        online_threshold_sec=online_threshold_sec,
        stale_threshold_sec=stale_threshold_sec,
    )
    scopes = get_key_scopes(x_api_key, settings)
    if "wearables:read" in scopes or "admin" in scopes or settings.is_auth_disabled:
        full["public"] = False
        return full
    return public_connection_view(full)


@router.get("/public")
def get_connection_status_public(
    request: Request,
    online_threshold_sec: int = Query(default=30, ge=5, le=600),
    stale_threshold_sec: int = Query(default=300, ge=30, le=3600),
):
    """Alias explícito da visão pública (sem autenticação)."""
    _ = request
    try:
        history = telemetry_store.iter_patients()
    except DurableStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Armazenamento durável de telemetria indisponível. ({exc})",
        ) from exc
    full = build_connection_status(
        history,
        online_threshold_sec=online_threshold_sec,
        stale_threshold_sec=stale_threshold_sec,
    )
    return public_connection_view(full)
