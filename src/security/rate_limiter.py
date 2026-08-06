"""
Rate Limiter em memória para a API Saúde Responsiva.

Limita o número de requisições por chave de API ou por IP utilizando Janela Deslizante (Sliding Window).
Injeta headers HTTP padrão (X-RateLimit-Limit, X-RateLimit-Remaining) e retorna 429 Too Many Requests.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Configurações padrão de limites (requisições por minuto)
RATE_LIMITS = {
    "/api/v1/wearables/ingest": 60,
    "/api/v1/wearables/batch-ingest": 30,
    "/api/v1/wearables/patient": 60,
    "/api/v1/admin": 10,
    "default": 120,
}


class SlidingWindowRateLimiter:
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        # Estrutura: key -> List[timestamp]
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def _get_limit_for_path(self, path: str) -> int:
        for route_prefix, limit in RATE_LIMITS.items():
            if route_prefix != "default" and path.startswith(route_prefix):
                return limit
        return RATE_LIMITS["default"]

    def is_rate_limited(self, identifier: str, path: str) -> Tuple[bool, int, int, int]:
        """
        Retorna: (is_limited, limit, remaining, retry_after)
        """
        now = time.time()
        cutoff = now - self.window_seconds
        limit = self._get_limit_for_path(path)

        # Limpar timestamps antigos fora da janela
        timestamps = self._requests[identifier]
        valid_timestamps = [t for t in timestamps if t > cutoff]
        self._requests[identifier] = valid_timestamps

        current_count = len(valid_timestamps)
        if current_count >= limit:
            oldest_timestamp = valid_timestamps[0] if valid_timestamps else now
            retry_after = int(self.window_seconds - (now - oldest_timestamp)) + 1
            return True, limit, 0, max(1, retry_after)

        # Registrar a nova requisição
        self._requests[identifier].append(now)
        remaining = limit - (current_count + 1)
        return False, limit, remaining, 0


# Instância global do Rate Limiter
_limiter_instance = SlidingWindowRateLimiter(window_seconds=60)


class RateLimitingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Isentar static files e health check de rate limiting estrito
        path = request.url.path
        if path.startswith("/dashboard") or path in {"/api/health", "/favicon.ico"}:
            return await call_next(request)

        # Identificador: API Key (se presente) ou IP do cliente
        api_key = request.headers.get("X-API-Key")
        client_ip = request.client.host if request.client else "127.0.0.1"
        identifier = api_key or client_ip

        is_limited, limit, remaining, retry_after = _limiter_instance.is_rate_limited(
            identifier=identifier, path=path
        )

        if is_limited:
            logger.warning(
                f"Rate limit excedido para '{identifier}' no path '{path}'. Limite: {limit}/min"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Limite de requisições excedido. Por favor, aguarde antes de tentar novamente.",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
