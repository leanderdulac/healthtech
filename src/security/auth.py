"""
Autenticação, Gestão de Escopos e CORS para APIs HealthTech.

Escopos suportados:
  - wearables:write (ingestão de telemetria)
  - wearables:read (leitura de histórico e estado atual)
  - admin (reindexação, status avançado, gerenciamento)

Chaves configuráveis via ambiente:
  - API_KEY / ADMIN_API_KEY (escopo total: admin, wearables:write, wearables:read)
  - INGEST_API_KEY (escopo: wearables:write)
  - READ_API_KEY (escopo: wearables:read)
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from typing import Callable, List, Optional, Set

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

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


def get_cors_origins() -> List[str]:
    """
    Origens CORS permitidas.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]

    if is_production():
        return [
            "https://healthtech-responsive-5794833455.us-central1.run.app"
        ]

    return [
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]


def cors_allow_credentials() -> bool:
    origins = get_cors_origins()
    return bool(origins) and origins != ["*"]


def mask_api_key(key: Optional[str]) -> str:
    """Retorna a chave mascarada para logs de auditoria de forma segura."""
    if not key:
        return "anonymous"
    if len(key) <= 8:
        return "***"
    return f"{key[:7]}***{key[-4:]}"


def _safe_eq(a: str, b: str) -> bool:
    """Comparação em tempo constante; nunca use startswith para escopos."""
    if not a or not b:
        return False
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


def get_key_scopes(provided_key: Optional[str]) -> Set[str]:
    """
    Retorna o conjunto de escopos concedidos para a chave fornecida.

    Apenas comparação exata (hmac.compare_digest). Prefixos ht_admin_ / ht_ingest_
    NÃO concedem escopo — isso era um bypass crítico.
    """
    if auth_disabled():
        return {"wearables:write", "wearables:read", "admin"}

    if not provided_key:
        return set()

    # Sem defaults hardcoded em produção: chave ausente no env = sem aquele escopo
    admin_key = (os.getenv("ADMIN_API_KEY") or os.getenv("API_KEY") or "").strip()
    ingest_key = (os.getenv("INGEST_API_KEY") or "").strip()
    read_key = (os.getenv("READ_API_KEY") or "").strip()

    # Defaults apenas em development (testes/local) — nunca em production
    if not is_production():
        admin_key = admin_key or "ht_admin_test_key_32chars_long_tokenxx"
        ingest_key = ingest_key or "ht_ingest_test_key_32chars_long_token"
        read_key = read_key or "ht_read_test_key_32chars_long_token"

    scopes: Set[str] = set()

    if admin_key and _safe_eq(provided_key, admin_key):
        scopes.update(["wearables:write", "wearables:read", "admin"])

    if ingest_key and _safe_eq(provided_key, ingest_key):
        scopes.add("wearables:write")

    if read_key and _safe_eq(provided_key, read_key):
        scopes.add("wearables:read")

    # Dev-only: chaves de teste longas usadas nos unit tests (nunca em prod)
    if not is_production():
        dev_map = {
            "ht_admin_test_key_32chars_long_token": {
                "wearables:write",
                "wearables:read",
                "admin",
            },
            "ht_admin_test_key_32chars_long_tokenxx": {
                "wearables:write",
                "wearables:read",
                "admin",
            },
            "ht_ingest_test_key_32chars_long_token": {"wearables:write"},
            "ht_read_test_key_32chars_long_token": {"wearables:read"},
        }
        if provided_key in dev_map:
            scopes.update(dev_map[provided_key])

    return scopes


def verify_api_key(provided: Optional[str]) -> bool:
    if auth_disabled():
        return True
    scopes = get_key_scopes(provided)
    return len(scopes) > 0


async def require_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
) -> str:
    """Dependency FastAPI basica: exige qualquer API Key valida."""
    if verify_api_key(x_api_key) and x_api_key:
        return x_api_key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key inválida ou ausente. Envie o header X-API-Key válido.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def require_scope(required_scope: str) -> Callable:
    """
    Factory de Dependency FastAPI para validar escopos específicos de chave.
    - Se a chave for inválida ou ausente -> 401 Unauthorized
    - Se a chave for válida mas não possuir o escopo exigido -> 403 Forbidden
    """
    async def scope_dependency(
        x_api_key: Optional[str] = Security(api_key_header),
    ) -> str:
        if auth_disabled():
            return x_api_key or "dev_bypass_key"

        if not x_api_key or not verify_api_key(x_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key inválida ou ausente. Envie o header X-API-Key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        user_scopes = get_key_scopes(x_api_key)
        if required_scope not in user_scopes:
            logger.warning(
                f"Acesso negado: chave '{mask_api_key(x_api_key)}' não possui o escopo '{required_scope}' (escopos atuais: {user_scopes})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acesso proibido. O escopo '{required_scope}' é necessário para esta operação.",
            )

        return x_api_key

    return scope_dependency


def validate_secret_salt(raise_in_production: bool = True) -> str:
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


def check_patient_authorization(provided_key: Optional[str], target_patient_id: str) -> bool:
    """
    Verifica se a chave tem permissão para o paciente especificado (Proteção IDOR).
    - Escopo 'admin' tem permissão universal.
    - Se ALLOWED_PATIENT_IDS estiver definido no ambiente, exige inclusão na whitelist.
    - Em produção, sem whitelist e sem admin: nega (fail-closed) para dados clínicos.
    """
    if auth_disabled():
        return True
    if not provided_key:
        return False
    scopes = get_key_scopes(provided_key)
    if "admin" in scopes:
        return True

    allowed_raw = os.getenv("ALLOWED_PATIENT_IDS", "").strip()
    if allowed_raw:
        allowed = {p.strip() for p in allowed_raw.split(",") if p.strip()}
        return target_patient_id in allowed

    # Fail-open só em development (UX de demo). Em production exige whitelist ou admin.
    if is_production():
        logger.warning(
            "IDOR: ALLOWED_PATIENT_IDS não configurado em produção — "
            "negando acesso cross-patient para chave não-admin."
        )
        return False
    return True


def require_patient_access(required_scope: str = "wearables:read") -> Callable:
    """
    Dependency FastAPI para validação de escopo + autorização por paciente (Proteção contra IDOR).
    """
    async def patient_dependency(
        patient_id: str,
        x_api_key: Optional[str] = Security(api_key_header),
    ) -> str:
        if auth_disabled():
            return x_api_key or "dev_bypass_key"

        if not x_api_key or not verify_api_key(x_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key inválida ou ausente. Envie o header X-API-Key.",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        user_scopes = get_key_scopes(x_api_key)
        if required_scope not in user_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acesso proibido. O escopo '{required_scope}' é necessário para esta operação.",
            )

        if not check_patient_authorization(x_api_key, patient_id):
            logger.warning(
                f"Tentativa de IDOR bloqueada: chave '{mask_api_key(x_api_key)}' tentou acessar paciente '{patient_id}' sem permissão."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acesso proibido. A chave fornecida não tem autorização para os dados do paciente '{patient_id}'.",
            )

        return x_api_key

    return patient_dependency


def generate_api_key(prefix: str = "ht_live_") -> str:
    """Gera chave aleatória segura para uso em .env ou clientes."""
    return f"{prefix}{secrets.token_urlsafe(32)}"

