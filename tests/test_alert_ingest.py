"""Testes da integração matriz de alertas ↔ ingestão wearables."""

from __future__ import annotations

from src.clinical_intelligence.alert_ingest import (
    assess_ingest_alerts,
    merge_anomaly_with_alerts,
    vitals_from_ingest_context,
)


def test_vitals_prefer_explicit_bp_over_phantom():
    v = vitals_from_ingest_context(
        heart_rate=80,
        spo2=98,
        skin_temp=33.0,
        phantom={"systolic_bp": {"estimate": 150}, "diastolic_bp": {"estimate": 95}},
        hband_ext={"blood_pressure_sys": 190, "blood_pressure_dia": 115},
    )
    assert v.pas == 190
    assert v.pad == 115
    assert v.hr == 80


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
