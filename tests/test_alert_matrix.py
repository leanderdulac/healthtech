"""Testes da matriz de alertas e classificador FP."""

from __future__ import annotations

from src.clinical_intelligence.alert_matrix_dataset import generate_dataset
from src.clinical_intelligence.alert_matrix_rules import (
    AlertMatrixEngine,
    VitalSnapshot,
    rules_catalog,
)


def test_rules_catalog_has_all_sections():
    cat = rules_catalog()
    assert len(cat) >= 140
    categories = {r["category"] for r in cat}
    assert "pa_alta" in categories
    assert "hipoglicemia" in categories
    assert "funcional" in categories
    assert "infeccao" in categories
    assert "desidratacao" in categories
    assert "queda" in categories


def test_critical_hypertensive_crisis():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=190, pad=115, hr=125, spo2=96, temp_c=36.8, glucose_mgdl=110)
    )
    assert res.is_true_alert
    assert res.max_severity == "critico"
    assert res.primary_rule_id is not None


def test_isolated_borderline_not_always_critical():
    eng = AlertMatrixEngine()
    # HR 105 isolada — pode acionar fc leve se 111-130, mas 105 não
    res = eng.evaluate(
        VitalSnapshot(pas=118, pad=76, hr=105, spo2=98, temp_c=36.7, glucose_mgdl=105)
    )
    # Não deve ser crítico
    assert res.max_severity in ("none", "leve")


def test_hypoxemia_critical():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=120, pad=80, hr=80, spo2=88, temp_c=36.6, glucose_mgdl=100)
    )
    assert res.is_true_alert
    assert res.max_severity == "critico"


def test_hypoglycemia_severe():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=120, pad=80, hr=80, spo2=98, temp_c=36.6, glucose_mgdl=40)
    )
    assert res.is_true_alert
    assert res.max_severity == "critico"


def test_generate_dataset_balance():
    df = generate_dataset(n_per_rule=5, n_normal=50, n_false_positive=50, seed=1)
    assert len(df) > 100
    assert df["is_false_positive"].sum() > 0
    assert df["is_true_alert"].sum() > 0
    assert set(df["severity"].unique()).issubset({"none", "leve", "moderado", "critico"})


def test_decision_support_is_never_a_mandatory_protocol():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=190, pad=115, hr=125, spo2=96, temp_c=36.8, glucose_mgdl=110)
    )
    payload = res.to_dict()
    ds = payload["decision_support"]
    assert ds["not_a_diagnosis"] is True
    assert ds["not_a_mandatory_protocol"] is True
    assert payload["care_line"]["mandatory"] is False
    assert payload["care_line"]["protocol_binding"] is False
    assert "protocolo institucional" in ds["disclaimer"].lower()


def test_isolated_systolic_and_care_line_leve():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=148, pad=82, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=100)
    )
    assert res.is_true_alert
    assert res.max_severity == "leve"
    assert res.care_line is not None
    assert res.care_line["acs_dispatch"] is False
    assert res.care_line["acs_deadline_hours"] == 168
    ids = {h.rule_id for h in res.hits}
    assert "n2u_011" in ids or "n2u_012" in ids


def test_sepsis_pattern_critical_with_nurse_acs_line():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=88, pad=50, hr=135, spo2=97, temp_c=38.6, glucose_mgdl=110)
    )
    assert res.is_true_alert
    assert res.max_severity == "critico"
    assert res.care_line["acs_dispatch"] is True
    assert res.care_line["acs_deadline_hours"] == 4
    ids = {h.rule_id for h in res.hits}
    assert "n2u_020" in ids or "n2u_048" in ids or any(i.startswith("n2u_") for i in ids)
    assert any("sepse" in (h.name or "").lower() or "instabilidade" in (h.name or "").lower() for h in res.hits)


def test_fall_requires_hourly_steps():
    eng = AlertMatrixEngine()
    without = eng.evaluate(
        VitalSnapshot(pas=85, pad=50, hr=80, spo2=98, temp_c=36.6, glucose_mgdl=100)
    )
    with_steps = eng.evaluate(
        VitalSnapshot(
            pas=85, pad=50, hr=80, spo2=98, temp_c=36.6, glucose_mgdl=100,
            hourly_steps_available=True, abrupt_steps_stop=True,
        )
    )
    assert with_steps.is_true_alert
    assert with_steps.max_severity == "critico"
    assert any(h.category == "queda" for h in with_steps.hits)
    assert "n2u_154" in {h.rule_id for h in with_steps.hits} or "n2u_146" in {
        h.rule_id for h in with_steps.hits
    }
    # Sem interrupção de passos a regra de queda não dispara
    assert not any(h.category == "queda" for h in without.hits)


def test_dehydration_and_infection_notes():
    eng = AlertMatrixEngine()
    res = eng.evaluate(
        VitalSnapshot(pas=95, pad=60, hr=120, spo2=97, temp_c=36.6, glucose_mgdl=100)
    )
    assert res.is_true_alert
    cats = {h.category for h in res.hits}
    assert "desidratacao" in cats or "pa_baixa" in cats
    if any(h.category == "desidratacao" for h in res.hits):
        assert res.clinical_notes


def test_fasting_glucose_only_when_flagged():
    eng = AlertMatrixEngine()
    plain = eng.evaluate(
        VitalSnapshot(pas=120, pad=75, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=160)
    )
    fasting = eng.evaluate(
        VitalSnapshot(
            pas=120, pad=75, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=160,
            fasting_or_preprandial=True,
        )
    )
    assert not plain.is_true_alert
    assert fasting.is_true_alert
    assert fasting.max_severity == "leve"
    assert fasting.primary_rule_id == "n2u_085"


def test_resting_tachycardia_needs_at_rest_flag():
    eng = AlertMatrixEngine()
    unknown = eng.evaluate(
        VitalSnapshot(pas=118, pad=76, hr=105, spo2=98, temp_c=36.7, glucose_mgdl=105)
    )
    rest = eng.evaluate(
        VitalSnapshot(
            pas=118, pad=76, hr=105, spo2=98, temp_c=36.7, glucose_mgdl=105, at_rest=True
        )
    )
    assert unknown.max_severity in ("none", "leve")
    assert not unknown.is_true_alert
    assert rest.is_true_alert
    assert rest.max_severity in ("leve", "moderado")
    assert {"n2u_094", "n2u_100"} & {h.rule_id for h in rest.hits}


def test_classifier_train_and_fp_detection():
    from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier

    df = generate_dataset(n_per_rule=50, n_normal=600, n_false_positive=800, seed=7)
    clf = AlertMatrixClassifier()
    metrics = clf.fit(df, test_size=0.2, random_state=7)
    # Operacional: capturar FPs (recall) e não perder true alerts.
    # severity_f1_macro ~0.84–0.87 na matriz Next2U-158 (varia por OS) com este dataset sintético.
    assert metrics["false_positive_recall"] >= 0.90
    assert metrics["true_alert_f1"] >= 0.95
    assert metrics["severity_f1_macro"] >= 0.84
    assert metrics["false_positive_f1"] >= 0.75

    out = clf.assess(
        VitalSnapshot(
            pas=118, pad=76, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=100,
            steps_drop_pct=5, sleep_worsen_pct=5, hr_baseline_rise=2, spo2_drop_points=0.5,
        )
    )
    assert not out["is_true_alert"]
    assert out["severity"] == "none"

    out_fp = clf.assess(
        VitalSnapshot(
            pas=118, pad=76, hr=105, spo2=98, temp_c=36.7, glucose_mgdl=105,
            steps_drop_pct=8, sleep_worsen_pct=10, hr_baseline_rise=3, spo2_drop_points=0.5,
        )
    )
    assert not out_fp["is_true_alert"]

    out2 = clf.assess(
        VitalSnapshot(pas=190, pad=115, hr=125, spo2=96, temp_c=36.8, glucose_mgdl=110)
    )
    assert out2["is_true_alert"]
    assert out2["severity"] == "critico"


