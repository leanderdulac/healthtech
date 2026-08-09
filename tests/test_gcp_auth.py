"""Testes de resolução de credenciais GCP (soft no CI sem ADC)."""

from __future__ import annotations

import pytest

from src.utils.gcp_auth import get_gcp_credentials


def test_get_gcp_credentials_returns_project_id():
    creds, project_id = get_gcp_credentials(project_id="healthtech-gcp-2026")
    assert project_id == "healthtech-gcp-2026"
    # Em CI sem ADC/gcloud, creds é None — esperado; não quebra a suite.
    if creds is None:
        pytest.skip("Sem credenciais GCP (ADC/gcloud) neste ambiente")


def test_get_gcp_credentials_default_project_env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "from-env-project")
    _creds, project_id = get_gcp_credentials()
    assert project_id == "from-env-project"
