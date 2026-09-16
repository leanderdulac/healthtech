"""GET /api/v1/patients — cadastro operacional via FastAPI."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api_server import app
from src.ops.operational_patients import OperationalDbUnavailable

client = TestClient(app)
READ_HEADERS = {"X-API-Key": "ht_read_test_key_32chars_long_token"}
INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}

SAMPLE = {
    "patient_id": "PAT-N2U-001",
    "display_name": "Paciente demonstração",
    "phone": "5511999999999",
    "caregiver_phone": None,
    "programs": ["has"],
    "diseases": ["hypertension"],
    "isolation_social": False,
    "is_demo": True,
    "municipality_id": None,
    "ubs_id": None,
    "created_at": "2026-09-08T00:00:00",
    "updated_at": "2026-09-08T00:00:00",
}


def test_patients_requires_read_scope():
    denied = client.get("/api/v1/patients")
    assert denied.status_code == 401
    forbidden = client.get("/api/v1/patients", headers=INGEST_HEADERS)
    assert forbidden.status_code == 403


def test_patients_list_when_db_configured():
    with patch(
        "src.ops.patients_routes.list_patients",
        return_value=([SAMPLE], 1),
    ):
        res = client.get("/api/v1/patients", headers=READ_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["patients"][0]["patient_id"] == "PAT-N2U-001"
    assert body["patients"][0]["is_demo"] is True


def test_patients_list_without_database_url():
    with patch(
        "src.ops.patients_routes.list_patients",
        side_effect=OperationalDbUnavailable("DATABASE_URL não configurada"),
    ):
        res = client.get("/api/v1/patients", headers=READ_HEADERS)
    assert res.status_code == 503


def test_patient_by_id_found():
    with patch("src.ops.patients_routes.get_patient", return_value=SAMPLE):
        res = client.get("/api/v1/patients/PAT-N2U-001", headers=READ_HEADERS)
    assert res.status_code == 200
    assert res.json()["patient_id"] == "PAT-N2U-001"


def test_patient_by_id_not_found():
    with patch("src.ops.patients_routes.get_patient", return_value=None):
        res = client.get("/api/v1/patients/PAT-MISSING", headers=READ_HEADERS)
    assert res.status_code == 404


def test_patients_list_respects_allowed_ids(monkeypatch):
    other = {**SAMPLE, "patient_id": "PAT-SECRET"}
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-N2U-001")
    with patch(
        "src.ops.patients_routes.list_patients",
        return_value=([SAMPLE, other], 2),
    ):
        res = client.get("/api/v1/patients", headers=READ_HEADERS)
    assert res.status_code == 200
    ids = [p["patient_id"] for p in res.json()["patients"]]
    assert ids == ["PAT-N2U-001"]


def test_patients_list_star_allows_all(monkeypatch):
    other = {**SAMPLE, "patient_id": "PAT-SECRET"}
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "*")
    with patch(
        "src.ops.patients_routes.list_patients",
        return_value=([SAMPLE, other], 2),
    ):
        res = client.get("/api/v1/patients", headers=READ_HEADERS)
    assert res.status_code == 200
    ids = [p["patient_id"] for p in res.json()["patients"]]
    assert ids == ["PAT-N2U-001", "PAT-SECRET"]
