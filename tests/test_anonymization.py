"""Testes de anonimização FHIR."""

from __future__ import annotations

from src.security.anonymization import FHIR_DEID_PROFILE, anonimizar_paciente_fhir


def _sample_patient() -> dict:
    return {
        "resourceType": "Patient",
        "id": "123",
        "name": [{"family": "Silva", "given": ["Maria"]}],
        "birthDate": "1985-06-15",
        "telecom": [{"system": "phone", "value": "+5511999999999"}],
        "photo": [{"url": "http://example.com/photo.jpg"}],
        "contact": [{"name": {"family": "Contato"}}],
        "identifier": [{"system": "cpf", "value": "12345678901"}],
        "address": [
            {
                "line": ["Rua X, 100"],
                "city": "São Paulo",
                "state": "SP",
                "country": "BR",
                "postalCode": "01000-000",
            }
        ],
    }


def test_removes_pii_fields():
    anon = anonimizar_paciente_fhir(_sample_patient())
    assert "name" not in anon
    assert "telecom" not in anon
    assert "photo" not in anon
    assert "contact" not in anon


def test_generalizes_birthdate():
    anon = anonimizar_paciente_fhir(_sample_patient())
    assert anon["birthDate"] == "1985-01-01"


def test_hashes_identifier_deterministically(monkeypatch):
    monkeypatch.setenv("SECRET_SALT", "test-salt-not-for-production-use-32b")
    a = anonimizar_paciente_fhir(_sample_patient())
    b = anonimizar_paciente_fhir(_sample_patient())
    assert a["identifier"][0]["value"] == b["identifier"][0]["value"]
    assert a["identifier"][0]["value"] != "12345678901"
    assert len(a["id"]) == 16


def test_address_minimization_no_city():
    anon = anonimizar_paciente_fhir(_sample_patient())
    assert "city" not in anon["address"][0]
    assert anon["address"][0]["state"] == "SP"
    assert anon["address"][0]["country"] == "BR"


def test_meta_security_profile():
    anon = anonimizar_paciente_fhir(_sample_patient())
    assert FHIR_DEID_PROFILE in anon["meta"]["profile"]
    assert anon["meta"]["security"][0]["code"] == "HTEST"
