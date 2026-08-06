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
    assert len(cat) >= 40
    categories = {r["category"] for r in cat}
    assert "pa_alta" in categories
    assert "hipoglicemia" in categories
    assert "funcional" in categories


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


def test_classifier_train_and_fp_detection():
    from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier

    df = generate_dataset(n_per_rule=50, n_normal=600, n_false_positive=800, seed=7)
    clf = AlertMatrixClassifier()
    metrics = clf.fit(df, test_size=0.2, random_state=7)
    # Operacional: capturar FPs (recall) e não perder true alerts
    assert metrics["false_positive_recall"] >= 0.90
    assert metrics["true_alert_f1"] >= 0.95
    assert metrics["severity_f1_macro"] >= 0.90
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


