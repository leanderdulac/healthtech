"""
Sistema de Inferência Fuzzy (Mamdani) para predição clínica.

Variáveis linguísticas:
  - hr_deviation, spo2_risk, hrv_suppression, ghost_strength, noise_level,
    clinical_burden, persistence, trajectory_slope

Saídas:
  - event_probability, false_positive_risk, noise_gate

Regras projetadas para engenharia biomédica:
  - Suprimir alertas quando ruído alto + persistência baixa
  - Amplificar quando ≥2 sinais fantasmas concordam
  - Modular por comorbidades clínicas (FHIR Conditions)
"""

import logging
from typing import Dict, List, Tuple

import numpy as np

from src.clinical_intelligence.models import FuzzyAssessment, GhostSignal, PatientBaseline

logger = logging.getLogger(__name__)


def _triangular(x: float, a: float, b: float, c: float) -> float:
    if x <= a or x >= c:
        return 0.0
    if x == b:
        return 1.0
    if x < b:
        return (x - a) / (b - a) if b != a else 0.0
    return (c - x) / (c - b) if c != b else 0.0


def _trapezoidal(x: float, a: float, b: float, c: float, d: float) -> float:
    if x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if x < b:
        return (x - a) / (b - a) if b != a else 0.0
    return (d - x) / (d - c) if d != c else 0.0


class FuzzyClinicalEngine:
    """Motor de inferência fuzzy Mamdani para eventos clínicos."""

    OUTPUT_LEVELS = {
        "very_low": 0.1,
        "low": 0.25,
        "moderate": 0.5,
        "high": 0.75,
        "very_high": 0.95,
    }

    def assess(
        self,
        hr_deviation: float,
        spo2_risk: float,
        hrv_suppression: float,
        ghost_signals: List[GhostSignal],
        noise_level: float,
        artifact_ratio: float,
        persistence: float,
        trajectory_slope: float,
        baseline: PatientBaseline,
    ) -> FuzzyAssessment:
        fuzzified = self._fuzzify(
            hr_deviation, spo2_risk, hrv_suppression, ghost_signals,
            noise_level, artifact_ratio, persistence, trajectory_slope, baseline,
        )
        rule_outputs, activations = self._apply_rules(fuzzified)
        event_prob = self._defuzzify(rule_outputs, "event")
        fp_risk = self._defuzzify(rule_outputs, "false_positive")
        noise_gate = self._defuzzify(rule_outputs, "noise_gate")

        event_prob = self._apply_noise_gate(event_prob, noise_gate, artifact_ratio)
        summary = self._linguistic_summary(fuzzified, event_prob, fp_risk)

        return FuzzyAssessment(
            event_probability=round(event_prob, 4),
            false_positive_risk=round(fp_risk, 4),
            noise_gate=round(noise_gate, 4),
            persistence_score=round(persistence, 4),
            rule_activations=activations,
            linguistic_summary=summary,
        )

    def _fuzzify(
        self,
        hr_dev: float,
        spo2_risk: float,
        hrv_sup: float,
        ghosts: List[GhostSignal],
        noise: float,
        artifact: float,
        persistence: float,
        slope: float,
        baseline: PatientBaseline,
    ) -> Dict[str, Dict[str, float]]:
        ghost_strength = max((g.value * g.confidence for g in ghosts), default=0.0)
        clinical_burden = min(1.0, baseline.risk_factor + len(baseline.clinical_conditions) * 0.15)

        return {
            "hr_deviation": {
                "normal": _triangular(abs(hr_dev), 0, 0, 1.5),
                "elevated": _triangular(abs(hr_dev), 1.0, 2.5, 4.0),
                "critical": _trapezoidal(abs(hr_dev), 3.0, 4.5, 8.0, 12.0),
            },
            "spo2_risk": {
                "safe": _triangular(spo2_risk, 0, 0, 0.3),
                "warning": _triangular(spo2_risk, 0.2, 0.5, 0.8),
                "danger": _trapezoidal(spo2_risk, 0.6, 0.8, 1.0, 1.2),
            },
            "hrv_suppression": {
                "normal": _triangular(hrv_sup, 0, 0, 0.25),
                "moderate": _triangular(hrv_sup, 0.15, 0.4, 0.65),
                "severe": _trapezoidal(hrv_sup, 0.5, 0.7, 1.0, 1.2),
            },
            "ghost_strength": {
                "absent": _triangular(ghost_strength, 0, 0, 0.2),
                "present": _triangular(ghost_strength, 0.15, 0.45, 0.75),
                "strong": _trapezoidal(ghost_strength, 0.55, 0.75, 1.0, 1.2),
            },
            "noise_level": {
                "low": _triangular(noise, 0, 0, 0.3),
                "medium": _triangular(noise, 0.2, 0.5, 0.8),
                "high": _trapezoidal(noise, 0.6, 0.8, 1.2, 1.5),
            },
            "persistence": {
                "transient": _triangular(persistence, 0, 0, 0.35),
                "sustained": _triangular(persistence, 0.25, 0.55, 0.85),
                "persistent": _trapezoidal(persistence, 0.7, 0.85, 1.0, 1.2),
            },
            "clinical_burden": {
                "low": _triangular(clinical_burden, 0, 0, 0.35),
                "moderate": _triangular(clinical_burden, 0.25, 0.5, 0.75),
                "high": _trapezoidal(clinical_burden, 0.6, 0.8, 1.0, 1.2),
            },
            "trajectory": {
                "stable": _triangular(abs(slope), 0, 0, 0.3),
                "rising": _triangular(slope, 0.1, 0.5, 1.2),
                "falling": _triangular(-slope, 0.1, 0.5, 1.2),
            },
        }

    def _apply_rules(
        self, f: Dict[str, Dict[str, float]],
    ) -> Tuple[Dict[str, List[Tuple[float, float]]], Dict[str, float]]:
        """
        Regras fuzzy (antecedente → consequente).
        activation = min(antecedentes); output = nível crisp do consequente.
        """
        rules: List[Tuple[float, str, float]] = []
        activations: Dict[str, float] = {}

        def fire(strength: float, name: str, level: str):
            rules.append((strength, "event", self.OUTPUT_LEVELS[level]))
            activations[name] = max(activations.get(name, 0), strength)

        # R1: Ruído alto + persistência baixa → suprimir (falso positivo)
        r1 = min(f["noise_level"]["high"], f["persistence"]["transient"])
        rules.append((r1, "false_positive", 0.9))
        rules.append((r1, "noise_gate", 0.85))
        activations["R1_noise_suppress"] = r1

        # R2: SpO2 danger + ghost strong → evento alto
        r2 = min(f["spo2_risk"]["danger"], f["ghost_strength"]["strong"])
        fire(r2, "R2_hypoxemia_ghost", "very_high")

        # R3: HRV severe + autonomic ghost + sustained
        r3 = min(f["hrv_suppression"]["severe"], f["ghost_strength"]["present"], f["persistence"]["sustained"])
        fire(r3, "R3_autonomic_event", "high")

        # R4: HR critical + clinical burden high → very high
        r4 = min(f["hr_deviation"]["critical"], f["clinical_burden"]["high"])
        fire(r4, "R4_cardiac_critical", "very_high")

        # R5: Ghost strong + trajectory rising + low noise → high
        r5 = min(f["ghost_strength"]["strong"], f["trajectory"]["rising"], f["noise_level"]["low"])
        fire(r5, "R5_ghost_trajectory", "high")

        # R6: HR elevated + transient + medium noise → false positive
        r6 = min(f["hr_deviation"]["elevated"], f["persistence"]["transient"], f["noise_level"]["medium"])
        rules.append((r6, "false_positive", 0.7))
        activations["R6_transient_hr"] = r6

        # R7: Multiple moderate signals + persistent → moderate event
        r7 = min(
            max(f["hr_deviation"]["elevated"], f["hrv_suppression"]["moderate"]),
            f["persistence"]["persistent"],
            f["noise_level"]["low"],
        )
        fire(r7, "R7_persistent_moderate", "moderate")

        # R8: Clinical burden + ghost present → amplify
        r8 = min(f["clinical_burden"]["moderate"], f["ghost_strength"]["present"])
        fire(r8, "R8_clinical_ghost", "moderate")

        # R9: All safe → very low
        r9 = min(f["hr_deviation"]["normal"], f["spo2_risk"]["safe"], f["ghost_strength"]["absent"])
        fire(r9, "R9_all_normal", "very_low")

        outputs: Dict[str, List[Tuple[float, float]]] = {
            "event": [], "false_positive": [], "noise_gate": [],
        }
        for strength, output_type, value in rules:
            if strength > 0.01:
                outputs[output_type].append((strength, value))

        return outputs, activations

    def _defuzzify(self, outputs: Dict[str, List[Tuple[float, float]]], key: str) -> float:
        items = outputs.get(key, [])
        if not items:
            return 0.1 if key == "event" else 0.0
        numerator = sum(s * v for s, v in items)
        denominator = sum(s for s, _ in items)
        return numerator / denominator if denominator > 0 else 0.0

    @staticmethod
    def _apply_noise_gate(probability: float, noise_gate: float, artifact_ratio: float) -> float:
        suppression = noise_gate * 0.5 + artifact_ratio * 0.3
        return max(0.0, probability * (1.0 - min(0.85, suppression)))

    @staticmethod
    def _linguistic_summary(f: Dict, event_prob: float, fp_risk: float) -> str:
        if event_prob > 0.75:
            level = "ALTO risco de evento clínico"
        elif event_prob > 0.5:
            level = "Risco MODERADO — monitoramento intensificado"
        elif event_prob > 0.25:
            level = "Risco BAIXO-MODERADO — vigilância"
        else:
            level = "Risco BAIXO — dentro do esperado"

        if fp_risk > 0.6:
            fp = "Alta probabilidade de falso positivo — sinal suprimido por ruído/transiência."
        elif fp_risk > 0.3:
            fp = "Risco moderado de falso positivo — requer confirmação multimodal."
        else:
            fp = "Baixo risco de falso positivo."

        return f"{level}. {fp}"