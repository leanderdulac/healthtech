"""
signal_processing — Módulo de Processamento de Sinais Biomédicos
=================================================================

Pacote de processamento de sinais para a plataforma HealthTech, implementando
algoritmos de geração, fusão e denoising de sinais fisiológicos.

Submódulos:
    - physiological_signal_model: Geração de sinais biomédicos realistas
      (Ornstein-Uhlenbeck, distribuição multivariada, intervalos R-R)
    - sensor_fusion: Fusão Bayesiana de sensores com variância adaptativa,
      teste de Grubbs e reconciliação drop-in
    - noise_separation: Denoising wavelet, filtro Butterworth e decomposição
      de componentes de sinal

Uso:
    >>> from signal_processing import OrnsteinUhlenbeckProcess, AdaptiveSensorFusion
    >>> from signal_processing import WaveletDenoiser, ButterworthFilter
"""

# --- physiological_signal_model ---
from .physiological_signal_model import (
    OrnsteinUhlenbeckProcess,
    MultivariatePhysiologicalGenerator,
    generate_rr_intervals,
)

# --- sensor_fusion ---
from .sensor_fusion import (
    AdaptiveSensorFusion,
    reconciliar_dados_bayesiano,
)

# --- noise_separation ---
from .noise_separation import (
    WaveletDenoiser,
    ButterworthFilter,
    decompose_signal_components,
)

__all__: list[str] = [
    # Geração de sinais fisiológicos
    "OrnsteinUhlenbeckProcess",
    "MultivariatePhysiologicalGenerator",
    "generate_rr_intervals",
    # Fusão de sensores
    "AdaptiveSensorFusion",
    "reconciliar_dados_bayesiano",
    # Separação de ruído
    "WaveletDenoiser",
    "ButterworthFilter",
    "decompose_signal_components",
]
