"""O TCN não promove alerta enquanto a calibração conformal está degenerada."""

from src.integrations.vertex.deploy.tcn_decision import calibration_usable, decide_tcn


DEGENERATE = {
    "horizons": {
        "event_6h": {"q_hat": 1.0},
        "event_24h": {"q_hat": 0.0},
        "event_72h": {"q_hat": 0.8348},
    }
}

USABLE = {
    "horizons": {
        "event_6h": {"q_hat": 0.12},
        "event_24h": {"q_hat": 0.2},
        "event_72h": {"q_hat": 0.15},
    }
}


def test_current_calibration_is_not_usable():
    assert calibration_usable(DEGENERATE) is False


def test_degenerate_calibration_does_not_alert_or_publish_intervals():
    decision = decide_tcn([1.0, 1.0, 0.99], DEGENERATE)
    assert decision["alerta"] is False
    assert decision["uso"] == "laboratorio"
    assert decision["horizon_at_risk"] is None
    assert decision["conformal_status"] == "degenerado"
    assert "conformal_intervals" not in decision
    assert decision["prob_6h"] == 1.0


def test_usable_calibration_keeps_intervals_and_still_refuses_clinical_alert():
    decision = decide_tcn([0.9, 0.2, 0.1], USABLE)
    assert decision["conformal_status"] == "calibrado"
    assert decision["conformal_intervals"]["6h"] == [0.78, 1.0]
    assert decision["alerta"] is False
    assert decision["uso"] == "laboratorio"


def test_missing_calibration_is_explicit():
    decision = decide_tcn([0.4, 0.4, 0.4], None)
    assert decision["conformal_status"] == "ausente"
    assert decision["alerta"] is False
