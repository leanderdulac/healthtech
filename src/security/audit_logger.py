"""
Audit Logger para Conformidade LGPD e Segurança de Dados de Saúde.

Registra todas as requisições à API em formato estruturado (JSON), capturando:
- Timestamp UTC
- Request ID único (UUID4)
- API Key ID mascarada (nunca grava a chave em texto claro)
- IP de origem e User-Agent
- Método HTTP e Path
- ID do Paciente (se aplicável)
- Código de status HTTP e tempo de resposta (ms)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.security.auth import mask_api_key

audit_logger = logging.getLogger("healthtech.audit")
audit_logger.setLevel(logging.INFO)


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start_time = time.time()

        api_key = request.headers.get("X-API-Key")
        masked_key = mask_api_key(api_key)
        client_ip = request.client.host if request.client else "127.0.0.1"

        response: Response = await call_next(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id

        # Extrair patient_id se presente na URL
        path = request.url.path
        patient_id: Optional[str] = None
        if "/patient/" in path:
            parts = path.split("/")
            try:
                idx = parts.index("patient")
                if idx + 1 < len(parts):
                    patient_id = parts[idx + 1]
            except ValueError:
                pass

        log_record = {
            "event": "api_access_audit",
            "request_id": request_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "client_ip": client_ip,
            "masked_api_key": masked_key,
            "method": request.method,
            "path": path,
            "patient_id": patient_id,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "user_agent": request.headers.get("user-agent", "unknown"),
        }

        audit_logger.info(json.dumps(log_record))
        return response
