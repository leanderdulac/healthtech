"""Testes do módulo de autenticação e CORS."""

from __future__ import annotations

import pytest

from src.security.auth import (
    get_cors_origins,
    validate_secret_salt,
    verify_api_key,
)


def test_verify_api_key_dev_without_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("API_KEY", raising=False)
    assert verify_api_key(None) is True
    assert verify_api_key("anything") is True


def test_verify_api_key_with_configured_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("API_KEY", "super-secret-key")
    assert verify_api_key("super-secret-key") is True
    assert verify_api_key("wrong") is False
    assert verify_api_key(None) is False


def test_verify_api_key_production_requires_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_KEY", raising=False)
    assert verify_api_key(None) is False


def test_auth_disabled_ignored_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("API_KEY", "prod-key")
    assert verify_api_key("prod-key") is True
    assert verify_api_key("wrong") is False


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


def test_cors_origins_production_empty_without_config(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert get_cors_origins() == []


def test_cors_origins_explicit(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, http://localhost:3000")
    assert get_cors_origins() == [
        "https://app.example.com",
        "http://localhost:3000",
    ]
