"""
Fusão multimodal de evidências: wearable + clínico FHIR + ghost + ontologia.

Implementa fusão Bayesiana ponderada com requisito de concordância
multi-fonte para reduzir falsos positivos (≥2 fontes independentes).
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from src.clinical_intelligence.models import (
    ClinicalEventPrediction,
    FuzzyAssessment,
    GhostSignal,
    PatientBaseline,
)

logger = logging.getLogger(__name__)


class EvidenceFusionEngine:
    """
    Combina evidências de múltiplas fontes com pesos calibrados
    por engenharia biomédica:

    - Wearable direto (0.30): HR, SpO2, HRV filtrados
    - Ghost signals (0.25): biomarcadores inferidos
    - Clínico FHIR (0.25): comorbidades, medicações, labs
    - Fuzzy inference (0.20): agregação linguística
    """

    SOURCE_WEIGHTS = {
        "wearable": 0.30,
        "ghost": 0.25,
        "clinical": 0.25,
        "fuzzy": 0.20,
    }

    EVENT_CATALOG = {
        "cardiovascular_event": {
            "triggers": ["autonomic_imbalance", "pulse_irregularity", "recovery_deficit"],
            "clinical_conditions": ["hypertension", "heart_failure", "coronary_artery_disease", "atrial_fibrillation"],
            "base_lead_hours": 48,
        },
        "respiratory_decompensation": {
            "triggers": ["hidden_hypoxemia", "hemodynamic_irregularity_proxy"],
            "clinical_conditions": ["copd", "asthma", "sleep_apnea"],
            "base_lead_hours": 24,
        },
        "autonomic_crisis": {
            "triggers": ["autonomic_imbalance", "stress_activity_decoupling", "circadian_desync"],
            "clinical_conditions": ["diabetes", "autonomic_neuropathy"],
            "base_lead_hours": 12,
        },
        "arrhythmia_event": {
            "triggers": ["pulse_irregularity", "autonomic_imbalance"],
            "clinical_conditions": ["atrial_fibrillation", "arrhythmia"],
            "base_lead_hours": 6,
        },
    }

    def fuse(
        self,
        patient_id: str,
        wearable_score: float,
        ghost_signals: List[GhostSignal],
        fuzzy: FuzzyAssessment,
        baseline: PatientBaseline,
        hemodynamic_score: float = 0.0,
    ) -> tuple:
        ghost_score = self._aggregate_ghosts(ghost_signals)
        clinical_score = self._clinical_score(baseline)

        scores = {
            "wearable": wearable_score,
            "ghost": ghost_score,
            "clinical": clinical_score,
            "fuzzy": fuzzy.event_probability,
        }

        fusion_score = sum(
            self.SOURCE_WEIGHTS[k] * scores[k] for k in self.SOURCE_WEIGHTS
        )

        independent_sources = sum(1 for v in scores.values() if v > 0.35)
        if independent_sources < 2:
            fusion_score *= 0.6

        fusion_score = self._apply_false_positive_penalty(fusion_score, fuzzy.false_positive_risk)
        fusion_score = min(1.0, fusion_score + hemodynamic_score * 0.1)

        predictions = self._generate_predictions(
            patient_id, fusion_score, ghost_signals, fuzzy, baseline, scores,
        )

        return fusion_score, predictions

    def _aggregate_ghosts(self, ghosts: List[GhostSignal]) -> float:
        if not ghosts:
            return 0.0
        weighted = [g.value * g.confidence for g in ghosts]
        top_two = sorted(weighted, reverse=True)[:2]
        if len(top_two) >= 2:
            return min(1.0, 0.6 * top_two[0] + 0.4 * top_two[1])
        return min(1.0, top_two[0]) if top_two else 0.0

    def _clinical_score(self, baseline: PatientBaseline) -> float:
        score = baseline.risk_factor
        score += len(baseline.clinical_conditions) * 0.12
        score += len(baseline.medications) * 0.05
        if baseline.age > 65:
            score += 0.1
        return min(1.0, score)

    @staticmethod
    def _apply_false_positive_penalty(score: float, fp_risk: float) -> float:
        return score * (1.0 - fp_risk * 0.7)

    def _generate_predictions(
        self,
        patient_id: str,
        fusion_score: float,
        ghosts: List[GhostSignal],
        fuzzy: FuzzyAssessment,
        baseline: PatientBaseline,
        source_scores: Dict[str, float],
    ) -> List[ClinicalEventPrediction]:
        predictions = []
        ghost_names = {g.name for g in ghosts if g.value > 0.2}
        now = __import__("datetime").datetime.utcnow().isoformat()

        for event_type, spec in self.EVENT_CATALOG.items():
            trigger_match = ghost_names & set(spec["triggers"])
            clinical_match = any(
                c.lower() in " ".join(baseline.clinical_conditions).lower()
                for c in spec["clinical_conditions"]
            )

            if not trigger_match and not clinical_match:
                continue

            trigger_factor = len(trigger_match) / max(1, len(spec["triggers"]))
            prob = fusion_score * (0.5 + 0.5 * trigger_factor)
            if clinical_match:
                prob = min(1.0, prob * 1.15)

            if prob < 0.2:
                continue

            lead_hours = self._estimate_lead_time(
                prob, fuzzy.persistence_score, spec["base_lead_hours"],
                source_scores.get("ghost", 0),
            )

            ci_low = max(0.0, prob - 0.15 * fuzzy.false_positive_risk)
            ci_high = min(1.0, prob + 0.1)

            predictions.append(ClinicalEventPrediction(
                patient_id=patient_id,
                event_type=event_type,
                probability=round(prob, 4),
                confidence_interval=(round(ci_low, 4), round(ci_high, 4)),
                lead_time_hours=round(lead_hours, 1),
                lead_time_days=round(lead_hours / 24, 2),
                horizon="hours" if lead_hours < 48 else "days",
                evidence_sources=[k for k, v in source_scores.items() if v > 0.25],
                ghost_signals_involved=list(trigger_match),
                false_positive_risk=round(fuzzy.false_positive_risk, 4),
                recommendation=self._recommendation(event_type, prob, lead_hours),
                timestamp=now,
            ))

        if not predictions and fusion_score > 0.3:
            predictions.append(ClinicalEventPrediction(
                patient_id=patient_id,
                event_type="unspecified_clinical_deterioration",
                probability=round(fusion_score, 4),
                confidence_interval=(round(max(0, fusion_score - 0.2), 4), round(min(1, fusion_score + 0.1), 4)),
                lead_time_hours=36.0,
                lead_time_days=1.5,
                horizon="days",
                evidence_sources=[k for k, v in source_scores.items() if v > 0.2],
                ghost_signals_involved=[g.name for g in ghosts if g.value > 0.3],
                false_positive_risk=0.0,
                recommendation="Monitoramento contínuo — sinais subclínicos detectados.",
                timestamp=now,
            ))

        return sorted(predictions, key=lambda p: p.probability, reverse=True)

    @staticmethod
    def _estimate_lead_time(
        probability: float,
        persistence: float,
        base_hours: float,
        ghost_score: float,
    ) -> float:
        """
        Horizonte preditivo: quanto maior a probabilidade e persistência,
        menor o lead time (evento mais iminente). Ghost signals fortes
        antecipam detecção em 1.5-3x.
        """
        imminence = probability * (0.5 + 0.5 * persistence)
        lead = base_hours * (1.0 - imminence * 0.6)
        if ghost_score > 0.5:
            lead *= 1.8
        return max(2.0, min(168.0, lead))

    @staticmethod
    def _recommendation(event_type: str, prob: float, lead_hours: float) -> str:
        if prob > 0.75:
            urgency = "URGENTE"
        elif prob > 0.5:
            urgency = "PRIORITÁRIO"
        else:
            urgency = "VIGILÂNCIA"

        horizon = f"{lead_hours:.0f}h" if lead_hours < 48 else f"{lead_hours/24:.1f} dias"
        return (
            f"[{urgency}] Risco de {event_type.replace('_', ' ')} "
            f"em ~{horizon}. Confirmar com ECG/SpO2 contínuo e avaliação clínica."
        )