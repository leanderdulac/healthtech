"""Fluxogramas de programa (HAS, DM, DRC, DPOC, hepatopatia, obstétrico)."""

from __future__ import annotations

from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine, VitalSnapshot
from src.clinical_intelligence.care_flows import (
    CATALOG_VERSION,
    apply_care_flow_overlay,
    evaluate_care_flows,
)
from src.clinical_intelligence.next2u_context import PatientContext, canonicalize_disease


def _stable() -> VitalSnapshot:
    return VitalSnapshot(pas=118, pad=76, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=100)


def test_aliases_pregnancy_and_hepatopathy():
    assert canonicalize_disease("gestação") == "pregnancy"
    assert canonicalize_disease("cirrose") == "liver_failure"


def test_disease_alone_does_not_fire_care_flow():
    ctx = PatientContext(diseases=["has", "dm", "drc", "dpoc", "hepatopatia", "gestação"])
    res = evaluate_care_flows(_stable(), ctx)
    assert set(res.enrolled) == {"has", "dm", "drc", "dpoc", "hepatopatia", "obstetrico"}
    assert not res.matched
    assert res.severity == "none"


def test_has_flow_thresholds():
    ctx = PatientContext(diseases=["hypertension"])
    hypo = evaluate_care_flows(VitalSnapshot(pas=88, pad=58, hr=80, spo2=97, temp_c=36.5), ctx)
    assert hypo.matched and hypo.severity == "critico" and hypo.action == "samu"

    mod = evaluate_care_flows(VitalSnapshot(pas=150, pad=105, hr=80, spo2=97, temp_c=36.5), ctx)
    assert mod.matched and mod.severity == "moderado"

    crisis = evaluate_care_flows(VitalSnapshot(pas=190, pad=125, hr=88, spo2=97, temp_c=36.5), ctx)
    assert crisis.matched and crisis.severity == "critico"
    assert crisis.program == "has"


def test_dm_hypo_confirmation_tree():
    ctx = PatientContext(diseases=["diabetes"])
    first = evaluate_care_flows(VitalSnapshot(glucose_mgdl=62, hr=80, spo2=97, temp_c=36.5), ctx)
    assert first.severity == "moderado"
    assert first.action == "acs"
    assert first.pending_confirmation

    confirmed = PatientContext(diseases=["diabetes"], confirmation_or_persistence=True)
    silent = evaluate_care_flows(VitalSnapshot(glucose_mgdl=62, hr=80, spo2=97, temp_c=36.5), confirmed)
    assert silent.severity == "moderado" and silent.action == "ubs"

    symptomatic = PatientContext(
        diseases=["diabetes"], confirmation_or_persistence=True, symptoms=True
    )
    with_sx = evaluate_care_flows(
        VitalSnapshot(glucose_mgdl=62, hr=80, spo2=97, temp_c=36.5), symptomatic
    )
    assert with_sx.severity == "critico" and with_sx.action == "samu"

    grave = evaluate_care_flows(
        VitalSnapshot(glucose_mgdl=50, consciousness_altered=True, hr=80, spo2=97, temp_c=36.5),
        ctx,
    )
    assert grave.severity == "critico"


def test_drc_crisis_vs_isolated_sign():
    ctx = PatientContext(diseases=["ckd"])
    crise = evaluate_care_flows(VitalSnapshot(pas=190, pad=125, hr=72, spo2=97, temp_c=36.5), ctx)
    assert crise.severity == "critico"

    isolated_hr = evaluate_care_flows(
        VitalSnapshot(pas=120, pad=80, hr=110, spo2=97, temp_c=36.5), ctx
    )
    assert isolated_hr.matched and isolated_hr.severity == "moderado"

    combo = evaluate_care_flows(
        VitalSnapshot(pas=120, pad=80, hr=110, spo2=90, temp_c=36.5), ctx
    )
    assert combo.severity == "critico"
    assert combo.other_signs


def test_dpoc_spo2_and_fever():
    ctx = PatientContext(diseases=["copd"])
    hypox = evaluate_care_flows(VitalSnapshot(spo2=90, hr=72, pas=120, pad=80, temp_c=36.5), ctx)
    assert hypox.severity == "critico"

    fever = evaluate_care_flows(VitalSnapshot(spo2=96, hr=72, pas=120, pad=80, temp_c=37.7), ctx)
    assert fever.severity == "critico"


def test_hepatopathy_hypotension_and_acs_table():
    ctx = PatientContext(diseases=["hepatopatia"])
    hypo = evaluate_care_flows(VitalSnapshot(pas=95, pad=58, hr=72, spo2=97, temp_c=36.5), ctx)
    assert hypo.severity == "critico"

    isolated = evaluate_care_flows(
        VitalSnapshot(pas=120, pad=80, hr=110, spo2=97, temp_c=36.5, glucose_mgdl=110), ctx
    )
    assert isolated.severity == "moderado"

    overlay = apply_care_flow_overlay({"severity": "none", "is_true_alert": False}, hypo)
    assert overlay["care_flow"]["acs_checks"][0] == "pa"
    assert overlay["is_true_alert"] is True


def test_obstetric_pa_and_isolated_spo2():
    ctx = PatientContext(diseases=["gestação"])
    pa = evaluate_care_flows(VitalSnapshot(pas=145, pad=92, hr=80, spo2=97, temp_c=36.5), ctx)
    assert pa.severity == "critico"

    spo2_only = evaluate_care_flows(
        VitalSnapshot(pas=118, pad=76, hr=80, spo2=93, temp_c=36.5, glucose_mgdl=90), ctx
    )
    assert spo2_only.severity == "moderado"

    spo2_plus = evaluate_care_flows(
        VitalSnapshot(pas=118, pad=76, hr=110, spo2=93, temp_c=36.5, glucose_mgdl=90), ctx
    )
    assert spo2_plus.severity == "critico"


def test_ingest_exposes_care_flow_for_has_crisis():
    from src.clinical_intelligence.alert_ingest import assess_ingest_alerts

    payload = assess_ingest_alerts(
        heart_rate=88,
        spo2=97,
        skin_temp=36.5,
        raw_telemetry={
            "blood_pressure_sys": 190,
            "blood_pressure_dia": 125,
            "clinical_context": {"diseases": ["has"]},
        },
    )
    flow = (payload.get("staff_only") or {}).get("care_flow") or {}
    assert payload["is_true_alert"]
    assert payload["severity"] == "critico"
    assert flow.get("matched") is True
    assert flow.get("program") == "has"


def test_overlay_does_not_break_next2u_lock():
    eng = AlertMatrixEngine()
    vitals = _stable()
    ctx = PatientContext(diseases=["hypertension", "ckd", "copd"])
    matrix = eng.evaluate(vitals, context=ctx)
    flow = evaluate_care_flows(vitals, ctx)
    merged = apply_care_flow_overlay(
        {
            "is_true_alert": matrix.is_true_alert,
            "severity": matrix.max_severity,
            "stars": matrix.stars,
            "rule_explanation": matrix.explanation,
        },
        flow,
    )
    assert not matrix.is_true_alert
    assert not flow.matched
    assert merged["is_true_alert"] is False
    assert merged["care_flow"]["catalog_version"] == CATALOG_VERSION
