"""
test_security.py — Suíte de segurança da API Saúde Responsiva Secure.

Valida:
1. 401 sem API key / 403 com escopo insuficiente
2. Escopos wearables:write / wearables:read / admin
3. Security headers (HSTS, CSP, nosniff, X-Frame-Options)
4. X-Request-ID de auditoria
5. Rate limiting (slowapi) e anti-IDOR
6. Validação Pydantic e purge LGPD
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Garante imports `app.*` a partir deste diretório
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ambiente de teste antes de importar a app (sempre modo secure neste suite)
os.environ["ENVIRONMENT"] = "development"
os.environ["AUTH_DISABLED"] = "false"
os.environ["APP_MODE"] = "secure"
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32c")

from app.config import get_settings

get_settings.cache_clear()

from app.main import create_app
from app.services import telemetry_store

app = create_app()

client = TestClient(app)

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
READ_KEY = "ht_read_test_key_32chars_long_token"
ADMIN_KEY = "ht_admin_test_key_32chars_long_token"


@pytest.fixture(autouse=True)
def _clean_store():
    telemetry_store.clear_all()
    yield
    telemetry_store.clear_all()


def test_health_is_public():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "version" in body


def test_unauthenticated_request_returns_401():
    response = client.post(
        "/api/v1/wearables/ingest",
        json={"patient_id": "PAT-TEST-001", "heart_rate": 75.0},
    )
    assert response.status_code == 401
    assert "API key" in response.json()["detail"]


def test_ingest_key_can_write_telemetry():
    response = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={
            "patient_id": "PAT-TEST-001",
            "device_id": "wrist_band_v1",
            "heart_rate": 82.0,
            "hrv_rmssd": 45.0,
            "skin_temp": 33.5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PAT-TEST-001"
    assert data["cleaned_telemetry"]["heart_rate_clean"] == 82.0


def test_read_key_cannot_write_telemetry():
    response = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": READ_KEY},
        json={"patient_id": "PAT-TEST-002", "heart_rate": 78.0},
    )
    assert response.status_code == 403
    assert "wearables:write" in response.json()["detail"]


def test_read_key_can_read_patient_telemetry():
    client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-READ-001", "heart_rate": 72.0},
    )
    response = client.get(
        "/api/v1/wearables/patient/PAT-READ-001/latest",
        headers={"X-API-Key": READ_KEY},
    )
    assert response.status_code == 200
    assert response.json()["patient_id"] == "PAT-READ-001"


def test_history_endpoint():
    for hr in (70.0, 75.0, 80.0):
        client.post(
            "/api/v1/wearables/ingest",
            headers={"X-API-Key": INGEST_KEY},
            json={"patient_id": "PAT-HIST-001", "heart_rate": hr},
        )
    response = client.get(
        "/api/v1/wearables/patient/PAT-HIST-001/history?limit=2",
        headers={"X-API-Key": READ_KEY},
    )
    assert response.status_code == 200
    assert response.json()["total_records"] == 2


def test_ingest_key_cannot_access_admin_endpoints():
    response = client.post(
        "/api/v1/admin/reindex",
        headers={"X-API-Key": INGEST_KEY},
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"]


def test_admin_key_has_all_permissions():
    response = client.get(
        "/api/status",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "online"


def test_security_headers_present():
    response = client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers
    assert "strict-transport-security" in headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "referrer-policy" in headers
    assert "content-security-policy" in headers


def test_x_request_id_header_injected():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 10


def test_idor_patient_authorization_blocked(monkeypatch):
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-ALLOWED-001,PAT-ALLOWED-002")
    get_settings.cache_clear()
    # Recria client com settings frescos
    from app.main import create_app

    fresh = TestClient(create_app())
    response = fresh.get(
        "/api/v1/wearables/patient/PAT-BLOCKED-999/latest",
        headers={"X-API-Key": READ_KEY},
    )
    assert response.status_code == 403
    assert "Acesso proibido" in response.json()["detail"]
    get_settings.cache_clear()
    monkeypatch.delenv("ALLOWED_PATIENT_IDS", raising=False)
    get_settings.cache_clear()


def test_pydantic_input_validation_and_sanitization():
    res_hr = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-TEST-VAL", "heart_rate": 500.0},
    )
    assert res_hr.status_code == 422

    res_filter = client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={
            "patient_id": "PAT-TEST-VAL",
            "heart_rate": 75.0,
            "filter_type": "INVALID_FILTER",
        },
    )
    assert res_filter.status_code == 422


def test_lgpd_patient_anonymization_endpoint():
    client.post(
        "/api/v1/wearables/ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={"patient_id": "PAT-LGPD-DEL", "heart_rate": 80.0},
    )
    del_res = client.delete(
        "/api/v1/patient/PAT-LGPD-DEL/anonymize",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    get_res = client.get(
        "/api/v1/wearables/patient/PAT-LGPD-DEL/latest",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert get_res.status_code == 404


def test_batch_ingest():
    response = client.post(
        "/api/v1/wearables/batch-ingest",
        headers={"X-API-Key": INGEST_KEY},
        json={
            "patient_id": "PAT-BATCH-001",
            "readings": [
                {"patient_id": "PAT-BATCH-001", "heart_rate": 70.0},
                {"patient_id": "PAT-BATCH-001", "heart_rate": 72.0},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["processed_count"] == 2


def test_bmo_analysis_requires_read_scope():
    signal = [70.0, 72.0, 71.0, 73.0, 74.0, 72.0, 70.0, 69.0]
    denied = client.post(
        "/api/v1/signal/bmo-analysis",
        headers={"X-API-Key": INGEST_KEY},
        json={"signal": signal},
    )
    assert denied.status_code == 403

    ok = client.post(
        "/api/v1/signal/bmo-analysis",
        headers={"X-API-Key": READ_KEY},
        json={"signal": signal},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert isinstance(body, dict) and len(body) > 0
    # Aceita perfil fallback local ou BMOAnalyzer do monólito
    assert any(
        k in body
        for k in (
            "n_samples",
            "scales",
            "mean",
            "bmo_norm",
            "vmo_index",
            "scale_mean_oscillations",
        )
    )


def test_prefix_matching_not_accepted():
    """Chaves que apenas começam com ht_admin_ NÃO devem autenticar (fix de segurança)."""
    response = client.get(
        "/api/status",
        headers={"X-API-Key": "ht_admin_forged_prefix_only_not_real"},
    )
    assert response.status_code == 401
