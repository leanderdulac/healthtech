"""
Módulo de Detecção de Anomalias — HealthTech Biomedical Platform
================================================================

Exporta os detectores temporais e o sistema de ensemble para
identificação de anomalias em séries temporais biomédicas.

Classes principais:
    - CUSUMDetector: Detecção sequencial por soma cumulativa (CUSUM).
    - MahalanobisScorer: Pontuação multivariada via distância de Mahalanobis.
    - AdaptiveZScore: Z-score adaptativo com média móvel exponencial (EWMA).
    - PlattScaling: Calibração de escores brutos via regressão logística (Platt).
    - FisherCombinedTest: Combinação de p-valores pelo método de Fisher.
    - EnsembleAnomalyScorer: Orquestrador de múltiplos detectores com fusão estatística.
"""

from .temporal_detector import CUSUMDetector, MahalanobisScorer, AdaptiveZScore
from .ensemble_scorer import PlattScaling, FisherCombinedTest, EnsembleAnomalyScorer

__all__ = [
    "CUSUMDetector",
    "MahalanobisScorer",
    "AdaptiveZScore",
    "PlattScaling",
    "FisherCombinedTest",
    "EnsembleAnomalyScorer",
]
