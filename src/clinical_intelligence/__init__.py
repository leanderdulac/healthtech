"""
Motor de inteligência clínica preditiva multimodal.

Filtragem de ruído → sinais fantasmas → lógica fuzzy → fusão de evidências
→ predição de eventos clínicos com antecedência de horas/dias.
"""

from src.clinical_intelligence.pipeline import ClinicalIntelligencePipeline
from src.clinical_intelligence.fuzzy_engine import FuzzyClinicalEngine
from src.clinical_intelligence.ghost_signals import GhostSignalDetector
from src.clinical_intelligence.signal_processing import WearableSignalProcessor
from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine, VitalSnapshot
from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier
from src.clinical_intelligence.alert_ingest import (
    assess_ingest_alerts,
    merge_anomaly_with_alerts,
)
from src.clinical_intelligence.care_flows import evaluate_care_flows

__all__ = [
    "ClinicalIntelligencePipeline",
    "FuzzyClinicalEngine",
    "GhostSignalDetector",
    "WearableSignalProcessor",
    "AlertMatrixEngine",
    "VitalSnapshot",
    "AlertMatrixClassifier",
    "assess_ingest_alerts",
    "merge_anomaly_with_alerts",
    "evaluate_care_flows",
]
from src.clinical_intelligence.agents import (
    SpecialistOpinion,
    CardiologyAgent,
    PulmonologyAgent,
    IntensivistTriageAgent,
    ClinicalConsensusCoordinator,
)

__all__ += [
    "SpecialistOpinion",
    "CardiologyAgent",
    "PulmonologyAgent",
    "IntensivistTriageAgent",
    "ClinicalConsensusCoordinator",
]
