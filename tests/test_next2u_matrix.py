"""Next2U: escore de internação, trava de segurança e promoção por estrelas."""

from __future__ import annotations

from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine, VitalSnapshot
from src.clinical_intelligence.next2u_context import (
    PatientContext,
    hospitalization_score,
    risk_band,
)
from src.clinical_intelligence.next2u_promotion import load_catalog, promote_stars


def test_catalog_has_971_patterns():
    cat = load_catalog()
    assert cat.get("n_expanded_patterns", 0) >= 971
    ids = {p["id"] for p in cat["patterns"]}
    assert "001.1" in ids
    assert "158.4" in ids
    assert len(ids) == 971


def test_hospitalization_score_bands():
    low = PatientContext(diseases=["hypertension"])
    assert hospitalization_score(low) <= 5
    assert risk_band(hospitalization_score(low)) == "baixo"

    high = PatientContext(
        diseases=["hf", "ckd", "neoplasm", "diabetes"],
        n_continuous_meds=8,
        hospitalized_last_6_months=True,
        lives_alone=True,
        reduced_mobility=True,
    )
    sc = hospitalization_score(high)
    assert sc > 15
    assert risk_band(sc) == "critico"


def test_score_alone_does_not_create_alert():
    eng = AlertMatrixEngine()
    vitals = VitalSnapshot(
        pas=118, pad=76, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=100
    )
    ctx = PatientContext(
        diseases=["hf", "ckd", "neoplasm", "dementia"],
        n_continuous_meds=10,
        hospitalized_last_6_months=True,
        lives_alone=True,
        confirmation_or_persistence=True,
        clinical_progression=True,
    )
    res = eng.evaluate(vitals, context=ctx)
    assert not res.is_true_alert
    assert res.max_severity == "none"
    assert res.hospitalization_score > 15


def test_star_promotion_light_to_critical():
    assert promote_stars(1, "baixo", disease_or_med=True, confirmation=True, progression=True) == 1
    assert promote_stars(1, "moderado", disease_or_med=True, confirmation=True, progression=False) == 2
    assert promote_stars(1, "critico", disease_or_med=True, confirmation=True, progression=True) == 3
    assert promote_stars(2, "alto", disease_or_med=True, confirmation=True, progression=False) == 3
    assert promote_stars(3, "baixo", disease_or_med=False, confirmation=False, progression=False) == 3


def test_social_isolation_does_not_promote():
    # promoção ignora isolamento — só disease/med + confirmação/progressão
    assert promote_stars(1, "alto", disease_or_med=False, confirmation=False, progression=False) == 1


def test_hypertensive_crisis_stays_three_stars():
    eng = AlertMatrixEngine()
    vitals = VitalSnapshot(pas=190, pad=115, hr=125, spo2=96, temp_c=36.8, glucose_mgdl=110)
    ctx = PatientContext(diseases=["hypertension"], data_valid=True)
    res = eng.evaluate(vitals, context=ctx)
    assert res.is_true_alert
    assert res.stars == 3
    assert res.care_pathway is not None
    assert res.care_pathway["acs_hours"] == 4
    assert res.next2u_id is not None
    assert res.primary_alert_name.startswith("Possível")


def test_mild_pressure_promotes_with_confirmation():
    eng = AlertMatrixEngine()
    vitals = VitalSnapshot(pas=150, pad=95, hr=100, spo2=98, temp_c=36.6, glucose_mgdl=110)
    ctx = PatientContext(
        diseases=["hypertension", "hf", "ckd"],
        medications=["nsaid"],
        n_continuous_meds=7,
        hospitalized_last_6_months=True,
        confirmation_or_persistence=True,
        clinical_progression=True,
    )
    res = eng.evaluate(vitals, context=ctx)
    assert res.is_true_alert
    assert res.stars >= 2
    assert res.next2u_id is not None


def test_engine_has_158_base_rules():
    from src.clinical_intelligence.alert_matrix_rules import rules_catalog

    cat = rules_catalog()
    ids = {r["rule_id"] for r in cat}
    assert len(cat) >= 158
    assert "n2u_001" in ids
    assert "n2u_158" in ids
    cats = {r["category"] for r in cat}
    assert "infeccao" in cats
    assert "desidratacao" in cats
    assert "queda" in cats


def test_infection_and_fall_predicates():
    eng = AlertMatrixEngine()
    infec = eng.evaluate(
        VitalSnapshot(pas=120, pad=80, hr=100, spo2=97, temp_c=38.4, glucose_mgdl=110)
    )
    assert infec.is_true_alert

    fall = eng.evaluate(
        VitalSnapshot(
            pas=85, pad=55, hr=140, spo2=88, temp_c=36.6, glucose_mgdl=45,
            steps_interrupted=True,
        )
    )
    assert fall.is_true_alert
    assert fall.max_severity == "critico"


def test_ingest_uses_clinical_context():
    from src.clinical_intelligence.alert_ingest import assess_ingest_alerts

    out = assess_ingest_alerts(
        heart_rate=100,
        spo2=98,
        skin_temp=36.6,
        raw_telemetry={
            "blood_pressure_sys": 150,
            "blood_pressure_dia": 95,
            "clinical_context": {
                "diseases": ["hipertensão", "icc", "drc"],
                "medications": ["aine"],
                "n_continuous_meds": 8,
                "hospitalized_last_6_months": True,
                "confirmation_or_persistence": True,
                "clinical_progression": True,
            },
        },
    )
    assert out["is_true_alert"]
    staff = out.get("staff_only") or {}
    assert staff.get("stars", 0) >= 2
    assert "staff_only" in out
