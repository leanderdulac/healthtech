"""
Módulo de Dados Fantasmas (Phantom Data)

Este módulo expõe as classes e métodos responsáveis por realizar inferência
de estados fisiológicos latentes ("phantom data") a partir de observáveis
de wearables, bem como análise de HRV (Variabilidade da Frequência Cardíaca).
"""

from src.phantom_data.state_space_model import (
    ExtendedKalmanFilter,
    UnscentedKalmanFilter,
    PhysiologicalTransitionModel,
    WearableObservationModel,
)
from src.phantom_data.phantom_inference_engine import (
    PhantomDataEngine,
    BatchPhantomProcessor,
)
from src.phantom_data.hrv_analysis import (
    HRVAnalyzer,
)

__all__ = [
    "ExtendedKalmanFilter",
    "UnscentedKalmanFilter",
    "PhysiologicalTransitionModel",
    "WearableObservationModel",
    "PhantomDataEngine",
    "BatchPhantomProcessor",
    "HRVAnalyzer",
]
