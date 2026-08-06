"""
Security Headers Middleware para a API Saúde Responsiva.

Injeta cabeçalhos HTTP recomendados pela OWASP / LGPD para proteção contra ataques comuns
(XSS, Clickjacking, MIME Sniffing, HSTS).
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Injetar cabeçalhos de segurança padrão OWASP
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Content Security Policy flexível o suficiente para Dashboard estático + Chart.js e Google Fonts
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' wss: ws: http: https:;"
        )
        response.headers["Content-Security-Policy"] = csp

        return response
