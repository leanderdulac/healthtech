"""
App factory — Saúde Responsiva Secure API.

Middlewares: Security Headers → Rate Limit → Audit → CORS
Exception handlers: HTTP + genérico (sem vazar stack em produção).

Modos (APP_MODE):
  - secure (default): rotas enxutas (wearables/signal/admin/LGPD)
  - full: monólito completo (dashboard + WebSocket + phantom/Vertex)
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, health, lgpd, signal, wearables
from app.config import get_settings
from app.security.auth import validate_api_keys_on_startup, validate_secret_salt
from app.security.headers import SecurityHeadersMiddleware
from app.security.rate_limit import PathRateLimitMiddleware, limiter
from app.services.audit import AuditLoggingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _ensure_project_root_on_path() -> None:
    """Garante que o monólito (`src.*`) seja importável no modo full."""
    # .../saude_responsiva_secure/app/main.py → project root = parents[2]
    secure_root = Path(__file__).resolve().parents[1]
    project_root = secure_root.parent
    for candidate in (project_root, secure_root):
        s = str(candidate)
        if s not in sys.path:
            sys.path.insert(0, s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_secret_salt(settings)
    validate_api_keys_on_startup(settings)
    logger.info(
        "Iniciando %s v%s (env=%s mode=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment,
        settings.app_mode,
    )
    yield
    logger.info("Encerrando aplicação.")


def _create_secure_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        description=(
            "API biomédica endurecida: API Keys por escopo, rate limit, "
            "security headers, auditoria LGPD e autorização por paciente (anti-IDOR)."
        ),
        version=settings.app_version,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        lifespan=lifespan,
    )

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Ordem: último add_middleware = primeiro a processar a request de entrada
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(PathRateLimitMiddleware)
    application.add_middleware(AuditLoggingMiddleware)

    origins = settings.get_cors_origins()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["http://localhost:8080"],
        allow_credentials=bool(origins) and origins != ["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*", "X-API-Key", "X-Request-ID"],
    )

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        req_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "error_code": f"HTTP_{exc.status_code}",
                "request_id": req_id,
            },
            headers=getattr(exc, "headers", None) or {},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        req_id = getattr(request.state, "request_id", None)
        safe_errors = []
        for err in exc.errors():
            item = {k: v for k, v in err.items() if k != "ctx"}
            if "ctx" in err and err["ctx"] is not None:
                item["ctx"] = {
                    ck: (
                        str(cv)
                        if not isinstance(cv, (str, int, float, bool, type(None)))
                        else cv
                    )
                    for ck, cv in err["ctx"].items()
                }
            safe_errors.append(item)
        return JSONResponse(
            status_code=422,
            content={
                "detail": safe_errors,
                "error_code": "VALIDATION_ERROR",
                "request_id": req_id,
            },
        )

    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Exceção não tratada [Request-ID: %s]: %s",
            req_id,
            exc,
            exc_info=not settings.is_production,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Ocorreu um erro interno no processamento da solicitação.",
                "error_code": "INTERNAL_SERVER_ERROR",
                "request_id": req_id,
            },
        )

    application.include_router(health.router)
    application.include_router(wearables.router)
    application.include_router(signal.router)
    application.include_router(admin.router)
    application.include_router(lgpd.router)

    return application


def _create_full_app() -> FastAPI:
    """Delega ao monólito (dashboard + WS + phantom/Vertex) com middlewares secure."""
    _ensure_project_root_on_path()
    try:
        from src.api_monolith_runtime import build_monolith_app
    except ImportError as exc:
        logger.error(
            "APP_MODE=full requer o monólito (src.api_monolith_runtime). "
            "Erro: %s. Caindo para modo secure.",
            exc,
        )
        return _create_secure_app()

    application = build_monolith_app()
    application.state.limiter = getattr(application.state, "limiter", None) or limiter
    logger.info("App monólito full carregada via factory secure.")
    return application


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.is_full_mode:
        return _create_full_app()
    return _create_secure_app()


app = create_app()
