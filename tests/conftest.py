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
