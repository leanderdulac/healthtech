"""
test_bmo_analysis.py — Testes Unitários para a Teoria e Algoritmos BMO/VMO
==========================================================================
"""

import numpy as np
import pytest

from src.signal_processing.bmo_analysis import BMOAnalyzer
from src.signal_processing.noise_separation import BMODenoiser, decompose_signal_components
from src.signal_processing.chaos_fractal import FractalChaosAnalyzer
from src.phantom_data.hrv_analysis import HRVAnalyzer
from src.anomaly_detection.temporal_detector import BMOAnomalyDetector


def test_bmo_local_mean_oscillation_basic():
    """Testa a oscilação média local em um sinal constante vs oscilante."""
    analyzer = BMOAnalyzer()
    
    # Sinal constante -> Oscilação local deve ser 0
    const_signal = np.ones(50) * 10.0
    mo_const = analyzer.compute_local_mean_oscillation(const_signal, window_size=5)
    assert np.allclose(mo_const, 0.0)

    # Sinal degrau -> Oscilação alta na borda
    step_signal = np.array([0.0] * 20 + [10.0] * 20)
    mo_step = analyzer.compute_local_mean_oscillation(step_signal, window_size=6)
    assert np.max(mo_step) > 2.0


def test_bmo_norm_and_multiscale_profile():
    """Testa o cálculo da norma BMO e do perfil multiescala VMO."""
    analyzer = BMOAnalyzer(default_scales=[4, 8, 16])
    rng = np.random.default_rng(42)
    signal = rng.normal(loc=70.0, scale=5.0, size=100)

    bmo_norm = analyzer.compute_bmo_norm(signal)
    assert bmo_norm > 0.0

    profile = analyzer.multiscale_bmo_profile(signal)
    assert "bmo_norm" in profile
    assert "vmo_index" in profile
    assert isinstance(profile["vmo_index"], float)


def test_bmo_edge_preserving_denoise_1d():
    """Testa o denoising 1D BMO com preservação de bordas."""
    analyzer = BMOAnalyzer()
    # Degrau com ruído gaussiano
    rng = np.random.default_rng(42)
    clean = np.array([0.0] * 30 + [20.0] * 30)
    noisy = clean + rng.normal(0, 1.0, size=60)

    filtered = analyzer.denoise_edge_preserving_1d(noisy, window_size=6, alpha=0.5)

    assert len(filtered) == len(noisy)
    # Deve reduzir variância nas regiões constantes preservando o salto
    std_noisy_flat = np.std(noisy[:25])
    std_filt_flat = np.std(filtered[:25])
    assert std_filt_flat < std_noisy_flat
    assert abs(filtered[45] - 20.0) < 5.0  # Preserva amplitude do degrau


def test_bmo_2d_image_filter():
    """Testa o mapa 2D BMO e a filtragem de imagem médica sem efeito escada."""
    analyzer = BMOAnalyzer()
    rng = np.random.default_rng(42)
    
    # Criar imagem médica sintética (bloco 20x20 com 2 regiões de intensidade)
    img = np.ones((20, 20)) * 50.0
    img[5:15, 5:15] = 150.0
    noisy_img = img + rng.normal(0, 5.0, size=(20, 20))

    mo_map = analyzer.compute_bmo_2d(noisy_img, window_size=3)
    assert mo_map.shape == (20, 20)
    assert np.max(mo_map) > 0.0

    filtered_img = analyzer.denoise_image_2d_bmo(noisy_img, window_size=3, lambda_param=0.5)
    assert filtered_img.shape == (20, 20)


def test_bmodenoiser_wrapper_and_decompose():
    """Testa a classe BMODenoiser e a decomposição com BMO."""
    denoiser = BMODenoiser(window_size=8, alpha=0.5)
    sig = np.sin(np.linspace(0, 4 * np.pi, 100)) + np.random.normal(0, 0.2, 100)
    out = denoiser.denoise(sig)
    assert len(out) == 100

    decomp = decompose_signal_components(sig, fs=50.0)
    assert "bmo_norm" in decomp
    assert "vmo_index" in decomp
    assert decomp["bmo_norm"] >= 0.0


def test_bmo_fractal_and_hrv_integration():
    """Testa a integração BMO nos analisadores de fractal e HRV."""
    chaos_analyzer = FractalChaosAnalyzer()
    series = np.sin(np.linspace(0, 10, 100))
    res = chaos_analyzer.analyze(series)
    assert "bmo_norm" in res
    assert "vmo_index" in res

    hrv = HRVAnalyzer()
    rr = np.array([800.0, 810.0, 795.0, 820.0, 805.0, 815.0, 790.0, 800.0, 810.0, 825.0])
    hrv_res = hrv.full_analysis(rr)
    assert "bmo_domain" in hrv_res
    assert "bmo_norm" in hrv_res["bmo_domain"]


def test_bmo_anomaly_detector():
    """Testa a detecção de anomalias por BMO/VMO."""
    detector = BMOAnomalyDetector(short_window=4, long_window=16, bmo_threshold_multiplier=2.0)
    series = np.ones(50) * 70.0
    series[30:35] = 130.0  # Anomalia súbita (pico BMO)

    res = detector.detect_anomalies(series)
    assert res["anomalies_detected"] is True
    assert res["anomaly_count"] > 0
    assert 30 in res["anomaly_indices"] or 31 in res["anomaly_indices"]
