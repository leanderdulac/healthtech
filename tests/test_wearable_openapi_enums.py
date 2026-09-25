"""OpenAPI enums do ingest Core vs docs/openapi/hband-wearable.yaml."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SECURE_ROOT = ROOT / "saude_responsiva_secure"
YAML_PATH = ROOT / "docs" / "openapi" / "hband-wearable.yaml"

if str(SECURE_ROOT) not in sys.path:
    sys.path.insert(0, str(SECURE_ROOT))

os.environ["ENVIRONMENT"] = "development"
os.environ["AUTH_DISABLED"] = "false"
os.environ["APP_MODE"] = "secure"
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32c")

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import telemetry_store  # noqa: E402

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
INGEST_HEADERS = {"X-API-Key": INGEST_KEY}


def _parse_yaml_flow_enum(yaml_text: str, field_name: str) -> List[str]:
    """Lê o primeiro `enum: [a, b]` associado a um campo no YAML 1.0.0."""
    pattern = (
        rf"(?m)^[ \t]+{re.escape(field_name)}:[ \t]*\n"
        rf"(?:[ \t]+.+\n)*?"
        rf"[ \t]+enum:[ \t]*\[([^\]]+)\]"
    )
    match = re.search(pattern, yaml_text)
    assert match, f"enum de {field_name} não encontrado em {YAML_PATH}"
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _schema_enum(node: Any) -> Optional[List[str]]:
    if not isinstance(node, dict):
        return None
    if "enum" in node:
        return list(node["enum"])
    for key in ("anyOf", "oneOf", "allOf"):
        for item in node.get(key) or ():
            found = _schema_enum(item)
            if found is not None:
                return found
    return None


def _resolve_ref(spec: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    ref = node.get("$ref")
    if not ref:
        return node
    assert ref.startswith("#/"), ref
    cursor: Any = spec
    for part in ref[2:].split("/"):
        cursor = cursor[part]
    return cursor


def _openapi_spec() -> Dict[str, Any]:
    get_settings.cache_clear()
    application = create_app()
    return application.openapi()


def _ingest_and_batch_item_schemas(spec: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    schemas = spec["components"]["schemas"]
    ingest = schemas["WearableTelemetryRequest"]
    batch = schemas["WearableBatchIngestRequest"]
    item_schema = _resolve_ref(spec, batch["properties"]["readings"]["items"])
    return ingest, item_schema


@pytest.fixture
def client():
    get_settings.cache_clear()
    telemetry_store.clear_all()
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
    telemetry_store.clear_all()
    get_settings.cache_clear()


def test_openapi_ingest_source_enum_matches_yaml():
    yaml_text = YAML_PATH.read_text(encoding="utf-8")
    expected = _parse_yaml_flow_enum(yaml_text, "ingest_source")
    spec = _openapi_spec()
    ingest, batch_item = _ingest_and_batch_item_schemas(spec)

    ingest_enum = _schema_enum(ingest["properties"]["ingest_source"])
    item_enum = _schema_enum(batch_item["properties"]["ingest_source"])
    assert ingest_enum == expected
    assert item_enum == expected

    for path in ("/api/v1/wearables/batch-ingest", "/api/v1/wearables/ingest/batch"):
        body = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]
        assert body["schema"]["$ref"].endswith("WearableBatchIngestRequest")


def test_openapi_filter_type_enum_matches_yaml():
    yaml_text = YAML_PATH.read_text(encoding="utf-8")
    expected = _parse_yaml_flow_enum(yaml_text, "filter_type")
    spec = _openapi_spec()
    ingest, batch_item = _ingest_and_batch_item_schemas(spec)
    assert _schema_enum(ingest["properties"]["filter_type"]) == expected
    assert _schema_enum(batch_item["properties"]["filter_type"]) == expected


def test_null_and_omitted_ingest_source_still_default(client: TestClient):
    omitted = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json={"patient_id": "PAT-ENUM-OMIT", "heart_rate": 72.0},
    )
    assert omitted.status_code == 200

    explicit_null = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-ENUM-NULL",
            "heart_rate": 73.0,
            "ingest_source": None,
        },
    )
    assert explicit_null.status_code == 200


def test_invalid_ingest_source_is_422_on_ingest_and_whole_batch(client: TestClient):
    single = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-ENUM-BAD",
            "heart_rate": 74.0,
            "ingest_source": "wifi_watch",
        },
    )
    assert single.status_code == 422

    batch = {
        "patient_id": "PAT-ENUM-BATCH",
        "readings": [
            {
                "patient_id": "PAT-ENUM-BATCH",
                "heart_rate": 70.0,
                "ingest_source": "ble_sim",
            },
            {
                "patient_id": "PAT-ENUM-BATCH",
                "heart_rate": 71.0,
                "ingest_source": "not-a-source",
            },
        ],
    }
    for path in ("/api/v1/wearables/batch-ingest", "/api/v1/wearables/ingest/batch"):
        response = client.post(path, headers=INGEST_HEADERS, json=batch)
        assert response.status_code == 422, path
