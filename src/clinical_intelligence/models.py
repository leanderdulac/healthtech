"""
Modelos de dados para o motor preditivo clínico multimodal.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PatientBaseline:
    """Baseline personalizado adaptativo por paciente."""

    patient_id: str
    resting_hr: float
    baseline_spo2: float
    baseline_hrv: float
    age: int = 0
    risk_factor: float = 0.0
    activity_level: str = "moderate"
    clinical_conditions: List[str] = field(default_factory=list)
    medications: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DenoisedSignal:
    """Sinal wearable após pipeline de filtragem."""

    metric: str
    raw: List[float]
    filtered: List[float]
    timestamps: List[str]
    noise_estimate: float
    artifact_ratio: float
    quality_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "samples": len(self.raw),
            "noise_estimate": float(self.noise_estimate),
            "artifact_ratio": float(self.artifact_ratio),
            "quality_score": float(self.quality_score),
            "last_raw": float(self.raw[-1]) if self.raw else 0.0,
            "last_filtered": float(self.filtered[-1]) if self.filtered else 0.0,
        }


@dataclass
class GhostSignal:
    """
    Sinal fantasma: biomarcador inferido algoritmicamente, não medido
    diretamente pelo wearable.
    """

    name: str
    value: float
    confidence: float
    derivation: str
    clinical_relevance: str
    operator: str = "inference"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FuzzyAssessment:
    """Resultado da inferência fuzzy."""

    event_probability: float
    false_positive_risk: float
    noise_gate: float
    persistence_score: float
    rule_activations: Dict[str, float]
    linguistic_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClinicalEventPrediction:
    """Predição de evento clínico com horizonte temporal."""

    patient_id: str
    event_type: str
    probability: float
    confidence_interval: Tuple[float, float]
    lead_time_hours: float
    lead_time_days: float
    horizon: str
    evidence_sources: List[str]
    ghost_signals_involved: List[str]
    false_positive_risk: float
    recommendation: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["confidence_interval"] = list(self.confidence_interval)
        return d


@dataclass
class ClinicalIntelligenceResult:
    """Resultado completo da análise preditiva."""

    patient_id: str
    scenario: str
    denoised_signals: Dict[str, DenoisedSignal]
    ghost_signals: List[GhostSignal]
    fuzzy: FuzzyAssessment
    predictions: List[ClinicalEventPrediction]
    fusion_score: float
    ontology_domains: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "scenario": self.scenario,
            "denoised_signals": {k: v.to_dict() for k, v in self.denoised_signals.items()},
            "ghost_signals": [g.to_dict() for g in self.ghost_signals],
            "fuzzy": self.fuzzy.to_dict(),
            "predictions": [p.to_dict() for p in self.predictions],
            "fusion_score": float(self.fusion_score),
            "ontology_domains": self.ontology_domains,
        }