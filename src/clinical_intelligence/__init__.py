"""
Motor de inteligência clínica preditiva multimodal.

Filtragem de ruído → sinais fantasmas → lógica fuzzy → fusão de evidências
→ predição de eventos clínicos com antecedência de horas/dias.
"""

from src.clinical_intelligence.pipeline import ClinicalIntelligencePipeline
from src.clinical_intelligence.fuzzy_engine import FuzzyClinicalEngine
from src.clinical_intelligence.ghost_signals import GhostSignalDetector
from src.clinical_intelligence.signal_processing import WearableSignalProcessor

__all__ = [
    "ClinicalIntelligencePipeline",
    "FuzzyClinicalEngine",
    "GhostSignalDetector",
    "WearableSignalProcessor",
]