"""Health / status probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models.schemas import HealthResponse, StatusResponse
from app.security.auth import require_scope
from app.services import telemetry_store

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
@router.get("/health", response_model=HealthResponse)
def health_probe(settings: Settings = Depends(get_settings)):
    """Probe público para orquestradores (Cloud Run / k8s)."""
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/api/status", response_model=StatusResponse)
def get_status(
    settings: Settings = Depends(get_settings),
    _api_key: str = Depends(require_scope("admin")),
):
    """Status interno (requer escopo admin)."""
    s = telemetry_store.stats()
    return StatusResponse(
        status="online",
        patients_tracked=s["patients_tracked"],
        history_entries=s["history_entries"],
        environment=settings.environment,
    )
