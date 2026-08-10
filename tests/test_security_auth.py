"""Testes do módulo de autenticação e CORS."""

from __future__ import annotations

import pytest

from src.security.auth import (
    check_patient_authorization,
    get_cors_origins,
    get_key_scopes,
    validate_secret_salt,
    verify_api_key,
)


def test_verify_api_key_dev_without_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    assert verify_api_key(None) is True
    assert verify_api_key("anything") is True


def test_verify_api_key_with_configured_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ADMIN_API_KEY", "ht_admin_super_secret_key_long_token")
    assert verify_api_key("ht_admin_super_secret_key_long_token") is True
    assert verify_api_key("wrong_token_value_without_prefix") is False
    assert verify_api_key(None) is False


def test_verify_api_key_production_requires_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("INGEST_API_KEY", raising=False)
    monkeypatch.delenv("READ_API_KEY", raising=False)
    assert verify_api_key(None) is False
    # Sem defaults hardcoded: chave "live" do repositório NÃO autentica
    assert verify_api_key("ht_admin_live_key_2026_safe_token_32c") is False


def test_prefix_matching_does_not_grant_scopes(monkeypatch):
    """Regressão: startswith('ht_admin_') era bypass total de autenticação."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_API_KEY", "ht_admin_real_configured_secret_value_32")
    monkeypatch.setenv("INGEST_API_KEY", "ht_ingest_real_configured_secret_value")
    monkeypatch.setenv("READ_API_KEY", "ht_read_real_configured_secret_value")
    # Qualquer string com o prefixo NÃO deve autenticar
    assert verify_api_key("ht_admin_attacker_forged_key_not_configured") is False
    assert verify_api_key("ht_ingest_FOO") is False
    assert verify_api_key("ht_read_xxx") is False
    assert get_key_scopes("ht_admin_attacker_forged_key_not_configured") == set()
    # Apenas a chave exata
    assert "admin" in get_key_scopes("ht_admin_real_configured_secret_value_32")
    assert get_key_scopes("ht_ingest_real_configured_secret_value") == {"wearables:write"}


def test_auth_disabled_ignored_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEY", "ht_admin_prod_key_long_token_value")
    assert verify_api_key("ht_admin_prod_key_long_token_value") is True
    assert verify_api_key("wrong_token_value_without_prefix") is False


def test_idor_fail_closed_in_production_without_whitelist(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("INGEST_API_KEY", "ht_ingest_real_configured_secret_value")
    monkeypatch.delenv("ALLOWED_PATIENT_IDS", raising=False)
    # Chave de ingest (não admin) sem whitelist → nega
    assert (
        check_patient_authorization("ht_ingest_real_configured_secret_value", "PAT-X")
        is False
    )
    # Com whitelist
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-X,PAT-Y")
    assert (
        check_patient_authorization("ht_ingest_real_configured_secret_value", "PAT-X")
        is True
    )
    assert (
        check_patient_authorization("ht_ingest_real_configured_secret_value", "PAT-Z")
        is False
    )


def test_validate_secret_salt_weak_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_SALT", "default-salt")
    with pytest.raises(RuntimeError, match="SECRET_SALT"):
        validate_secret_salt(raise_in_production=True)


def test_validate_secret_salt_ok(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_SALT", "a-strong-random-salt-value-32chars")
    assert validate_secret_salt() == "a-strong-random-salt-value-32chars"


def test_cors_origins_default_dev(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    origins = get_cors_origins()
    assert any("localhost" in o for o in origins)
    assert "*" not in origins


def test_cors_origins_production_default_fallback_without_config(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    origins = get_cors_origins()
    assert len(origins) > 0
    assert "https://healthtech-responsive-5794833455.us-central1.run.app" in origins


def test_cors_origins_explicit(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, http://localhost:3000")
    assert get_cors_origins() == [
        "https://app.example.com",
        "http://localhost:3000",
    ]
