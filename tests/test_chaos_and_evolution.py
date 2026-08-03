"""
test_chaos_and_evolution.py — Testes Unitários para as Adaptações 'Do Caos à Precisão'
"""

import pytest
import numpy as np

from src.signal_processing.noise_separation import SigmoidalMicroclimateNoiseFilter
from src.signal_processing.chaos_fractal import FractalChaosAnalyzer
from src.anomaly_detection.evolutionary_ensemble import EvolutionaryPersonalizedEnsemble
from src.clinical_intelligence.sus_prevention_nudges import SUSPreventionNudgeEngine


def test_sigmoidal_noise_filter():
    filter_sig = SigmoidalMicroclimateNoiseFilter(alpha=4.0, threshold=2.0)
    data = np.array([70.0, 71.0, 70.5, 120.0, 70.2, 69.8])
    res = filter_sig.filter_transient_noise(data)

    assert "filtered_signal" in res
    assert "weights" in res
    # O valor atípico de 120.0 no índice 3 deve ter peso sigmoidal baixo (< 0.5)
    assert res["weights"][3] < 0.5
    assert res["filtered_signal"][3] < 120.0


def test_fractal_chaos_analyzer():
    analyzer = FractalChaosAnalyzer(k_max=5)
    np.random.seed(42)
    series = np.sin(np.linspace(0, 10, 100)) + 0.1 * np.random.randn(100)
    metrics = analyzer.analyze(series)

    assert 1.0 <= metrics["higuchi_fd"] <= 2.0
    assert 1.0 <= metrics["katz_fd"] <= 2.0
    assert 0.0 <= metrics["hurst_exponent"] <= 1.0
    assert isinstance(metrics["lyapunov_lle"], float)


def test_evolutionary_72_ensemble():
    ensemble = EvolutionaryPersonalizedEnsemble(patient_id="TEST_001")
    assert len(ensemble.algorithms) == 72

    ensemble.evolve_weights({"accuracy": 0.95})
    series = np.linspace(60, 100, 50)
    pred = ensemble.predict_anomaly(series)

    assert "anomaly_score" in pred
    assert pred["active_algorithms_count"] == 72
    assert 0.0 <= pred["anomaly_score"] <= 1.0
    assert pred["consensus_level"] in ["ALTO", "MEDIO", "BAIXO"]


def test_sus_prevention_nudge_engine():
    engine = SUSPreventionNudgeEngine()
    eval_res = engine.evaluate_prevention_protocols(
        patient_age=75,
        hr_series=[98.0, 99.0, 101.0],
        hrv_series=[15.0, 18.0, 14.0],
        stress_series=[80.0, 85.0, 82.0],
        temp_delta=0.8
    )

    assert eval_res["is_elderly"] is True
    assert eval_res["risk_level"] in ["CRITICO", "ALTO", "MEDIO"]
    assert len(eval_res["patient_nudges"]) > 0
    assert len(eval_res["nursing_decision_support"]) > 0
    assert "tecnologia de apoio" in eval_res["clinical_disclaimer"].lower()
