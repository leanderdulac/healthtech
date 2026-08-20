"""
Security Headers Middleware para a API Saúde Responsiva.

Injeta cabeçalhos HTTP recomendados pela OWASP / LGPD para proteção contra ataques comuns
(XSS, Clickjacking, MIME Sniffing, HSTS).

CSP é path-aware: dashboard/docs recebem política compatível com Chart.js e Google Fonts;
rotas de API JSON usam política restritiva.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# API JSON — sem scripts de terceiros
CSP_API = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

# Dashboard estático + Chart.js + Google Fonts + WebSocket
CSP_DASHBOARD = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self' wss: ws: http: https:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _csp_for_path(path: str) -> str:
    if path.startswith("/dashboard") or path in {"/", "/favicon.ico"}:
        return CSP_DASHBOARD
    if path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json":
        return CSP_DOCS
    return CSP_API


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Injetar cabeçalhos de segurança padrão OWASP
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = _csp_for_path(request.url.path)

        return response
