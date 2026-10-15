"""Isolamento do modo phantom/demo (revisão Rafael — PR #22).

Phantom (PA/glicose estimadas + defaults de sono/passos/FC-basal) só pode
rodar com ALERT_ALLOW_PHANTOM_VITALS=1 E ambiente de desenvolvimento
explícito, fora do Cloud Run. Em produção/Cloud Run é impossível: o flag e o
parâmetro allow_phantom_vitals=True são ignorados e um WARNING é emitido uma
única vez por motivo.

Também cobre `context_informed`: contexto enviado pelo cliente que saiu do
vitals_used legado, agora sem nenhum valor imputado.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

SECURE_ROOT = Path(__file__).resolve().parents[1] / "saude_responsiva_secure"
if str(SECURE_ROOT) not in sys.path:
    sys.path.insert(0, str(SECURE_ROOT))

from app.services.signal_core import process_ingest_frame  # noqa: E402
from src.clinical_intelligence import alert_ingest  # noqa: E402
from src.clinical_intelligence.alert_ingest import (  # noqa: E402
    CONTEXT_INFORMED_FIELDS,
    PHANTOM_VITALS_ENV,
    assess_ingest_alerts,
    phantom_vitals_block_reason,
    phantom_vitals_enabled,
    reset_phantom_guard_warnings,
    vitals_from_ingest_context,
)

LOGGER = alert_ingest.logger.name

LEGACY_PHANTOM = {
    "map_mmhg": {"estimate": 70.6, "reliable": True},
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


def _blocked_warnings(caplog: pytest.LogCaptureFixture) -> list:
    return [
        r for r in caplog.records
        if r.name == LOGGER and r.levelno == logging.WARNING and "phantom_vitals=blocked" in r.getMessage()
    ]


def _rule_ids(alerts: dict) -> list:
    return [h["rule_id"] for h in alerts.get("rule_hits") or []]


def _assert_measured_only(v, meta) -> None:
    assert v.pas is None and v.pad is None and v.glucose_mgdl is None
    assert v.sleep_worsen_pct is None and v.steps_drop_pct is None
    assert meta["bp_source"] == "absent" and meta["glucose_source"] == "absent"
    assert meta["phantom_vitals_enabled"] is False


# --- produção: impossível ----------------------------------------------------


def test_production_with_flag_on_blocks_phantom_and_warns_once(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    caplog.set_level(logging.WARNING, logger=LOGGER)

    assert phantom_vitals_enabled() is False
    v, meta = vitals_from_ingest_context(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    _assert_measured_only(v, meta)
    alerts = assess_ingest_alerts(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert _rule_ids(alerts) == ["n2u_034"]

    warns = _blocked_warnings(caplog)
    assert len(warns) == 1, [w.getMessage() for w in warns]
    assert "reason=production(ENVIRONMENT=production)" in warns[0].getMessage()
    assert "requested_via=env" in warns[0].getMessage()


def test_production_ignores_allow_phantom_vitals_param(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    caplog.set_level(logging.WARNING, logger=LOGGER)

    v, meta = vitals_from_ingest_context(
        heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM, allow_phantom_vitals=True
    )
    _assert_measured_only(v, meta)
    alerts = assess_ingest_alerts(
        heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM, allow_phantom_vitals=True
    )
    assert _rule_ids(alerts) == ["n2u_034"]
    assert alerts["source_meta"]["phantom_vitals_enabled"] is False
    assert alerts["vitals_used"]["pas"] is None
    assert alerts["vitals_used"]["glucose_mgdl"] is None

    warns = _blocked_warnings(caplog)
    assert len(warns) == 1
    assert "requested_via=param" in warns[0].getMessage()


def test_production_param_true_without_flag_still_blocked(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prod")
    v, meta = vitals_from_ingest_context(
        heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM, allow_phantom_vitals=True
    )
    _assert_measured_only(v, meta)


@pytest.mark.parametrize("marker", _CLOUD_RUN_VARS)
def test_cloud_run_blocks_even_if_environment_says_dev(monkeypatch, marker):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    monkeypatch.setenv(marker, "healthtech-secure-api")
    assert phantom_vitals_block_reason() == f"cloud_run({marker})"
    assert phantom_vitals_enabled(True) is False
    v, meta = vitals_from_ingest_context(
        heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM, allow_phantom_vitals=True
    )
    _assert_measured_only(v, meta)


@pytest.mark.parametrize(
    "env,app_env,expected",
    [
        (None, None, "environment_unset"),
        ("staging", None, "production(ENVIRONMENT=staging)"),
        ("qa", None, "environment_not_dev(ENVIRONMENT=qa)"),
        ("development", "production", "production(APP_ENV=production)"),
        (None, "prod", "production(APP_ENV=prod)"),
    ],
)
def test_non_authorized_environments_block(monkeypatch, env, app_env, expected):
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    if env is None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ENVIRONMENT", env)
    if app_env is not None:
        monkeypatch.setenv("APP_ENV", app_env)
    assert phantom_vitals_block_reason() == expected
    assert phantom_vitals_enabled() is False
    assert phantom_vitals_enabled(True) is False


def test_secure_signal_core_in_production_has_no_phantom(monkeypatch, caplog):
    """Caminho real do ingest secure (Cloud Run): flag ligado não gera phantom."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("K_SERVICE", "healthtech-secure-api")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    caplog.set_level(logging.WARNING, logger=LOGGER)
    frame = process_ingest_frame({"patient_id": "PAT-PHISO-PROD", "heart_rate": 72.0, "spo2": 88.0})
    assert frame["phantom_data"] == {}
    ca = frame["clinical_alerts"]
    assert _rule_ids(ca) == ["n2u_034"]
    assert ca["source_meta"]["phantom_vitals_enabled"] is False
    assert ca["source_meta"]["bp_source"] == "absent"
    assert len(_blocked_warnings(caplog)) == 1


def test_no_request_no_warning(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "production")
    caplog.set_level(logging.WARNING, logger=LOGGER)
    assess_ingest_alerts(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert phantom_vitals_enabled(False) is False
    assert _blocked_warnings(caplog) == []


# --- dev autorizado: continua funcionando ------------------------------------


def test_dev_authorized_flag_enables_phantom(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    caplog.set_level(logging.WARNING, logger=LOGGER)
    assert phantom_vitals_block_reason() is None
    assert phantom_vitals_enabled() is True
    v, meta = vitals_from_ingest_context(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert v.pas == pytest.approx(83.9)
    assert v.pad == pytest.approx(63.9)
    assert v.glucose_mgdl == pytest.approx(250.0)
    assert v.sleep_worsen_pct == 5.0 and v.steps_drop_pct == 5.0
    assert meta["bp_source"] == "phantom" and meta["phantom_vitals_enabled"] is True
    assert _blocked_warnings(caplog) == []


def test_dev_authorized_signal_core_generates_phantom(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "true")
    frame = process_ingest_frame({"patient_id": "PAT-PHISO-DEV", "heart_rate": 72.0, "spo2": 88.0})
    assert frame["phantom_data"], "modo demo autorizado deve gerar phantom"
    assert frame["clinical_alerts"]["source_meta"]["phantom_vitals_enabled"] is True


def test_dev_param_true_requires_flag_too(monkeypatch, caplog):
    """Parâmetro sozinho não basta: exige flag + dev (AMBOS)."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    v, meta = vitals_from_ingest_context(
        heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM, allow_phantom_vitals=True
    )
    _assert_measured_only(v, meta)
    warns = _blocked_warnings(caplog)
    assert len(warns) == 1
    assert f"flag_{PHANTOM_VITALS_ENV}_not_set" in warns[0].getMessage()


def test_dev_param_false_overrides_flag(monkeypatch):
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    v, meta = vitals_from_ingest_context(
        heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM, allow_phantom_vitals=False
    )
    _assert_measured_only(v, meta)


# --- context_informed: contexto enviado, nunca imputado ------------------------


def test_context_informed_all_none_when_client_sends_only_hr_spo2():
    alerts = assess_ingest_alerts(heart_rate=72, spo2=88, raw_telemetry={"heart_rate": 72, "spo2": 88})
    ctx = alerts["context_informed"]
    assert tuple(ctx) == CONTEXT_INFORMED_FIELDS
    assert all(v is None for v in ctx.values()), ctx


def test_context_informed_restores_client_context_without_imputation():
    raw = {
        "heart_rate": 80,
        "spo2": 97,
        "blood_pressure_sys": 150,
        "blood_pressure_dia": 90,
        "glucose_mgdl": 180,
        "consciousness_altered": False,
        "fasting": True,
        "rest": True,
        "sleep_hours": 5.5,
        "steps_drop_days": 3,
        "steps_interrupted": True,
        "basal": {"pas": 130},
        "previous_reading": {"glucose_mgdl": 170, "spo2": 97},
    }
    alerts = assess_ingest_alerts(heart_rate=80, spo2=97, raw_telemetry=raw)
    ctx = alerts["context_informed"]
    assert ctx["consciousness_altered"] is False
    assert ctx["fasting"] is True
    assert ctx["rest"] is True
    assert ctx["sleep_hours"] == 5.5
    assert ctx["steps_drop_days"] == 3
    assert ctx["steps_interrupted"] is True
    assert ctx["map_approx"] == pytest.approx(110.0)
    assert ctx["pulse_pressure"] == pytest.approx(60.0)
    assert ctx["pas_rise_vs_basal"] == pytest.approx(20.0)
    assert ctx["pas_drop_vs_basal"] == pytest.approx(-20.0)
    assert ctx["glucose_delta"] == pytest.approx(10.0)
    assert ctx["consecutive_valid"] == 2
    # vitals_used continua só com vitais medidos
    used = alerts["vitals_used"]
    assert used["pas"] == 150 and used["pad"] == 90 and used["glucose_mgdl"] == 180
    assert used["temp_c"] is None


def test_context_informed_never_exposes_phantom_even_in_authorized_dev(monkeypatch):
    monkeypatch.setenv(PHANTOM_VITALS_ENV, "1")
    alerts = assess_ingest_alerts(heart_rate=72, spo2=88, phantom=LEGACY_PHANTOM)
    assert alerts["source_meta"]["bp_source"] == "phantom"
    ctx = alerts["context_informed"]
    assert ctx["map_approx"] is None and ctx["pulse_pressure"] is None
    assert ctx["pas_rise_vs_basal"] is None and ctx["glucose_delta"] is None
