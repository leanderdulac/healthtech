"""
Autenticação e CORS para APIs HealthTech.

Uso:
  - Definir API_KEY no ambiente (produção).
  - Em desenvolvimento, AUTH_DISABLED=true desliga a exigência de chave.
  - CORS via CORS_ORIGINS (lista separada por vírgula).
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from typing import List, Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)

# Valores de salt considerados inseguros
_WEAK_SALTS = frozenset(
    {
        "",
        "default-salt",
        "altere-este-salt-em-producao",
        "change-me",
        "secret",
    }
)


def is_production() -> bool:
    env = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
    return env in {"production", "prod", "staging"}


def auth_disabled() -> bool:
    """Desliga auth apenas se explicitamente pedido e fora de produção."""
    flag = os.getenv("AUTH_DISABLED", "false").lower() in {"1", "true", "yes"}
    if flag and is_production():
        logger.warning(
            "AUTH_DISABLED ignorado em produção — autenticação permanece ativa."
        )
        return False
    return flag


def get_configured_api_key() -> Optional[str]:
    key = os.getenv("API_KEY", "").strip()
    return key or None


def get_cors_origins() -> List[str]:
    """
    Origens CORS permitidas.

    - CORS_ORIGINS=https://app.example.com,http://localhost:3000
    - Default em dev: localhost (dashboard e streamlit)
    - Em produção sem lista: lista vazia (sem * + credentials)
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]

    if is_production():
        return []

    return [
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]


def cors_allow_credentials() -> bool:
    """Credentials só com origins explícitas (nunca com *)."""
    origins = get_cors_origins()
    return bool(origins) and origins != ["*"]


def verify_api_key(provided: Optional[str]) -> bool:
    expected = get_configured_api_key()
    if auth_disabled():
        return True
    if not expected:
        if is_production():
            return False
        # Dev sem API_KEY: permite, mas loga uma vez por processo
        logger.debug("API_KEY não configurada — acesso liberado (desenvolvimento).")
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def require_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """Dependency FastAPI: exige X-API-Key quando configurado/produção."""
    if verify_api_key(x_api_key):
        return x_api_key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key inválida ou ausente. Envie o header X-API-Key.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def validate_secret_salt(raise_in_production: bool = True) -> str:
    """
    Valida SECRET_SALT. Em produção, recusa valores fracos/default.
    """
    salt = os.getenv("SECRET_SALT", "default-salt")
    weak = salt.strip().lower() in _WEAK_SALTS or salt in _WEAK_SALTS

    if weak:
        msg = (
            "SECRET_SALT ausente ou inseguro. "
            "Defina um valor forte em .env (ex.: openssl rand -hex 32)."
        )
        if is_production() and raise_in_production:
            raise RuntimeError(msg)
        logger.warning(msg)
    return salt


def generate_api_key() -> str:
    """Gera chave aleatória para uso em .env."""
    return secrets.token_urlsafe(32)
