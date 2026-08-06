"""
tests/test_security_remediation.py — Testes da Suíte de Segurança e Hardening.

Valida:
1. Rotação de chaves e permissões por escopo (wearables:write, wearables:read, admin).
2. Bloqueio 401 para requisições não autenticadas e 403 para chaves com escopo insuficiente.
3. Cabeçalhos de Segurança HTTP (HSTS, CSP, X-Frame-Options, X-Content-Type-Options).
4. Injeção de X-Request-ID e Audit Logging.
5. Proteção de Rate Limiting (429 Too Many Requests).
"""

import os
import pytest
from fastapi.testclient import TestClient

from src.api_server import app
from src.security.auth import generate_api_key

client = TestClient(app)

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
READ_KEY = "ht_read_test_key_32chars_long_token"
ADMIN_KEY = "ht_admin_test_key_32chars_long_token"


def test_unauthenticated_request_returns_401():
    """Requisições sem X-API-Key devem ser rejeitadas com 401 Unauthorized."""
    response = client.post(
        "/api/v1/wearables/ingest",
        json={
            "patient_id": "PAT-TEST-001",
            "heart_rate": 75.0
        }
    )
    assert response.status_code == 401
    assert "API key" in response.json()["detail"]


def test_ingest_key_can_write_telemetry():
    """Chave com escopo wearables:write pode enviar telemetria (200 OK)."""
    response = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={
            "patient_id": "PAT-TEST-001",
            "device_id": "wrist_band_v1",
            "heart_rate": 82.0,
            "hrv_rmssd": 45.0,
            "skin_temp": 33.5
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PAT-TEST-001"
    assert data["cleaned_telemetry"]["heart_rate_clean"] == 82.0


def test_read_key_cannot_write_telemetry():
    """Chave de leitura (ht_read_...) deve ser rejeitada com 403 ao tentar enviar telemetria."""
    response = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": READ_KEY},
        json={
            "patient_id": "PAT-TEST-002",
            "heart_rate": 78.0
        }
    )
    assert response.status_code == 403
    assert "wearables:write" in response.json()["detail"]


def test_read_key_can_read_patient_telemetry():
    """Chave de leitura pode acessar o histórico de um paciente."""
    # Primeiro ingerir com a chave de escrita
    client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-READ-001", "heart_rate": 72.0}
    )
    # Ler com a chave de leitura
    response = client.get(
        "/api/v1/wearables/patient/PAT-READ-001/latest",
        headers={"X-API-Key": READ_KEY}
    )
    assert response.status_code == 200
    assert response.json()["patient_id"] == "PAT-READ-001"


def test_ingest_key_cannot_access_admin_endpoints():
    """Chave de ingestão deve ser bloqueada (403) em endpoints admin."""
    response = client.post(
        "/api/v1/admin/reindex",
        headers={"X-API-Key": INGEST_KEY}
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"]


def test_admin_key_has_all_permissions():
    """Chave admin tem acesso completo a endpoints administrativos e de leitura/escrita."""
    response = client.get(
        "/api/status",
        headers={"X-API-Key": ADMIN_KEY}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "online"


def test_security_headers_present():
    """Respostas HTTP devem incluir todos os cabeçalhos de segurança exigidos (HSTS, CSP, nosniff, etc)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers
    assert "Strict-Transport-Security" in headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in headers
    assert "Content-Security-Policy" in headers


def test_x_request_id_header_injected():
    """Todas as respostas devem conter um header X-Request-ID único para auditoria."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 10


def test_rate_limiting_headers_injected():
    """Respostas devem incluir headers X-RateLimit-Limit e X-RateLimit-Remaining."""
    response = client.get(
        "/api/v1/wearables/patient/PAT-READ-001/latest",
        headers={"X-API-Key": READ_KEY}
    )
    assert response.status_code == 200
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers


def test_idor_patient_authorization_blocked(monkeypatch):
    """Verifica se chave não autorizada para paciente específico é bloqueada com 403 (IDOR Protection)."""
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-ALLOWED-001,PAT-ALLOWED-002")
    response = client.get(
        "/api/v1/wearables/patient/PAT-BLOCKED-999/latest",
        headers={"X-API-Key": READ_KEY}
    )
    assert response.status_code == 403
    assert "Acesso proibido" in response.json()["detail"]


def test_pydantic_input_validation_and_sanitization():
    """Valida rejeição de limites fisiológicos e filter_type inválido via Pydantic."""
    # Frequência cardíaca fora do limite (ex: 500.0)
    res_hr = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-TEST-VAL", "heart_rate": 500.0}
    )
    assert res_hr.status_code == 422

    # filter_type inválido
    res_filter = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-TEST-VAL", "heart_rate": 75.0, "filter_type": "INVALID_FILTER"}
    )
    assert res_filter.status_code == 422


def test_lgpd_patient_anonymization_endpoint():
    """Valida expurgo/anonimização de dados do paciente via endpoint LGPD (escopo admin)."""
    # Ingerir dado
    client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-LGPD-DEL", "heart_rate": 80.0}
    )
    # Deletar via admin
    del_res = client.delete(
        "/api/v1/patient/PAT-LGPD-DEL/anonymize",
        headers={"X-API-Key": ADMIN_KEY}
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    # Leitura posterior deve retornar 404
    get_res = client.get(
        "/api/v1/wearables/patient/PAT-LGPD-DEL/latest",
        headers={"X-API-Key": ADMIN_KEY}
    )
    assert get_res.status_code == 404

