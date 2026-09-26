"""Proveniência de `clinical_alerts.context_informed` (revisão Rafael — PR #22).

1) Nunca depende de phantom/estimativa, nem no modo demo em dev autorizado:
   cada campo vem só de dado recebido e MEDIDO na leitura atual (e, para
   comparações, de valor medido comparável no histórico). consecutive_valid só
   conta com par medido comparável; senão null.
2) "Presente" == "consumido pelo cálculo": sinal enviado mas não consumido pela
   matriz (ex.: `_hband.preprandial`) sai null, nunca um default (`false`)
   apresentado como conhecido.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SECURE_ROOT = Path(__file__).resolve().parents[1] / "saude_responsiva_secure"
if str(SECURE_ROOT) not in sys.path:
    sys.path.insert(0, str(SECURE_ROOT))

from app.services.signal_core import process_ingest_frame  # noqa: E402
from src.clinical_intelligence.alert_ingest import (  # noqa: E402
    CONTEXT_INFORMED_FIELDS,
    CONTEXT_SOURCES,
    PHANTOM_VITALS_ENV,
    assess_ingest_alerts,
    context_informed,
    reset_phantom_guard_warnings,
    vitals_from_ingest_context,
)

PHANTOM_GLU_250 = {
    "systolic_bp": {"estimate": 83.9, "reliable": True},
    "diastolic_bp": {"estimate": 63.9, "reliable": True},
    "glucose_mgdl": {"estimate": 250.0, "reliable": True},
}
_CLOUD_RUN_VARS = ("K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for var in (PHANTOM_VITALS_ENV, "APP_ENV", *_CLOUD_RUN_VARS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    reset_phantom_guard_warnings()
    yield
    reset_phantom_guard_warnings()


@pytest.fixture
def dev_phantom(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")


def _ctx(**kw):
    return assess_ingest_alerts(**kw)["context_informed"]


# --- (a) phantom nunca alimenta context_informed ------------------------------


def test_a_phantom_glucose_equal_previous_does_not_confirm_consecutive(dev_phantom):
    """Cenário do Rafael: phantom 250 vs previous_reading.glucose_mgdl=250."""
    raw = {"heart_rate": 72, "previous_reading": {"glucose_mgdl": 250}}
    alerts = assess_ingest_alerts(heart_rate=72, phantom=PHANTOM_GLU_250, raw_telemetry=raw)
    meta = alerts["source_meta"]
    assert meta["phantom_vitals_enabled"] is True
    assert meta["glucose_source"] == "phantom" and meta["bp_source"] == "phantom"
    ctx = alerts["context_informed"]
    assert ctx["consecutive_valid"] is None
    assert ctx["glucose_delta"] is None
    assert ctx["map_approx"] is None and ctx["pulse_pressure"] is None
    assert ctx["pas_rise_vs_basal"] is None and ctx["pas_drop_vs_basal"] is None
    phantom_values = {250.0, 83.9, 63.9}
    for key, value in ctx.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            assert float(value) not in phantom_values, (key, value)
    assert all(v is None for v in ctx.values()), ctx


def test_a_phantom_with_basal_and_previous_bp_glucose_all_comparisons_null(dev_phantom):
    raw = {
        "heart_rate": 72,
        "basal": {"pas": 120, "glucose_mgdl": 100},
        "previous_reading": {"glucose_mgdl": 245, "blood_pressure_sys": 84},
    }
    ctx = _ctx(heart_rate=72, phantom=PHANTOM_GLU_250, raw_telemetry=raw)
    for key in ("consecutive_valid", "glucose_delta", "pas_rise_vs_basal", "pas_drop_vs_basal",
                "map_approx", "pulse_pressure"):
        assert ctx[key] is None, (key, ctx)


def test_a_measured_spo2_still_counts_when_phantom_glucose_present(dev_phantom):
    """Par medido real (SpO2) continua valendo; a glicose phantom é ignorada."""
    raw = {"heart_rate": 72, "spo2": 95, "previous_reading": {"spo2": 95, "glucose_mgdl": 250}}
    ctx = _ctx(heart_rate=72, spo2=95, phantom=PHANTOM_GLU_250, raw_telemetry=raw)
    assert ctx["consecutive_valid"] == 2
    assert ctx["glucose_delta"] is None


def test_a_signal_core_dev_phantom_never_in_context_informed(dev_phantom):
    frame = process_ingest_frame({
        "patient_id": "PAT-CTX-PROV-DEV",
        "heart_rate": 72.0,
        "previous_reading": {"glucose_mgdl": 100, "spo2": 97},
    })
    assert frame["phantom_data"], "dev autorizado deve gerar phantom"
    ctx = frame["clinical_alerts"]["context_informed"]
    assert all(v is None for v in ctx.values()), ctx


# --- (b) presente mas não consumido → null ------------------------------------


def test_b_hband_preprandial_not_consumed_fasting_is_null_not_false():
    hband = {"preprandial": True}
    raw = {"heart_rate": 72, "spo2": 97, "_hband": hband}
    v, _ = vitals_from_ingest_context(heart_rate=72, spo2=97, hband_ext=hband, raw_telemetry=raw)
    assert v.fasting is False  # o cálculo NÃO consome _hband.preprandial (regra inalterada)
    ctx = _ctx(heart_rate=72, spo2=97, hband_ext=hband, raw_telemetry=raw)
    assert ctx["fasting"] is None


def test_b_signal_core_hband_preprandial_fasting_null():
    frame = process_ingest_frame({
        "patient_id": "PAT-CTX-PROV-PREPR",
        "heart_rate": 72.0,
        "spo2": 97.0,
        "_hband": {"preprandial": True},
    })
    assert frame["clinical_alerts"]["context_informed"]["fasting"] is None


def test_b_hband_fall_suspected_not_consumed_steps_interrupted_null():
    hband = {"fall_suspected": True}
    raw = {"heart_rate": 72, "_hband": hband}
    v, _ = vitals_from_ingest_context(heart_rate=72, hband_ext=hband, raw_telemetry=raw)
    assert v.steps_interrupted is False
    assert _ctx(heart_rate=72, hband_ext=hband, raw_telemetry=raw)["steps_interrupted"] is None


@pytest.mark.parametrize("alias", ["fasting_or_preprandial", "at_rest", "steps_drop_consecutive_days",
                                   "consecutive_count"])
def test_b_schema_aliases_not_consumed_stay_null(alias):
    raw = {"heart_rate": 72, alias: 2 if "days" in alias or "count" in alias else True}
    ctx = _ctx(heart_rate=72, raw_telemetry=raw)
    assert all(v is None for v in ctx.values()), (alias, ctx)


_BOOL_FIELDS = ("consciousness_altered", "rest", "fasting", "steps_interrupted")


@pytest.mark.parametrize(
    "field,where,key",
    [(f, w, k) for f in _BOOL_FIELDS for (w, k) in CONTEXT_SOURCES[f]],
)
def test_b_every_declared_source_is_consumed_and_exported(field, where, key):
    """Toda fonte declarada muda o cálculo E aparece no exportador (true)."""
    raw = {"heart_rate": 72}
    hband = {}
    (raw if where == "raw" else hband)[key] = True
    v, meta = vitals_from_ingest_context(heart_rate=72, hband_ext=hband, raw_telemetry=raw)
    assert getattr(v, field) is True
    ctx = context_informed(v, meta, hband_ext=hband, raw_telemetry=raw)
    assert ctx[field] is True


@pytest.mark.parametrize("field", _BOOL_FIELDS)
def test_b_declared_source_false_is_known_false(field):
    where, key = CONTEXT_SOURCES[field][0]
    raw = {"heart_rate": 72}
    hband = {}
    (raw if where == "raw" else hband)[key] = False
    ctx = _ctx(heart_rate=72, hband_ext=hband, raw_telemetry=raw)
    assert ctx[field] is False


@pytest.mark.parametrize(
    "field,where,key,value",
    [("sleep_hours", w, k, 5.5) for (w, k) in CONTEXT_SOURCES["sleep_hours"]]
    + [("steps_drop_days", w, k, 3) for (w, k) in CONTEXT_SOURCES["steps_drop_days"]],
)
def test_b_numeric_sources_consumed_and_exported(field, where, key, value):
    raw = {"heart_rate": 72}
    hband = {}
    (raw if where == "raw" else hband)[key] = value
    v, meta = vitals_from_ingest_context(heart_rate=72, hband_ext=hband, raw_telemetry=raw)
    assert getattr(v, field) == value
    assert context_informed(v, meta, hband_ext=hband, raw_telemetry=raw)[field] == value


# --- (c) histórico sem medida comparável → comparações null -------------------


def test_c_previous_without_comparable_measurement_is_null():
    raw = {
        "heart_rate": 80,
        "spo2": 97,
        "glucose_mgdl": 180,
        "previous_reading": {"heart_rate": 78},
    }
    ctx = _ctx(heart_rate=80, spo2=97, raw_telemetry=raw)
    assert ctx["consecutive_valid"] is None
    assert ctx["glucose_delta"] is None


def test_c_previous_glucose_but_no_current_glucose_is_null():
    raw = {"heart_rate": 80, "spo2": 97, "previous_reading": {"glucose_mgdl": 170}}
    ctx = _ctx(heart_rate=80, spo2=97, raw_telemetry=raw)
    assert ctx["consecutive_valid"] is None and ctx["glucose_delta"] is None


def test_c_previous_spo2_but_no_current_spo2_and_no_glucose_pair_is_null():
    raw = {"heart_rate": 80, "glucose_mgdl": 180, "previous_reading": {"spo2": 97}}
    ctx = _ctx(heart_rate=80, raw_telemetry=raw)
    assert ctx["consecutive_valid"] is None and ctx["glucose_delta"] is None


def test_c_basal_without_pas_gives_null_bp_comparisons():
    raw = {
        "heart_rate": 80,
        "blood_pressure_sys": 150,
        "blood_pressure_dia": 90,
        "basal": {"hr": 60},
    }
    ctx = _ctx(heart_rate=80, raw_telemetry=raw)
    assert ctx["pas_rise_vs_basal"] is None and ctx["pas_drop_vs_basal"] is None
    assert ctx["map_approx"] == pytest.approx(110.0)  # PA atual medida continua


def test_c_comparable_but_not_matching_is_known_one():
    raw = {"heart_rate": 80, "spo2": 88, "previous_reading": {"spo2": 97}}
    assert _ctx(heart_rate=80, spo2=88, raw_telemetry=raw)["consecutive_valid"] == 1


def test_c_measured_glucose_pair_confirms_and_delta():
    raw = {"heart_rate": 80, "glucose_mgdl": 180, "previous_reading": {"glucose": 170}}
    ctx = _ctx(heart_rate=80, raw_telemetry=raw)
    assert ctx["consecutive_valid"] == 2 and ctx["glucose_delta"] == pytest.approx(10.0)


@pytest.mark.parametrize(
    "raw",
    [
        {"spo2": 97, "previous_reading": {"spo2": 97}},
        {"spo2": 88, "previous_reading": {"spo2": 97}},
        {"glucose_mgdl": 180, "previous_vitals": {"glucose_mgdl": 170}},
        {"glucose_mgdl": 180, "spo2": 90, "previous_reading": {"glucose_mgdl": 120, "spo2": 97}},
    ],
)
def test_c_without_phantom_export_matches_rule_input(raw):
    """Fora do modo demo, quando há par medido, o exportado == o que as regras usaram."""
    raw = {"heart_rate": 80, **raw}
    v, meta = vitals_from_ingest_context(heart_rate=80, spo2=raw.get("spo2"), raw_telemetry=raw)
    ctx = context_informed(v, meta, raw_telemetry=raw)
    assert ctx["consecutive_valid"] == v.consecutive_valid


def test_fields_order_stable():
    assert tuple(_ctx(heart_rate=72)) == CONTEXT_INFORMED_FIELDS
