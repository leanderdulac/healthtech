"""Security Headers middleware (OWASP / LGPD).

CSP é path-aware:
- Rotas de API JSON usam política restritiva (`default-src 'none'`).
- Dashboard estático, Swagger e raiz usam política que permite CSS/JS/fonts/CDN.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# API JSON / endpoints de dados — sem scripts de terceiros
CSP_API = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

# Dashboard glassmórfico + Chart.js + Google Fonts + WebSocket
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

# Swagger UI / ReDoc (quando docs_url está habilitado em não-produção)
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
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Content-Security-Policy"] = _csp_for_path(request.url.path)

        # Não vazar stack / tech
        if "Server" in response.headers:
            del response.headers["Server"]

        return response
