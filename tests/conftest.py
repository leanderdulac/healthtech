"""Fixtures compartilhadas — mantém testes leves (sem torch/chromadb)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    """Ambiente seguro para testes unitários."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.delenv("API_KEY", raising=False)
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
