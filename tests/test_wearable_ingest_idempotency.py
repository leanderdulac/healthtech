"""
Idempotência / proteção contra duplicata nos endpoints de ingestão
da API secure (saude_responsiva_secure).

Cobre: resend unitário, batch com duplicatas parciais, com e sem
client_reading_id, header Idempotency-Key, chave natural, e auth
inalterada (401 sem chave, 403 com chave de leitura).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SECURE_ROOT = Path(__file__).resolve().parents[1] / "saude_responsiva_secure"
if str(SECURE_ROOT) not in sys.path:
    sys.path.insert(0, str(SECURE_ROOT))

os.environ["ENVIRONMENT"] = "development"
os.environ["AUTH_DISABLED"] = "false"
os.environ["APP_MODE"] = "secure"
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32c")

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import telemetry_store  # noqa: E402
from app.services.ingest_idempotency import (  # noqa: E402
    metric_signature,
    resolve_dedup_key,
)

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
READ_KEY = "ht_read_test_key_32chars_long_token"
INGEST_HEADERS = {"X-API-Key": INGEST_KEY}
READ_HEADERS = {"X-API-Key": READ_KEY}

TS = "2026-09-24T12:00:00Z"
TS_OFFSET = "2026-09-24T12:00:00+00:00"


@pytest.fixture
def client():
    get_settings.cache_clear()
    telemetry_store.clear_all()
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
    telemetry_store.clear_all()
    get_settings.cache_clear()


def _history_len(client: TestClient, patient_id: str) -> int:
    resp = client.get(
        f"/api/v1/wearables/patient/{patient_id}/history?limit=100",
        headers=READ_HEADERS,
    )
    if resp.status_code == 404:
        return 0
    assert resp.status_code == 200
    return int(resp.json()["total_records"])


def test_resolve_dedup_key_precedence():
    fields = {"heart_rate", "timestamp"}
    by_client = resolve_dedup_key(
        patient_id="PAT-A",
        device_id="DEV-1",
        client_reading_id="room-row-1",
        idempotency_key="hdr-1",
        client_timestamp=TS,
        fields_set=fields,
    )
    assert by_client == "cid:PAT-A:room-row-1"

    by_header = resolve_dedup_key(
        patient_id="PAT-A",
        device_id="DEV-1",
        client_reading_id=None,
        idempotency_key="hdr-1",
        client_timestamp=TS,
        fields_set=fields,
    )
    assert by_header == "hdr:PAT-A:hdr-1"

    natural = resolve_dedup_key(
        patient_id="PAT-A",
        device_id="DEV-1",
        client_reading_id=None,
        idempotency_key=None,
        client_timestamp=TS,
        fields_set=fields,
    )
    assert natural is not None and natural.startswith("nat:PAT-A:DEV-1:")
    assert natural.endswith(":heart_rate")

    no_key = resolve_dedup_key(
        patient_id="PAT-A",
        device_id="DEV-1",
        client_reading_id=None,
        idempotency_key=None,
        client_timestamp=None,
        fields_set=fields,
    )
    assert no_key is None


def test_natural_key_normalizes_equivalent_timestamps():
    a = resolve_dedup_key(
        patient_id="PAT-A",
        device_id="DEV-1",
        client_reading_id=None,
        idempotency_key=None,
        client_timestamp=TS,
        fields_set={"heart_rate", "spo2"},
    )
    b = resolve_dedup_key(
        patient_id="PAT-A",
        device_id="DEV-1",
        client_reading_id=None,
        idempotency_key=None,
        client_timestamp=TS_OFFSET,
        fields_set={"heart_rate", "spo2"},
    )
    assert a == b
    assert metric_signature({"heart_rate", "spo2", "timestamp"}) == "heart_rate+spo2"


@pytest.mark.critical
def test_single_resend_with_client_reading_id(client: TestClient):
    payload = {
        "patient_id": "PAT-IDEM-CID",
        "device_id": "HBAND-AA:BB:CC:DD:EE:01",
        "heart_rate": 78.0,
        "client_reading_id": "room-uuid-001",
    }
    first = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert first.status_code == 200
    body = first.json()
    assert body["ingest_status"] == "accepted"
    assert body["duplicate"] is False
    assert body["client_reading_id"] == "room-uuid-001"
    assert body["patient_id"] == "PAT-IDEM-CID"
    assert "phantom_data" in body

    second = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert second.status_code == 200
    replay = second.json()
    assert replay["ingest_status"] == "duplicate"
    assert replay["duplicate"] is True
    assert replay["reading_id"] == body["reading_id"]
    assert _history_len(client, "PAT-IDEM-CID") == 1


@pytest.mark.critical
def test_single_resend_without_client_id_uses_natural_key(client: TestClient):
    payload = {
        "patient_id": "PAT-IDEM-NAT",
        "device_id": "HBAND-AA:BB:CC:DD:EE:02",
        "heart_rate": 80.0,
        "spo2": 97.0,
        "timestamp": TS,
    }
    first = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert first.status_code == 200
    assert first.json()["ingest_status"] == "accepted"

    replay_payload = dict(payload)
    replay_payload["timestamp"] = TS_OFFSET
    second = client.post(
        "/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=replay_payload
    )
    assert second.status_code == 200
    assert second.json()["ingest_status"] == "duplicate"
    assert _history_len(client, "PAT-IDEM-NAT") == 1


@pytest.mark.critical
def test_single_resend_with_idempotency_key_header(client: TestClient):
    payload = {
        "patient_id": "PAT-IDEM-HDR",
        "device_id": "HBAND-AA:BB:CC:DD:EE:03",
        "heart_rate": 72.0,
    }
    headers = {**INGEST_HEADERS, "Idempotency-Key": "work-attempt-stable-9f3a"}
    first = client.post("/api/v1/wearables/ingest", headers=headers, json=payload)
    second = client.post("/api/v1/wearables/ingest", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["ingest_status"] == "accepted"
    assert second.json()["ingest_status"] == "duplicate"
    assert _history_len(client, "PAT-IDEM-HDR") == 1


@pytest.mark.critical
def test_legacy_client_without_new_fields_still_works(client: TestClient):
    payload = {
        "patient_id": "PAT-IDEM-LEGACY",
        "device_id": "wrist_wearable",
        "heart_rate": 74.0,
        "hrv_rmssd": 40.0,
    }
    first = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    second = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    # Sem client id e sem timestamp do client: sem dedup (compatível).
    assert first.json()["ingest_status"] == "accepted"
    assert second.json()["ingest_status"] == "accepted"
    assert _history_len(client, "PAT-IDEM-LEGACY") == 2


@pytest.mark.critical
def test_distinct_metric_types_at_same_timestamp_are_not_duplicates(client: TestClient):
    base = {
        "patient_id": "PAT-IDEM-METRIC",
        "device_id": "HBAND-AA:BB:CC:DD:EE:04",
        "timestamp": TS,
        "heart_rate": 76.0,
    }
    hr = {**base, "metric_type": "heart_rate"}
    spo2 = {**base, "spo2": 96.0, "metric_type": "spo2"}
    a = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=hr)
    b = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=spo2)
    assert a.status_code == 200 and a.json()["ingest_status"] == "accepted"
    assert b.status_code == 200 and b.json()["ingest_status"] == "accepted"
    assert _history_len(client, "PAT-IDEM-METRIC") == 2


@pytest.mark.critical
def test_batch_partial_duplicates_per_item(client: TestClient):
    known = {
        "patient_id": "PAT-IDEM-BATCH",
        "device_id": "HBAND-AA:BB:CC:DD:EE:05",
        "heart_rate": 70.0,
        "timestamp": "2026-09-24T08:00:00Z",
        "client_reading_id": "room-batch-a",
    }
    seeded = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=known)
    assert seeded.status_code == 200

    batch = {
        "patient_id": "PAT-IDEM-BATCH",
        "readings": [
            known,
            {
                "patient_id": "PAT-IDEM-BATCH",
                "device_id": "HBAND-AA:BB:CC:DD:EE:05",
                "heart_rate": 71.0,
                "timestamp": "2026-09-24T08:05:00Z",
                "client_reading_id": "room-batch-b",
            },
            {
                "patient_id": "PAT-IDEM-BATCH",
                "device_id": "HBAND-AA:BB:CC:DD:EE:05",
                "heart_rate": 72.0,
                "timestamp": "2026-09-24T08:10:00Z",
            },
        ],
    }
    response = client.post(
        "/api/v1/wearables/batch-ingest", headers=INGEST_HEADERS, json=batch
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["processed_count"] == 3
    assert body["accepted_count"] == 2
    assert body["duplicate_count"] == 1
    assert body["rejected_count"] == 0
    assert [item["status"] for item in body["results"]] == [
        "duplicate",
        "accepted",
        "accepted",
    ]
    assert body["results"][0]["client_reading_id"] == "room-batch-a"
    assert body["latest_result"]["raw_telemetry"]["heart_rate_bpm"] == 72.0
    assert _history_len(client, "PAT-IDEM-BATCH") == 3


@pytest.mark.critical
def test_batch_resend_without_client_ids_uses_natural_key(client: TestClient):
    batch = {
        "patient_id": "PAT-IDEM-BATCH-NAT",
        "readings": [
            {
                "patient_id": "PAT-IDEM-BATCH-NAT",
                "device_id": "VE30-01",
                "heart_rate": 68.0,
                "timestamp": "2026-09-24T09:00:00Z",
            },
            {
                "patient_id": "PAT-IDEM-BATCH-NAT",
                "device_id": "VE30-01",
                "heart_rate": 69.0,
                "timestamp": "2026-09-24T09:05:00Z",
            },
        ],
    }
    first = client.post(
        "/api/v1/wearables/batch-ingest", headers=INGEST_HEADERS, json=batch
    )
    second = client.post(
        "/api/v1/wearables/batch-ingest", headers=INGEST_HEADERS, json=batch
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["accepted_count"] == 2
    assert second.json()["duplicate_count"] == 2
    assert second.json()["accepted_count"] == 0
    assert second.json()["processed_count"] == 2
    assert all(item["status"] == "duplicate" for item in second.json()["results"])
    assert _history_len(client, "PAT-IDEM-BATCH-NAT") == 2


@pytest.mark.critical
def test_batch_idempotency_key_replays_cached_response(client: TestClient):
    batch = {
        "patient_id": "PAT-IDEM-BATCH-HDR",
        "readings": [
            {
                "patient_id": "PAT-IDEM-BATCH-HDR",
                "heart_rate": 66.0,
                "client_reading_id": "room-hdr-1",
            }
        ],
    }
    headers = {**INGEST_HEADERS, "Idempotency-Key": "batch-flush-42"}
    first = client.post("/api/v1/wearables/batch-ingest", headers=headers, json=batch)
    second = client.post("/api/v1/wearables/batch-ingest", headers=headers, json=batch)
    assert first.status_code == second.status_code == 200
    assert first.json()["processed_count"] == 1
    assert second.json()["processed_count"] == 1
    assert _history_len(client, "PAT-IDEM-BATCH-HDR") == 1


@pytest.mark.critical
def test_legacy_batch_path_alias_supports_idempotency(client: TestClient):
    batch = {
        "patient_id": "PAT-IDEM-BATCH-ALIAS",
        "readings": [
            {
                "patient_id": "PAT-IDEM-BATCH-ALIAS",
                "heart_rate": 64.0,
                "timestamp": "2026-09-24T10:00:00Z",
            }
        ],
    }
    first = client.post(
        "/api/v1/wearables/ingest/batch", headers=INGEST_HEADERS, json=batch
    )
    second = client.post(
        "/api/v1/wearables/ingest/batch", headers=INGEST_HEADERS, json=batch
    )
    assert first.status_code == 200
    assert second.json()["results"][0]["status"] == "duplicate"


@pytest.mark.critical
def test_ingest_auth_unchanged_unauthenticated_and_read_key(client: TestClient):
    payload = {"patient_id": "PAT-IDEM-AUTH", "heart_rate": 75.0}
    missing = client.post("/api/v1/wearables/ingest", json=payload)
    assert missing.status_code == 401
    assert "API key" in missing.json()["detail"]

    denied = client.post("/api/v1/wearables/ingest", headers=READ_HEADERS, json=payload)
    assert denied.status_code == 403
    assert "wearables:write" in denied.json()["detail"]

    batch_denied = client.post(
        "/api/v1/wearables/batch-ingest",
        headers=READ_HEADERS,
        json={"patient_id": "PAT-IDEM-AUTH", "readings": [payload]},
    )
    assert batch_denied.status_code == 403

    ok = client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    assert ok.status_code == 200


@pytest.mark.critical
def test_latest_and_history_shapes_survive_resend(client: TestClient):
    payload = {
        "patient_id": "PAT-IDEM-GET",
        "device_id": "HBAND-GET-1",
        "heart_rate": 88.0,
        "timestamp": TS,
        "client_reading_id": "room-get-1",
    }
    client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)
    client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)

    latest = client.get(
        "/api/v1/wearables/patient/PAT-IDEM-GET/latest", headers=READ_HEADERS
    )
    assert latest.status_code == 200
    latest_body = latest.json()
    assert latest_body["patient_id"] == "PAT-IDEM-GET"
    assert latest_body["raw_telemetry"]["heart_rate_bpm"] == 88.0
    assert "phantom_data" in latest_body
    assert latest_body.get("client_reading_id") == "room-get-1"

    history = client.get(
        "/api/v1/wearables/patient/PAT-IDEM-GET/history?limit=10",
        headers=READ_HEADERS,
    )
    assert history.status_code == 200
    hist = history.json()
    assert hist["patient_id"] == "PAT-IDEM-GET"
    assert hist["total_records"] == 1
    assert len(hist["records"]) == 1
    assert "raw_telemetry" in hist["records"][0]
