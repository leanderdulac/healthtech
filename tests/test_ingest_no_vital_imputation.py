"""Nunca inventar vitais no ingest/matriz de alertas (PR #22).

Caso real (revisão 00032-map): leitura só com FC 72 + SpO2 88 disparou 4 regras
críticas porque o ingest secure preenchia PA 83.9/63.9 por um "phantom"
heurístico marcado reliable=True e temperatura 33.0 °C por default. Sinal
ausente é desconhecido, não valor: só n2u_034 (hipoxemia) é legítima.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterator, Tuple

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
from app.services.signal_core import process_ingest_frame  # noqa: E402
from src.clinical_intelligence.alert_ingest import (  # noqa: E402
    PHANTOM_VITALS_ENV,
    assess_ingest_alerts,
    vitals_from_ingest_context,
)

INGEST_HEADERS = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
READ_HEADERS = {"X-API-Key": "ht_read_test_key_32chars_long_token"}

FORBIDDEN_CATEGORIES = {"pa_baixa", "temperatura", "infeccao"}
# Chaves que só podem ter valor se o cliente enviou o sinal correspondente.
IMPUTABLE_KEYS = {
    "systolic_bp",
    "diastolic_bp",
    "map_mmhg",
    "blood_pressure_sys",
    "blood_pressure_dia",
    "pas",
    "pad",
    "temp_c",
    "skin_temp",
    "skin_temp_celsius",
    "body_temp_c",
    "glucose_mgdl",
}

# Phantom legado exatamente como o ingest secure gerava para FC 72 / pele 33.
LEGACY_PHANTOM = {
    "map_mmhg": {"estimate": 70.6, "reliable": True},
    "systolic_bp": {"estimate": 83.9, "reliable": True},
    "diastolic_bp": {"estimate": 63.9, "reliable": True},
}


@pytest.fixture(autouse=True)
def _phantom_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PHANTOM_VITALS_ENV, raising=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    telemetry_store.clear_all()
    with TestClient(create_app()) as test_client:
        yield test_client
    telemetry_store.clear_all()
    get_settings.cache_clear()


def _walk(obj: Any, path: str = "") -> Iterator[Tuple[str, str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, str(k), v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _assert_no_imputed_bp_or_temp(obj: Any) -> None:
    leaked = [
        f"{p}.{k}={v!r}"
        for p, k, v in _walk(obj)
        if k in IMPUTABLE_KEYS and v is not None and v != {}
    ]
    assert not leaked, f"vitais imputados na resposta/registro: {leaked}"


def _rule_ids(alerts: dict) -> list:
    return [h["rule_id"] for h in alerts.get("rule_hits") or []]


# --- matriz (src.clinical_intelligence.alert_ingest) -----------------------


def test_hr_spo2_only_fires_exactly_hypoxemia():
    alerts = assess_ingest_alerts(heart_rate=72, spo2=88)
    assert alerts["is_true_alert"] is True
    assert alerts["severity"] == "critico"
    assert alerts["primary_rule_id"] == "n2u_034"
    assert _rule_ids(alerts) == ["n2u_034"]
    cats = {h["category"] for h in alerts["rule_hits"]}
    assert not cats & FORBIDDEN_CATEGORIES
    meta = alerts["source_meta"]
    assert meta["bp_source"] == "absent"
    assert meta["bp_reliable"] is False
    assert meta["phantom_vitals_enabled"] is False
    used = alerts["vitals_used"]
    assert used["hr"] == 72 and used["spo2"] == 88
    for k in ("pas", "pad", "temp_c", "glucose_mgdl", "steps_drop_pct", "sleep_worsen_pct"):
        assert used[k] is None, k


def test_phantom_bp_is_ignored_without_opt_in():
    """Mesmo recebendo o phantom 'reliable' antigo, sem opt-in ele não entra."""
    v, meta = vitals_from_ingest_context(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert v.pas is None and v.pad is None and v.temp_c is None
    assert v.sleep_worsen_pct is None and v.steps_drop_pct is None
    assert meta["bp_source"] == "absent" and meta["bp_reliable"] is False

    alerts = assess_ingest_alerts(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert _rule_ids(alerts) == ["n2u_034"]
    assert alerts["primary_rule_id"] == "n2u_034"


def test_legacy_phantom_only_with_explicit_opt_in(monkeypatch: pytest.MonkeyPatch):
    """Modo demo legado continua existindo, mas só atrás do flag explícito."""
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    v, meta = vitals_from_ingest_context(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert v.pas == pytest.approx(83.9)
    assert meta["bp_source"] == "phantom"
    assert meta["phantom_vitals_enabled"] is True


def test_real_low_bp_and_low_spo2_still_fire_n2u_021():
    alerts = assess_ingest_alerts(
        heart_rate=72,
        spo2=88,
        hband_ext={"blood_pressure_sys": 82, "blood_pressure_dia": 50},
    )
    assert alerts["severity"] == "critico"
    assert alerts["primary_rule_id"] == "n2u_021"
    assert {"n2u_021", "n2u_034"} <= set(_rule_ids(alerts))
    assert alerts["source_meta"]["bp_source"] == "measured"
    assert alerts["source_meta"]["bp_reliable"] is True
    assert alerts["vitals_used"]["pas"] == 82
    assert alerts["vitals_used"]["temp_c"] is None


def test_measured_temperature_still_used():
    v, _ = vitals_from_ingest_context(heart_rate=72, spo2=98, skin_temp=33.4, hband_ext={"body_temp_c": 36.9})
    assert v.temp_c == pytest.approx(36.9)
    v2, _ = vitals_from_ingest_context(heart_rate=72, spo2=98, hband_ext={"body_temp_c": 38.4})
    assert v2.temp_c == pytest.approx(38.4)


# --- API secure (saude_responsiva_secure) -----------------------------------


def test_signal_core_does_not_default_vitals():
    frame = process_ingest_frame({"patient_id": "PAT-NOIMP-SC", "heart_rate": 72.0, "spo2": 88.0})
    assert frame["phantom_data"] == {}
    raw = frame["raw_telemetry"]
    assert raw["skin_temp_celsius"] is None
    assert raw["hrv_rmssd_ms"] is None
    assert raw["activity_level"] is None
    ca = frame["clinical_alerts"]
    assert _rule_ids(ca) == ["n2u_034"]
    assert ca["source_meta"]["bp_reliable"] is False
    _assert_no_imputed_bp_or_temp(frame)


def test_secure_ingest_hr_spo2_only_exactly_n2u_034(client: TestClient):
    res = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-NOIMP-001",
            "device_id": "noimp-device",
            "heart_rate": 72,
            "spo2": 88,
            "ingest_source": "http",
            "client_reading_id": "noimp-001",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    ca = body["clinical_alerts"]
    assert ca["severity"] == "critico"
    assert ca["primary_rule_id"] == "n2u_034"
    assert _rule_ids(ca) == ["n2u_034"]
    assert not {h["category"] for h in ca["rule_hits"]} & FORBIDDEN_CATEGORIES
    assert ca["source_meta"]["bp_reliable"] is False
    assert body["phantom_data"] == {}
    _assert_no_imputed_bp_or_temp(body)

    hist = client.get(
        "/api/v1/wearables/patient/PAT-NOIMP-001/history?limit=10",
        headers=READ_HEADERS,
    )
    assert hist.status_code == 200, hist.text
    _assert_no_imputed_bp_or_temp(hist.json())


def test_secure_ingest_real_low_bp_still_fires_n2u_021(client: TestClient):
    res = client.post(
        "/api/v1/wearables/ingest",
        headers=INGEST_HEADERS,
        json={
            "patient_id": "PAT-NOIMP-BP",
            "heart_rate": 72,
            "spo2": 88,
            "blood_pressure_sys": 82,
            "blood_pressure_dia": 50,
            "ingest_source": "http",
            "client_reading_id": "noimp-bp-001",
        },
    )
    assert res.status_code == 200, res.text
    ca = res.json()["clinical_alerts"]
    assert ca["severity"] == "critico"
    assert ca["primary_rule_id"] == "n2u_021"
    assert {"n2u_021", "n2u_034"} <= set(_rule_ids(ca))
    assert ca["source_meta"]["bp_source"] == "measured"
    assert ca["source_meta"]["bp_reliable"] is True
    assert ca["vitals_used"]["temp_c"] is None
