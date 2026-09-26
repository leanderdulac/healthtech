"""Settings via pydantic-settings (12-factor)."""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Ambiente (env: ENVIRONMENT, etc.)
    environment: str = "development"
    # secure = API enxuta | full = monólito (dashboard + WS + phantom/Vertex)
    app_mode: str = "secure"
    app_name: str = "Saúde Responsiva Secure API"
    app_version: str = "1.0.0"

    # Auth
    api_key: str = ""
    admin_api_key: str = ""
    ingest_api_key: str = ""
    read_api_key: str = ""
    auth_disabled: bool = False
    secret_salt: str = "default-salt"
    allowed_patient_ids: str = ""

    # CORS
    cors_origins: str = (
        "http://localhost:8000,http://localhost:8080,"
        "http://127.0.0.1:8000,http://127.0.0.1:8080"
    )

    # Rate limiting (slowapi)
    rate_limit_default: str = "120/minute"
    rate_limit_ingest: str = "180/minute"
    rate_limit_batch: str = "30/minute"
    rate_limit_admin: str = "10/minute"

    # Telemetria em memória (fallback só sem DATABASE_URL)
    history_max_per_patient: int = 100

    # Postgres operacional (Cloud SQL). Alias: OPERATIONAL_DATABASE_URL.
    database_url: str = ""
    operational_database_url: str = ""

    @field_validator("environment")
    @classmethod
    def normalize_env(cls, v: str) -> str:
        return (v or "development").strip().lower()

    @field_validator("app_mode")
    @classmethod
    def normalize_mode(cls, v: str) -> str:
        mode = (v or "secure").strip().lower()
        if mode not in {"secure", "full"}:
            return "secure"
        return mode

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod", "staging"}

    @property
    def is_full_mode(self) -> bool:
        return self.app_mode == "full"

    @property
    def is_auth_disabled(self) -> bool:
        """AUTH_DISABLED só vale fora de produção."""
        if self.auth_disabled and self.is_production:
            return False
        return self.auth_disabled

    def get_cors_origins(self) -> List[str]:
        raw = (self.cors_origins or "").strip()
        if raw:
            origins = [o.strip() for o in raw.split(",") if o.strip()]
            if self.is_production and origins == ["*"]:
                return []
            return origins
        if self.is_production:
            return []
        return [
            "http://localhost:8000",
            "http://localhost:8080",
            "http://127.0.0.1:8000",
            "http://127.0.0.1:8080",
        ]

    def get_allowed_patients(self) -> set[str]:
        """IDs permitidos para chaves não-admin.

        Distingue wildcard de allow-list ausente — `check_patient_authorization`
        trata `set()` como unset (fail-closed em produção) e `{"*"}` como
        acesso a qualquer patient_id:
        - unset / vazio → `set()`
        - `*` / `ALL` / `all` → `{"*"}`
        - CSV finito → conjunto de IDs
        """
        raw = (self.allowed_patient_ids or "").strip()
        if not raw:
            return set()
        allowed = {p.strip() for p in raw.split(",") if p.strip()}
        if allowed & {"*", "ALL", "all"}:
            return {"*"}
        return allowed


@lru_cache
def get_settings() -> Settings:
    return Settings()
