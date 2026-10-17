"""device_label: apelido do aparelho (ex.: "iPhone de LFM") no ingest e na frota.

Decisão: acima de 64 caracteres o rótulo é **truncado**, não rejeitado.
O rótulo é cosmético e não pode derrubar a leitura clínica que vem junto.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.schemas import (
    DEVICE_LABEL_MAX_LENGTH,
    WearableTelemetryRequest,
    normalize_device_label,
)
from app.services import durable_readings
from tests.test_wearable_durable_store import (  # noqa: F401  (fixtures)
    INGEST_HEADERS,
    READ_HEADERS,
    durable_client,
    durable_engine,
    pytest_generate_tests,
)

TS1 = "2026-10-17T04:00:00.000Z"
TS2 = "2026-10-17T04:05:00.000Z"


def _ingest(client, **overrides):
    payload = {
        "patient_id": "PAT-LABEL-1",
        "device_id": "VE30-AA:BB:CC:DD:EE:01",
        "heart_rate": 72.0,
        "timestamp": TS1,
        "ingest_source": "ble_hband",
    }
    payload.update(overrides)
    return client.post("/api/v1/wearables/ingest", headers=INGEST_HEADERS, json=payload)


def _device(client, device_id):
    resp = client.get(
        "/api/v1/wearables/devices",
        headers=READ_HEADERS,
        params={"q": device_id, "include_synthetic": "true"},
    )
    assert resp.status_code == 200, resp.text
    rows = [row for row in resp.json()["devices"] if row["device_id"] == device_id]
    assert len(rows) == 1, resp.json()
    return rows[0]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("iPhone de LFM", "iPhone de LFM"),
        ("  iPhone   de\tLFM  ", "iPhone de LFM"),
        ("", None),
        ("   ", None),
        (None, None),
        ("x" * 80, "x" * DEVICE_LABEL_MAX_LENGTH),
    ],
)
def test_normalize_device_label(raw, expected):
    assert normalize_device_label(raw) == expected


def test_schema_accepts_absent_and_truncates_overlong():
    base = {"patient_id": "PAT-1", "heart_rate": 70.0}
    assert WearableTelemetryRequest(**base).device_label is None
    long = WearableTelemetryRequest(**base, device_label="A" * 200)
    assert long.device_label == "A" * DEVICE_LABEL_MAX_LENGTH


def test_schema_rejects_non_string():
    with pytest.raises(Exception):
        WearableTelemetryRequest(patient_id="PAT-1", heart_rate=70.0, device_label={"x": 1})


def test_openapi_exposes_device_label(durable_client):
    spec = durable_client.get("/openapi.json").json()
    props = spec["components"]["schemas"]["WearableTelemetryRequest"]["properties"]
    assert "device_label" in props
    assert props["device_label"].get("maxLength") == DEVICE_LABEL_MAX_LENGTH


def test_schema_adds_device_label_column(durable_engine, backend):
    durable_readings.apply_schema(durable_engine)
    durable_readings.apply_schema(durable_engine)  # idempotente
    with durable_engine.connect() as conn:
        if backend == "sqlite":
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(wearable_readings)"))}
        else:
            cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'wearable_readings'"
                    )
                )
            }
    assert "device_label" in cols


@pytest.mark.critical
def test_ingest_persists_and_lists_device_label(durable_client, durable_engine):
    resp = _ingest(durable_client, device_label="  iPhone de LFM ", client_reading_id="lbl-1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ingest_status"] == "accepted"
    assert body["device_label"] == "iPhone de LFM"

    with durable_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT device_label FROM wearable_readings WHERE client_reading_id = 'lbl-1'")
        ).scalar_one()
    assert stored == "iPhone de LFM"

    row = _device(durable_client, "VE30-AA:BB:CC:DD:EE:01")
    assert row["device_label"] == "iPhone de LFM"

    latest = durable_client.get(
        "/api/v1/wearables/patient/PAT-LABEL-1/latest", headers=READ_HEADERS
    )
    assert latest.status_code == 200, latest.text
    assert latest.json()["device_label"] == "iPhone de LFM"


def test_latest_label_survives_reading_without_label(durable_client):
    assert _ingest(durable_client, device_label="iPhone de LFM", client_reading_id="lbl-a").status_code == 200
    resp = _ingest(durable_client, timestamp=TS2, heart_rate=75.0, client_reading_id="lbl-b")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("device_label") is None
    row = _device(durable_client, "VE30-AA:BB:CC:DD:EE:01")
    assert row["device_label"] == "iPhone de LFM"


def test_newer_label_wins(durable_client):
    assert _ingest(durable_client, device_label="iPhone antigo", client_reading_id="lbl-o").status_code == 200
    assert _ingest(
        durable_client, device_label="iPhone de LFM", timestamp=TS2, client_reading_id="lbl-n"
    ).status_code == 200
    assert _device(durable_client, "VE30-AA:BB:CC:DD:EE:01")["device_label"] == "iPhone de LFM"


def test_ingest_without_label_still_ok(durable_client):
    resp = _ingest(durable_client, device_id="VE30-NO-LABEL", client_reading_id="nolbl-1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ingest_status"] == "accepted"
    assert _device(durable_client, "VE30-NO-LABEL")["device_label"] is None


def test_overlong_label_is_truncated_not_rejected(durable_client):
    resp = _ingest(durable_client, device_label="L" * 300, client_reading_id="long-1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["device_label"] == "L" * DEVICE_LABEL_MAX_LENGTH


def test_batch_ingest_carries_device_label(durable_client):
    resp = durable_client.post(
        "/api/v1/wearables/batch-ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-LABEL-1",
            "readings": [
                {
                    "patient_id": "PAT-LABEL-1",
                    "device_id": "VE30-BATCH",
                    "heart_rate": 70.0,
                    "timestamp": TS1,
                    "client_reading_id": "b-1",
                    "device_label": "Galaxy S21+ de LFM",
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted_count"] == 1
    assert _device(durable_client, "VE30-BATCH")["device_label"] == "Galaxy S21+ de LFM"


def test_device_label_does_not_change_dedup(durable_client):
    first = _ingest(durable_client, device_label="iPhone de LFM", client_reading_id="dup-1")
    replay = _ingest(durable_client, device_label="outro nome", client_reading_id="dup-1")
    assert first.json()["ingest_status"] == "accepted"
    assert replay.json()["ingest_status"] == "duplicate"
    assert replay.json()["device_label"] == "iPhone de LFM"
