"""Health / status probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.models.schemas import HealthResponse, StatusResponse
from app.security.auth import require_scope
from app.services import telemetry_store

router = APIRouter(tags=["health"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def root_landing(settings: Settings = Depends(get_settings)):
    """Página mínima para o browser em http://127.0.0.1:8080/ — a API não tem UI."""
    docs = "/docs" if not settings.is_production else "/api/health"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{settings.app_name}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:2rem}}
a{{color:#38bdf8}} code{{color:#f8fafc}}
</style></head><body>
<h1>{settings.app_name} v{settings.app_version}</h1>
<p>API no ar (modo <code>{settings.app_mode}</code>). Não há dashboard nesta URL.</p>
<ul>
<li><a href="/api/health">/api/health</a></li>
<li><a href="{docs}">{docs}</a></li>
</ul>
<p>App no emulador: use <code>http://10.0.2.2:8080</code> só no Android, não no Chrome do PC.</p>
</body></html>"""


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
