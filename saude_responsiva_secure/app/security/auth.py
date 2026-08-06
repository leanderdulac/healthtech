"""
API Keys + scopes + autorização por paciente (anti-IDOR).

Escopos:
  - wearables:write  — ingestão de telemetria
  - wearables:read   — latest / history
  - admin            — search reindex / status / LGPD

Chaves (exatas, comparadas com hmac.compare_digest — sem prefix matching):
  - ADMIN_API_KEY ou API_KEY → todos os escopos
  - INGEST_API_KEY → wearables:write
  - READ_API_KEY → wearables:read
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Callable, Optional, Set

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)

_WEAK_KEYS = frozenset(
    {
        "",
        "healthtech_live_key_2026",
        "default-key",
        "change-me",
        "secret",
        "123456",
    }
)

_WEAK_SALTS = frozenset(
    {
        "",
        "default-salt",
        "altere-este-salt-em-producao",
        "change-me",
        "secret",
    }
)


def mask_api_key(key: Optional[str]) -> str:
    if not key:
        return "anonymous"
    if len(key) <= 8:
        return "***"
    return f"{key[:7]}***{key[-4:]}"


def _safe_eq(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


def get_key_scopes(provided_key: Optional[str], settings: Optional[Settings] = None) -> Set[str]:
    settings = settings or get_settings()

    if settings.is_auth_disabled:
        return {"wearables:write", "wearables:read", "admin"}

    if not provided_key:
        return set()

    scopes: Set[str] = set()
    admin_key = (settings.admin_api_key or settings.api_key or "").strip()
    ingest_key = (settings.ingest_api_key or "").strip()
    read_key = (settings.read_api_key or "").strip()

    if admin_key and _safe_eq(provided_key, admin_key):
        scopes.update(["wearables:write", "wearables:read", "admin"])

    if ingest_key and _safe_eq(provided_key, ingest_key):
        scopes.add("wearables:write")

    if read_key and _safe_eq(provided_key, read_key):
        scopes.add("wearables:read")

    # Dev-only: chaves de teste longas usadas nos testes unitários (nunca em prod)
    if not settings.is_production:
        dev_map = {
            "ht_admin_test_key_32chars_long_token": {"wearables:write", "wearables:read", "admin"},
            "ht_ingest_test_key_32chars_long_token": {"wearables:write"},
            "ht_read_test_key_32chars_long_token": {"wearables:read"},
        }
        if provided_key in dev_map:
            scopes.update(dev_map[provided_key])

    return scopes


def verify_api_key(provided: Optional[str], settings: Optional[Settings] = None) -> bool:
    settings = settings or get_settings()
    if settings.is_auth_disabled:
        return True
    return len(get_key_scopes(provided, settings)) > 0


async def require_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    if verify_api_key(x_api_key, settings) and x_api_key:
        return x_api_key
    if settings.is_auth_disabled:
        return x_api_key or "dev_bypass_key"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key inválida ou ausente. Envie o header X-API-Key válido.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def require_scope(required_scope: str) -> Callable:
    async def scope_dependency(
        x_api_key: Optional[str] = Security(api_key_header),
        settings: Settings = Depends(get_settings),
    ) -> str:
        if settings.is_auth_disabled:
            return x_api_key or "dev_bypass_key"

        if not x_api_key or not verify_api_key(x_api_key, settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key inválida ou ausente. Envie o header X-API-Key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        user_scopes = get_key_scopes(x_api_key, settings)
        if required_scope not in user_scopes:
            logger.warning(
                "Acesso negado: chave '%s' sem escopo '%s' (atual: %s)",
                mask_api_key(x_api_key),
                required_scope,
                user_scopes,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Acesso proibido. O escopo '{required_scope}' "
                    "é necessário para esta operação."
                ),
            )
        return x_api_key

    return scope_dependency


def check_patient_authorization(
    provided_key: Optional[str],
    target_patient_id: str,
    settings: Optional[Settings] = None,
) -> bool:
    settings = settings or get_settings()
    if settings.is_auth_disabled:
        return True
    if not provided_key:
        return False

    scopes = get_key_scopes(provided_key, settings)
    if "admin" in scopes:
        return True

    allowed = settings.get_allowed_patients()
    if allowed:
        return target_patient_id in allowed
    return True


def require_patient_access(required_scope: str = "wearables:read") -> Callable:
    async def patient_dependency(
        patient_id: str,
        x_api_key: Optional[str] = Security(api_key_header),
        settings: Settings = Depends(get_settings),
    ) -> str:
        if settings.is_auth_disabled:
            return x_api_key or "dev_bypass_key"

        if not x_api_key or not verify_api_key(x_api_key, settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key inválida ou ausente. Envie o header X-API-Key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        user_scopes = get_key_scopes(x_api_key, settings)
        if required_scope not in user_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Acesso proibido. O escopo '{required_scope}' "
                    "é necessário para esta operação."
                ),
            )

        if not check_patient_authorization(x_api_key, patient_id, settings):
            logger.warning(
                "IDOR bloqueado: chave '%s' tentou acessar paciente '%s'",
                mask_api_key(x_api_key),
                patient_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Acesso proibido. A chave fornecida não tem autorização "
                    f"para os dados do paciente '{patient_id}'."
                ),
            )
        return x_api_key

    return patient_dependency


def validate_secret_salt(settings: Optional[Settings] = None) -> str:
    settings = settings or get_settings()
    salt = settings.secret_salt
    weak = salt.strip().lower() in _WEAK_SALTS or salt in _WEAK_SALTS
    if weak:
        msg = (
            "SECRET_SALT ausente ou inseguro. "
            "Defina um valor forte em .env (ex.: openssl rand -hex 32)."
        )
        if settings.is_production:
            raise RuntimeError(msg)
        logger.warning(msg)
    return salt


def validate_api_keys_on_startup(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    if settings.is_auth_disabled or not settings.is_production:
        return
    keys = [
        settings.admin_api_key or settings.api_key,
        settings.ingest_api_key,
        settings.read_api_key,
    ]
    configured = [k for k in keys if k and k.strip()]
    if not configured:
        raise RuntimeError(
            "Em produção é obrigatório configurar API_KEY/ADMIN_API_KEY "
            "(e preferencialmente INGEST_API_KEY / READ_API_KEY)."
        )
    for k in configured:
        if k.strip().lower() in _WEAK_KEYS or len(k) < 24:
            raise RuntimeError(
                "API key fraca ou curta detectada. Use chaves fortes "
                "(ex.: openssl rand -hex 32)."
            )


def generate_api_key(prefix: str = "ht_live_") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"
