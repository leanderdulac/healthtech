"""Testes da integração matriz de alertas ↔ ingestão wearables."""

from __future__ import annotations

from src.clinical_intelligence.alert_ingest import (
    assess_ingest_alerts,
    merge_anomaly_with_alerts,
    vitals_from_ingest_context,
)


def test_ppg_mean_is_not_a_heart_rate():
    from src.clinical_intelligence.alert_ingest import resolve_heart_rate

    hr, note = resolve_heart_rate(
        76,
        [500.0, 520.0, 560.0, 610.0, 580.0, 530.0, 505.0, 495.0],
    )
    assert hr == 76
    assert note["heart_rate_source"] == "measured"
    assert note["ppg_role"] == "waveform"
    assert note["ppg_not_used_as_bpm"] is True


def test_out_of_range_heart_rate_does_not_enter_the_matrix():
    alerts = assess_ingest_alerts(
        heart_rate=540,
        spo2=97,
        skin_temp=33.0,
        phantom={},
        rules_only=True,
    )
    assert alerts["vitals_used"]["hr"] is None
    assert alerts["is_true_alert"] is False
    assert any(item["field"] == "hr" for item in alerts["source_meta"]["rejected"])


def test_missing_context_is_not_invented():
    vitals, _meta = vitals_from_ingest_context(
        heart_rate=100,
        spo2=98,
        skin_temp=36.6,
        activity_level=90,
        phantom={},
    )
    assert vitals.hr_baseline_rise is None
    assert vitals.steps_drop_pct is None
    assert vitals.sleep_worsen_pct is None
    assert vitals.pas is None
    assert vitals.glucose_mgdl is None


def test_unreliable_phantom_does_not_drive_the_alert():
    alerts = assess_ingest_alerts(
        heart_rate=78,
        spo2=98,
        skin_temp=36.5,
        phantom={
            "systolic_bp": {"estimate": 190, "reliable": False, "method": "heuristic"},
            "diastolic_bp": {"estimate": 115, "reliable": False, "method": "heuristic"},
            "glucose_mgdl": {"estimate": 220, "reliable": False, "method": "heuristic"},
        },
        rules_only=True,
    )
    assert alerts["vitals_used"]["pas"] is None
    assert alerts["vitals_used"]["glucose_mgdl"] is None
    assert alerts["is_true_alert"] is False


def test_vitals_prefer_explicit_bp_over_phantom():
    v, meta = vitals_from_ingest_context(
        heart_rate=80,
        spo2=98,
        skin_temp=33.0,
        phantom={"systolic_bp": {"estimate": 150}, "diastolic_bp": {"estimate": 95}},
        hband_ext={"blood_pressure_sys": 190, "blood_pressure_dia": 115},
    )
    assert v.pas == 190
    assert v.pad == 115
    assert v.hr == 80
    assert meta["bp_source"] == "measured"


def test_ui_screenshot_false_positive_suppressed():
    """Caso da UI: FC 78, temp 36.5, sono bom + 'crise hipertensiva' / hiperglicemia phantom."""
    alerts = assess_ingest_alerts(
        heart_rate=78,
        spo2=98,
        skin_temp=36.5,
        phantom={
            "systolic_bp": {"estimate": 190, "reliable": True},
            "diastolic_bp": {"estimate": 115, "reliable": True},
            "glucose_mgdl": {"estimate": 200, "reliable": True},
        },
        hband_ext={"steps_drop_pct": 5, "sleep_worsen_pct": 5},
    )
    assert alerts["is_true_alert"] is False
    assert alerts["severity"] == "none"
    assert alerts["is_false_positive"] is True or alerts["decision"] in {
        "suppressed_sample_discrepancy",
        "suppressed_false_positive",
        "stable_or_noise",
    }
    # Se regras phantom bateram, discrepancy deve ter suprimido
    if alerts.get("discrepancy"):
        assert alerts["discrepancy"].get("is_discrepant") or not alerts["is_true_alert"]


def test_assess_critical_hypoxemia_on_ingest():
    alerts = assess_ingest_alerts(
        heart_rate=85,
        spo2=88,
        skin_temp=33.0,
        phantom={},
    )
    assert alerts["is_true_alert"] is True
    assert alerts["severity"] == "critico"
    assert alerts["primary_rule_id"] is not None
    assert alerts.get("care_line")
    assert alerts["care_line"]["acs_deadline_hours"] == 4
    assert alerts["care_line"]["acs_dispatch"] is True
    assert alerts["care_line"]["mandatory"] is False
    assert alerts["decision_support"]["not_a_mandatory_protocol"] is True


def test_assess_suppresses_borderline_hr_false_positive():
    alerts = assess_ingest_alerts(
        heart_rate=105,
        spo2=98,
        skin_temp=33.0,
        phantom={
            "systolic_bp": {"estimate": 118},
            "diastolic_bp": {"estimate": 76},
            "glucose_mgdl": {"estimate": 105},
        },
        hband_ext={"steps_drop_pct": 8, "sleep_worsen_pct": 10},
    )
    assert alerts["is_true_alert"] is False
    assert alerts["severity"] == "none"


def test_rules_only_does_not_load_classifier(monkeypatch):
    def _boom():
        raise AssertionError("classificador não pode entrar no piloto")

    monkeypatch.setattr(
        "src.clinical_intelligence.alert_ingest._load_classifier",
        _boom,
    )
    alerts = assess_ingest_alerts(
        heart_rate=85,
        spo2=88,
        skin_temp=33.0,
        phantom={},
        raw_telemetry={"ingest_source": "ble_hband"},
        rules_only=True,
    )
    assert alerts["engine"] == "alert_matrix_rules"
    assert alerts["ml"] is None
    assert alerts["is_true_alert"] is True
    assert alerts["pilot_eligible"] is True
    assert alerts["ingest_source"] == "ble_hband"
    provenance = alerts["provenance"]
    assert provenance["rules_count"] == 158
    assert len(provenance["rules_sha256"]) == 64
    assert provenance["git_sha"]


def test_ble_standard_is_pilot_eligible():
    alerts = assess_ingest_alerts(
        heart_rate=72,
        spo2=98,
        skin_temp=33.0,
        phantom={},
        raw_telemetry={"ingest_source": "ble_standard"},
        rules_only=True,
    )
    assert alerts["pilot_eligible"] is True
    assert alerts["ingest_source"] == "ble_standard"
    assert alerts["engine"] == "alert_matrix_rules"


def test_ble_sim_is_recorded_but_not_pilot_eligible():
    alerts = assess_ingest_alerts(
        heart_rate=78,
        spo2=98,
        skin_temp=33.0,
        phantom={},
        raw_telemetry={"ingest_source": "ble_sim"},
        rules_only=True,
    )
    assert alerts["engine"] == "alert_matrix_rules"
    assert alerts["pilot_eligible"] is False
    assert alerts["ingest_source"] == "ble_sim"


def test_merge_anomaly_reinforces_true_alert():
    anomaly = {"alerta": False, "score": 0.05, "modo": "Detecção Local BMO"}
    alerts = {
        "is_true_alert": True,
        "is_false_positive": False,
        "severity": "critico",
        "primary_rule_id": "spo2_5",
        "primary_alert_name": "Possível hipoxemia importante",
    }
    merged = merge_anomaly_with_alerts(anomaly, alerts)
    assert merged["alerta"] is True
    assert merged["score"] >= 0.9
    assert "Matriz" in merged["modo"]


def test_omitted_activity_is_not_rest_and_explicit_zero_is():
    omitted, _meta = vitals_from_ingest_context(heart_rate=105, spo2=98, phantom={})
    assert omitted.rest is False
    quiet = assess_ingest_alerts(heart_rate=105, spo2=98, phantom={}, rules_only=True)
    assert quiet["is_true_alert"] is False

    resting, _meta = vitals_from_ingest_context(
        heart_rate=105, spo2=98, activity_level=0, phantom={}
    )
    assert resting.rest is True
    alert = assess_ingest_alerts(
        heart_rate=105, spo2=98, activity_level=0, phantom={}, rules_only=True
    )
    assert alert["is_true_alert"] is True
    assert alert["vitals_used"]["rest"] is True


def test_recent_previous_confirms_and_stale_previous_does_not():
    alone = assess_ingest_alerts(
        heart_rate=80,
        spo2=98,
        phantom={},
        raw_telemetry={
            "timestamp": "2026-10-09T15:10:00Z",
            "sleep_hours": 5,
            "ingest_source": "ble_hband",
        },
        rules_only=True,
    )
    assert alone["vitals_used"]["consecutive_valid"] == 1
    assert alone["is_true_alert"] is False

    confirmed = assess_ingest_alerts(
        heart_rate=81,
        spo2=98.4,
        phantom={},
        raw_telemetry={
            "timestamp": "2026-10-09T15:10:00Z",
            "sleep_hours": 5,
            "ingest_source": "ble_hband",
            "previous_reading": {"spo2": 98.0, "heart_rate": 80, "timestamp": "2026-10-09T15:00:00Z"},
        },
        rules_only=True,
    )
    assert confirmed["vitals_used"]["consecutive_valid"] == 2
    assert confirmed["is_true_alert"] is True
    assert any(hit["rule_id"] == "n2u_111" for hit in confirmed["rule_hits"])

    stale = assess_ingest_alerts(
        heart_rate=81,
        spo2=98.4,
        phantom={},
        raw_telemetry={
            "timestamp": "2026-10-09T18:00:00Z",
            "sleep_hours": 5,
            "ingest_source": "ble_hband",
            "previous_reading": {"spo2": 98.0, "heart_rate": 80, "timestamp": "2026-10-09T15:00:00Z"},
        },
        rules_only=True,
    )
    assert stale["vitals_used"]["consecutive_valid"] == 1
    assert stale["is_true_alert"] is False


def test_wear_off_motion_and_duplicate_suppress_without_dropping_other_signals():
    loose = assess_ingest_alerts(
        heart_rate=85,
        spo2=88,
        phantom={},
        raw_telemetry={"wear_status": False, "timestamp": "2026-10-09T15:00:00Z"},
        rules_only=True,
    )
    assert loose["is_true_alert"] is False
    assert loose["decision"] == "suppressed_quality"
    assert loose["care_line"] is None
    assert "wear_off" in loose["source_meta"]["quality"]["reasons"]

    exercise = assess_ingest_alerts(
        heart_rate=140,
        spo2=98,
        activity_level=55,
        phantom={},
        rules_only=True,
    )
    assert exercise["is_true_alert"] is False
    assert "motion" in exercise["source_meta"]["quality"]["reasons"]
    assert any(hit["rule_id"] == "n2u_092" for hit in exercise["rule_hits"])

    hypoxemia_while_moving = assess_ingest_alerts(
        heart_rate=128,
        spo2=88,
        activity_level=55,
        phantom={},
        rules_only=True,
    )
    assert hypoxemia_while_moving["is_true_alert"] is True

    repeated = assess_ingest_alerts(
        heart_rate=85,
        spo2=88,
        phantom={},
        raw_telemetry={
            "timestamp": "2026-10-09T15:00:01Z",
            "previous_reading": {
                "heart_rate": 85,
                "spo2": 88,
                "timestamp": "2026-10-09T15:00:00Z",
            },
        },
        rules_only=True,
    )
    assert repeated["is_true_alert"] is False
    assert repeated["decision"] == "suppressed_quality"
    assert "duplicate_sample" in repeated["source_meta"]["quality"]["reasons"]


def test_merge_anomaly_suppresses_local_fp():
    anomaly = {"alerta": True, "score": 0.95, "modo": "Detecção Local BMO"}
    alerts = {
        "is_true_alert": False,
        "is_false_positive": True,
        "severity": "none",
    }
    merged = merge_anomaly_with_alerts(anomaly, alerts)
    assert merged["alerta"] is False
    assert merged.get("suppressed_by_matrix") is True


def test_wearable_api_returns_clinical_alerts():
    from fastapi.testclient import TestClient
    from src.api_server import app

    client = TestClient(app)
    headers = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
    res = client.post(
        "/api/v1/wearables/ingest",
        headers=headers,
        json={
            "patient_id": "PAT-ALERT-001",
            "device_id": "hband-test",
            "heart_rate": 85.0,
            "spo2": 88.0,
            "skin_temp": 33.0,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "clinical_alerts" in data
    assert data["clinical_alerts"]["is_true_alert"] is True
    assert data["clinical_alerts"]["severity"] == "critico"
    assert data["anomaly_detection"]["alerta"] is True


def test_wearable_api_hypertensive_crisis_with_explicit_bp():
    from fastapi.testclient import TestClient
    from src.api_server import app

    client = TestClient(app)
    headers = {"X-API-Key": "ht_ingest_test_key_32chars_long_token"}
    res = client.post(
        "/api/v1/wearables/ingest",
        headers=headers,
        json={
            "patient_id": "PAT-ALERT-002",
            "heart_rate": 125.0,
            "spo2": 97.0,
            "blood_pressure_sys": 190,
            "blood_pressure_dia": 115,
            "body_temp_c": 36.8,
        },
    )
    assert res.status_code == 200
    ca = res.json()["clinical_alerts"]
    assert ca["is_true_alert"] is True
    assert ca["severity"] == "critico"
    assert ca.get("primary_rule_id") is not None
