"""Fixtures compartilhadas e path da API segura.

O backend WEARABLE_TEST_DB vive neste conftest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
for path in (SECURE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    """Ambiente seguro para testes unitários."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("SECURE_API_BASE_URL", raising=False)
    monkeypatch.delenv("SECURE_READ_API_KEY", raising=False)
    monkeypatch.delenv("SECURE_API_KEY", raising=False)
    monkeypatch.setenv("SECRET_SALT", "test-salt-not-for-production-use-32b")


_CRITICAL_HINTS = (
    "alert",
    "ingest",
    "security",
    "connection",
    "hband",
    "wearable",
    "anonymization",
    "vendor",
)
_RESEARCH_HINTS = ("tcn", "bmo", "hemodynamic", "chaos")


def pytest_collection_modifyitems(items):
    """Marca testes de produto vs laboratório sem anotar cada função."""
    for item in items:
        node = item.nodeid.lower()
        if any(h in node for h in _RESEARCH_HINTS):
            item.add_marker(pytest.mark.research)
        if any(h in node for h in _CRITICAL_HINTS):
            item.add_marker(pytest.mark.critical)
