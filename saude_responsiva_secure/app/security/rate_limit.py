"""Rate limiting com slowapi (Limiter + storage limits) e middleware por path."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List, Tuple

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings


def _rate_limit_key(request: Request) -> str:
    """Identifica cliente por X-API-Key (preferido) ou IP remoto."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key[:16]}"
    return get_remote_address(request)


# Limiter slowapi (exception handler / app.state.limiter)
limiter = Limiter(key_func=_rate_limit_key, default_limits=["120/minute"])


def _parse_limit(limit_str: str) -> Tuple[int, int]:
    """Retorna (max_requests, window_seconds)."""
    try:
        count_s, unit = limit_str.split("/", 1)
        max_requests = int(count_s)
        unit = unit.strip().lower()
        if "second" in unit:
            return max_requests, 1
        if "hour" in unit:
            return max_requests, 3600
        return max_requests, 60
    except Exception:
        return 120, 60


def _limit_for_path(path: str) -> str:
    settings = get_settings()
    if path.startswith("/api/v1/wearables/batch-ingest"):
        return settings.rate_limit_batch
    if path.startswith("/api/v1/wearables/ingest"):
        return settings.rate_limit_ingest
    if path.startswith("/api/v1/admin") or path.startswith("/api/reindex"):
        return settings.rate_limit_admin
    return settings.rate_limit_default


class SlidingWindowCounter:
    """Janela deslizante em memória (por processo)."""

    def __init__(self) -> None:
        self._hits: Dict[str, List[float]] = defaultdict(list)

    def hit(self, key: str, limit: int, window: int) -> Tuple[bool, int, int]:
        """
        Registra hit.
        Retorna (allowed, remaining, retry_after_seconds).
        """
        now = time.time()
        cutoff = now - window
        stamps = [t for t in self._hits[key] if t > cutoff]
        self._hits[key] = stamps
        if len(stamps) >= limit:
            oldest = stamps[0] if stamps else now
            retry = int(window - (now - oldest)) + 1
            return False, 0, max(1, retry)
        self._hits[key].append(now)
        remaining = limit - len(self._hits[key])
        return True, remaining, 0


_counter = SlidingWindowCounter()


class PathRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limit por path/chave usando janela deslizante.
    Expõe o Limiter do slowapi em app.state.limiter para o handler 429 padrão.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in {"/api/health", "/health", "/favicon.ico"} or path.startswith(
            "/docs"
        ) or path.startswith("/redoc") or path.startswith("/openapi"):
            return await call_next(request)

        limit_str = _limit_for_path(path)
        max_requests, window = _parse_limit(limit_str)
        key = f"{_rate_limit_key(request)}:{path}"
        allowed, remaining, retry_after = _counter.hit(key, max_requests, window)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Limite de requisições excedido. "
                        "Por favor, aguarde antes de tentar novamente."
                    ),
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
