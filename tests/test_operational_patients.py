"""GET /api/v1/patients — enumeração autorizada (authz antes de LIMIT/OFFSET)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.api_server import app
from src.ops import operational_patients as op
from src.ops.operational_patients import (
    InvalidTerritoryScope,
    OperationalDbUnavailable,
    TerritoryScope,
    parse_allowed_patient_ids,
    parse_territory_scopes,
)

client = TestClient(app)
READ_HEADERS = {"X-API-Key": "ht_read_test_key_32chars_long_token"}
INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
ADMIN_HEADERS = {"X-API-Key": "ht_admin_test_key_32chars_long_token"}

SAMPLE = {
    "patient_id": "PAT-N2U-001",
    "display_name": "Paciente demonstração",
    "phone": "5511999999999",
    "caregiver_phone": None,
    "programs": ["has"],
    "diseases": ["hypertension"],
    "isolation_social": False,
    "is_demo": True,
    "municipality_id": "mun-a",
    "ubs_id": "ubs-1",
    "created_at": "2026-09-08T00:00:00",
    "updated_at": "2026-09-08T00:00:00",
}

_CREATE_SQL = """
CREATE TABLE enrollments (
    patient_id TEXT PRIMARY KEY,
    display_name TEXT,
    phone TEXT,
    caregiver_phone TEXT,
    programs TEXT,
    diseases TEXT,
    isolation_social INTEGER DEFAULT 0,
    is_demo INTEGER DEFAULT 0,
    municipality_id TEXT,
    ubs_id TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""


@pytest.fixture
def enrollment_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'enrollments.db'}")
    rows = [
        # updated_at DESC: E, A, B, C, D — mixed allow-list + undefined territory
        ("PAT-E", None, None, "2026-09-16T11:00:00"),
        ("PAT-A", "mun-a", "ubs-1", "2026-09-16T10:00:00"),
        ("PAT-B", "mun-a", "ubs-1", "2026-09-16T09:00:00"),
        ("PAT-C", "mun-a", "ubs-2", "2026-09-16T08:00:00"),
        ("PAT-D", "mun-b", "ubs-9", "2026-09-16T07:00:00"),
    ]
    with engine.begin() as conn:
        conn.execute(text(_CREATE_SQL))
        for pid, mun, ubs, updated in rows:
            conn.execute(
                text(
                    "INSERT INTO enrollments (patient_id, display_name, programs, diseases, "
                    "municipality_id, ubs_id, created_at, updated_at) "
                    "VALUES (:pid, :name, :programs, :diseases, :mun, :ubs, :ts, :ts)"
                ),
                {
                    "pid": pid,
                    "name": pid,
                    "programs": '["has"]',
                    "diseases": "[]",
                    "mun": mun,
                    "ubs": ubs,
                    "ts": updated,
                },
            )
    op.set_engine(engine)
    try:
        yield engine
    finally:
        op.reset_engine()


def test_list_with_constraint_without_db_is_unavailable():
    op.reset_engine()
    with pytest.raises(OperationalDbUnavailable):
        op.list_patients(
            allowed_patient_ids=frozenset({"PAT-A"}),
            fail_closed_without_constraint=True,
            require_defined_territory=True,
        )
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
    assert body["items"][0]["patient_id"] == "PAT-N2U-001"
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


def test_route_pushes_allow_list_into_list_patients(monkeypatch):
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-A,PAT-C")
    with patch(
        "src.ops.patients_routes.list_patients",
        return_value=([], 0),
    ) as mocked:
        res = client.get("/api/v1/patients?limit=1&offset=0", headers=READ_HEADERS)
    assert res.status_code == 200
    kwargs = mocked.call_args.kwargs
    assert kwargs["allowed_patient_ids"] == frozenset({"PAT-A", "PAT-C"})
    assert kwargs["limit"] == 1
    assert kwargs["offset"] == 0
    assert kwargs["require_defined_territory"] is True
    assert kwargs["fail_closed_without_constraint"] is True


def test_wildcard_without_territory_is_fail_closed(monkeypatch):
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "*")
    with patch(
        "src.ops.patients_routes.list_patients",
        return_value=([], 0),
    ) as mocked:
        res = client.get("/api/v1/patients", headers=READ_HEADERS)
    assert res.status_code == 200
    assert res.json()["total"] == 0
    assert res.json()["items"] == []
    assert mocked.call_args.kwargs["allowed_patient_ids"] is None
    assert mocked.call_args.kwargs["fail_closed_without_constraint"] is True


def test_parse_allowed_patient_ids():
    assert parse_allowed_patient_ids("") == (frozenset(), False)
    assert parse_allowed_patient_ids(None) == (frozenset(), False)
    ids, wild = parse_allowed_patient_ids("PAT-A, PAT-C")
    assert ids == frozenset({"PAT-A", "PAT-C"}) and wild is False
    ids, wild = parse_allowed_patient_ids("*")
    assert ids is None and wild is True


def test_parse_territory_scopes_union_and_pairing():
    scopes = parse_territory_scopes(
        territory=["mun-a:ubs-1", "mun-b"],
        municipality_id=["mun-c"],
        ubs_id=[],
    )
    assert scopes == [
        TerritoryScope("mun-a", "ubs-1"),
        TerritoryScope("mun-b", None),
        TerritoryScope("mun-c", None),
    ]
    paired = parse_territory_scopes(municipality_id=["mun-a"], ubs_id=["ubs-1"])
    assert paired == [TerritoryScope("mun-a", "ubs-1")]
    with pytest.raises(InvalidTerritoryScope):
        parse_territory_scopes(municipality_id=[], ubs_id=["ubs-orphan"])


def test_authz_before_pagination_mixed_allow_list(enrollment_db):
    """Page-then-filter would leak PAT-B; filter-then-page must not."""
    allowed = frozenset({"PAT-A", "PAT-C", "PAT-E"})
    page1, total = op.list_patients(
        limit=1,
        offset=0,
        allowed_patient_ids=allowed,
        require_defined_territory=True,
        fail_closed_without_constraint=True,
    )
    page2, total2 = op.list_patients(
        limit=1,
        offset=1,
        allowed_patient_ids=allowed,
        require_defined_territory=True,
        fail_closed_without_constraint=True,
    )
    ids1 = [p["patient_id"] for p in page1]
    ids2 = [p["patient_id"] for p in page2]
    assert total == total2 == 2
    assert ids1 == ["PAT-A"]
    assert ids2 == ["PAT-C"]
    assert "PAT-B" not in ids1 + ids2
    assert "PAT-D" not in ids1 + ids2
    assert "PAT-E" not in ids1 + ids2


def test_authorized_total_is_not_global_count(enrollment_db):
    items, total = op.list_patients(
        limit=50,
        offset=0,
        allowed_patient_ids=frozenset({"PAT-A", "PAT-C"}),
        require_defined_territory=True,
        fail_closed_without_constraint=True,
    )
    assert total == 2
    assert {p["patient_id"] for p in items} == {"PAT-A", "PAT-C"}


def test_territory_ubs_and_municipal_union(enrollment_db):
    ubs, total_ubs = op.list_patients(
        limit=50,
        offset=0,
        allowed_patient_ids=None,
        territories=[TerritoryScope("mun-a", "ubs-1")],
        require_defined_territory=True,
        fail_closed_without_constraint=True,
    )
    assert total_ubs == 2
    assert {p["patient_id"] for p in ubs} == {"PAT-A", "PAT-B"}

    municipal, total_mun = op.list_patients(
        limit=50,
        offset=0,
        territories=[TerritoryScope("mun-a", None)],
        require_defined_territory=True,
        fail_closed_without_constraint=True,
    )
    assert total_mun == 3
    assert {p["patient_id"] for p in municipal} == {"PAT-A", "PAT-B", "PAT-C"}

    union, total_union = op.list_patients(
        limit=50,
        offset=0,
        territories=[
            TerritoryScope("mun-a", "ubs-1"),
            TerritoryScope("mun-b", None),
        ],
        require_defined_territory=True,
        fail_closed_without_constraint=True,
    )
    assert total_union == 3
    assert {p["patient_id"] for p in union} == {"PAT-A", "PAT-B", "PAT-D"}


def test_fail_closed_empty_allow_list_and_missing_territory(enrollment_db):
    items, total = op.list_patients(
        limit=50,
        offset=0,
        allowed_patient_ids=frozenset(),
        fail_closed_without_constraint=True,
        require_defined_territory=True,
    )
    assert items == [] and total == 0
    items, total = op.list_patients(
        limit=50,
        offset=0,
        allowed_patient_ids=None,
        territories=[],
        fail_closed_without_constraint=True,
        require_defined_territory=True,
    )
    assert items == [] and total == 0


def test_route_mixed_allow_list_does_not_return_unauthorized(enrollment_db, monkeypatch):
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "PAT-A,PAT-C,PAT-E")
    res = client.get("/api/v1/patients?limit=1&offset=0", headers=READ_HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert [p["patient_id"] for p in body["items"]] == ["PAT-A"]
    res2 = client.get("/api/v1/patients?limit=1&offset=1", headers=READ_HEADERS)
    assert [p["patient_id"] for p in res2.json()["items"]] == ["PAT-C"]
    assert res2.json()["total"] == 2


def test_route_territory_query_filters_before_page(enrollment_db, monkeypatch):
    monkeypatch.setenv("ALLOWED_PATIENT_IDS", "*")
    res = client.get(
        "/api/v1/patients?territory=mun-a:ubs-1&limit=1&offset=0",
        headers=READ_HEADERS,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert body["items"][0]["patient_id"] == "PAT-A"
    res2 = client.get(
        "/api/v1/patients?territory=mun-a:ubs-1&limit=1&offset=1",
        headers=READ_HEADERS,
    )
    assert res2.json()["items"][0]["patient_id"] == "PAT-B"


def test_route_without_constraint_does_not_leak_global(enrollment_db, monkeypatch):
    monkeypatch.delenv("ALLOWED_PATIENT_IDS", raising=False)
    res = client.get("/api/v1/patients?limit=50", headers=READ_HEADERS)
    assert res.status_code == 200
    assert res.json()["total"] == 0
    assert res.json()["items"] == []
    assert res.json()["patients"] == []
    res = client.get(
        "/api/v1/patients?ubs_id=ubs-orphan",
        headers=READ_HEADERS,
    )
    assert res.status_code == 400


def test_devices_patient_id_filters_before_pagination():
    from src.ops.device_registry import clear_all, list_devices, upsert_frame

    clear_all()
    for i in range(6):
        upsert_frame(
            {
                "patient_id": "PAT-KEEP" if i % 2 == 0 else "PAT-OTHER",
                "device_id": f"DEV-{i:03d}",
                "timestamp": f"2026-09-16T10:00:{i:02d}+00:00",
                "raw_telemetry": {"heart_rate_bpm": 70 + i, "spo2_percent": 97},
            }
        )
    page = list_devices(patient_id="PAT-KEEP", limit=2, offset=0)
    assert page["coverage"] == "patient"
    assert page["patient_id"] == "PAT-KEEP"
    assert page["counts"]["total"] == 3
    assert len(page["devices"]) == 2
    assert {d["patient_id"] for d in page["devices"]} == {"PAT-KEEP"}
    page2 = list_devices(patient_id="PAT-KEEP", limit=2, offset=2)
    assert len(page2["devices"]) == 1
    assert page2["devices"][0]["patient_id"] == "PAT-KEEP"
    empty = list_devices(patient_id="PAT-NONE")
    assert empty["counts"]["total"] == 0
    assert empty["devices"] == []
    listed = client.get(
        "/api/v1/wearables/devices?patient_id=PAT-KEEP&limit=10",
        headers=READ_HEADERS,
    )
    assert listed.status_code == 200
    http_body = listed.json()
    assert http_body["coverage"] == "patient"
    assert http_body["counts"]["total"] == 3
    assert {d["patient_id"] for d in http_body["devices"]} == {"PAT-KEEP"}
    clear_all()
