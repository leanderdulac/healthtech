"""
agents.py — Motor Clínico Multi-Agente & Consenso de Evidências (Dempster-Shafer)

Este módulo implementa agentes especialistas autônomos para deliberação clínica:
- CardiologyAgent: Análise hemodinâmica, arritmias, variabilidade cardíaca (HRV) e elastância vascular.
- PulmonologyAgent: Avaliação de trocas gasosas, hipoxemia latente, oximetria e risco respiratório.
- IntensivistTriageAgent: Escalonamento de cuidados intensivos, triagem e alocação de recursos.
- ClinicalConsensusCoordinator: Fusão de crenças via Regra de Combinação de Dempster-Shafer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SpecialistOpinion:
    """Opinião e distribuição de massa de crença emitida por um agente especialista."""

    agent_id: str
    specialty: str
    risk_level: str  # "low", "moderate", "high", "critical"
    confidence: float  # [0.0, 1.0]
    rationale: str
    recommended_actions: List[str]
    supporting_biomarkers: Dict[str, Any]
    # Atribuição de massa básica de crença Dempster-Shafer: m(Critical), m(Elevated), m(Normal), m(Theta)
    mass_assignment: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "specialty": self.specialty,
            "risk_level": self.risk_level,
            "confidence": float(round(self.confidence, 4)),
            "rationale": self.rationale,
            "recommended_actions": self.recommended_actions,
            "supporting_biomarkers": self.supporting_biomarkers,
            "mass_assignment": {k: float(round(v, 4)) for k, v in self.mass_assignment.items()},
        }


class CardiologyAgent:
    """Agente Especialista em Cardiologia e Hemodinâmica."""

    def __init__(self, agent_id: str = "CARDIO-AGENT-01"):
        self.agent_id = agent_id
        self.specialty = "Cardiology & Vascular Dynamics"

    def evaluate(
        self,
        vitals: Dict[str, float],
        phantom_data: Optional[Dict[str, Any]] = None,
        hrv_metrics: Optional[Dict[str, float]] = None,
        hemodynamics: Optional[Dict[str, Any]] = None,
    ) -> SpecialistOpinion:
        """Avalia risco cardiovascular integrando eletrofisiologia, HRV e hemodinâmica."""
        hr = vitals.get("heart_rate", 75.0)
        rmssd = (hrv_metrics or {}).get("rmssd", vitals.get("hrv_rmssd", 40.0))
        sdnn = (hrv_metrics or {}).get("sdnn", 50.0)

        est_sbp = (phantom_data or {}).get("systolic_bp", {}).get("estimate", 120.0) if phantom_data else 120.0
        est_dbp = (phantom_data or {}).get("diastolic_bp", {}).get("estimate", 80.0) if phantom_data else 80.0
        pwv = (hemodynamics or {}).get("pwv_bramwell_hill", 7.5)

        # Cálculo de scores de instabilidade cardiovascular
        arrhythmia_score = 0.0
        if hr > 110 or hr < 50:
            arrhythmia_score += 0.4
        if rmssd < 20.0 or rmssd > 120.0:
            arrhythmia_score += 0.3
        if sdnn < 30.0:
            arrhythmia_score += 0.3

        vascular_score = 0.0
        if est_sbp > 140 or est_dbp > 90:
            vascular_score += 0.4
        if pwv > 10.0:  # Rigidez arterial elevada
            vascular_score += 0.4
        if est_sbp > 170 or est_dbp > 110:
            vascular_score += 0.2

        composite_risk = min(1.0, 0.6 * arrhythmia_score + 0.4 * vascular_score)

        # Determinar nível de risco
        if composite_risk >= 0.7:
            risk_level = "critical"
            rationale = f"Taquicardia/arritmia severa (HR={hr:.1f} bpm, RMSSD={rmssd:.1f} ms) associada a sobrecarga vascular (PAS={est_sbp:.0f} mmHg, PWV={pwv:.1f} m/s)."
            actions = ["Solicitar ECG 12 derivações contínuo", "Administrar antiarrítmico/anti-hipertensivo conforme protocolo", "Avaliação cardiológica presencial imediata"]
        elif composite_risk >= 0.4:
            risk_level = "moderate"
            rationale = f"Instabilidade moderada do tônus autonômico cardíaco (HR={hr:.1f} bpm, PWV={pwv:.1f} m/s)."
            actions = ["Manter telemetria contínua a cada 5 minutos", "Reavaliar curva pressórica em 30 minutos"]
        else:
            risk_level = "low"
            rationale = f"Parâmetros hemodinâmicos e autonômicos dentro do setpoint homeostático (HR={hr:.1f} bpm, PAS={est_sbp:.0f} mmHg)."
            actions = ["Manter vigilância ambulatorial/domiciliar padrão"]

        # Atribuição de massa Dempster-Shafer
        confidence = min(0.95, max(0.60, 1.0 - (0.1 if rmssd < 10 else 0.0)))
        if risk_level == "critical":
            m_crit = 0.70 * confidence
            m_elev = 0.20 * confidence
            m_norm = 0.05 * confidence
        elif risk_level == "moderate":
            m_crit = 0.15 * confidence
            m_elev = 0.65 * confidence
            m_norm = 0.15 * confidence
        else:
            m_crit = 0.02 * confidence
            m_elev = 0.10 * confidence
            m_norm = 0.80 * confidence
        m_theta = 1.0 - (m_crit + m_elev + m_norm)

        return SpecialistOpinion(
            agent_id=self.agent_id,
            specialty=self.specialty,
            risk_level=risk_level,
            confidence=confidence,
            rationale=rationale,
            recommended_actions=actions,
            supporting_biomarkers={
                "heart_rate": hr,
                "hrv_rmssd": rmssd,
                "est_sbp": est_sbp,
                "est_dbp": est_dbp,
                "pwv": pwv,
                "composite_risk": composite_risk,
            },
            mass_assignment={"Critical": m_crit, "Elevated": m_elev, "Normal": m_norm, "Theta": m_theta},
        )


class PulmonologyAgent:
    """Agente Especialista em Pneumologia e Trocas Gasosas."""

    def __init__(self, agent_id: str = "PULMO-AGENT-01"):
        self.agent_id = agent_id
        self.specialty = "Pulmonology & Respiratory Dynamics"

    def evaluate(
        self,
        vitals: Dict[str, float],
        phantom_data: Optional[Dict[str, Any]] = None,
        respiratory_rate: Optional[float] = None,
    ) -> SpecialistOpinion:
        """Avalia risco respiratório e descompensação de oxigenação."""
        spo2_direct = vitals.get("spo2", 97.0)
        est_spo2 = (phantom_data or {}).get("spo2", {}).get("estimate", spo2_direct) if phantom_data else spo2_direct
        rr = respiratory_rate or vitals.get("respiratory_rate", 16.0)

        hypoxemia_score = 0.0
        if est_spo2 < 90.0:
            hypoxemia_score += 0.8
        elif est_spo2 < 94.0:
            hypoxemia_score += 0.4

        if rr > 24.0 or rr < 10.0:
            hypoxemia_score += 0.3

        composite_risk = min(1.0, hypoxemia_score)

        if composite_risk >= 0.7:
            risk_level = "critical"
            rationale = f"Dessaturação grave detectada (SpO2 estimado={est_spo2:.1f}%, FR={rr:.0f} rpm). Risco iminente de insuficiência respiratória hipoxêmica."
            actions = ["Oxigenoterapia imediata (máscara de Venturi ou Cânula)", "Gasometria arterial urgente", "Radiografia de tórax no leito"]
        elif composite_risk >= 0.35:
            risk_level = "moderate"
            rationale = f"Tendência de hipoxemia subclínica ou taquipneia compensatória (SpO2={est_spo2:.1f}%, FR={rr:.0f} rpm)."
            actions = ["Oximetria contínua", "Posicionamento do paciente a 45 graus", "Vigilância de padrão respiratório"]
        else:
            risk_level = "low"
            rationale = f"Troca gasosa e saturação periférica preservadas (SpO2={est_spo2:.1f}%, FR={rr:.0f} rpm)."
            actions = ["Manter monitoramento de rotina"]

        confidence = 0.90
        if risk_level == "critical":
            m_crit = 0.75 * confidence
            m_elev = 0.15 * confidence
            m_norm = 0.05 * confidence
        elif risk_level == "moderate":
            m_crit = 0.10 * confidence
            m_elev = 0.70 * confidence
            m_norm = 0.15 * confidence
        else:
            m_crit = 0.01 * confidence
            m_elev = 0.08 * confidence
            m_norm = 0.85 * confidence
        m_theta = 1.0 - (m_crit + m_elev + m_norm)

        return SpecialistOpinion(
            agent_id=self.agent_id,
            specialty=self.specialty,
            risk_level=risk_level,
            confidence=confidence,
            rationale=rationale,
            recommended_actions=actions,
            supporting_biomarkers={"est_spo2": est_spo2, "respiratory_rate": rr, "composite_risk": composite_risk},
            mass_assignment={"Critical": m_crit, "Elevated": m_elev, "Normal": m_norm, "Theta": m_theta},
        )


class IntensivistTriageAgent:
    """Agente Especialista em Terapia Intensiva, Triagem e Alocação de Recursos."""

    def __init__(self, agent_id: str = "ICU-TRIAGE-01"):
        self.agent_id = agent_id
        self.specialty = "Critical Care & Triage Optimization"

    def evaluate(
        self,
        vitals: Dict[str, float],
        cardio_opinion: SpecialistOpinion,
        pulmo_opinion: SpecialistOpinion,
        bed_pressure: float = 0.5,
    ) -> SpecialistOpinion:
        """Determina a prioridade de leito e necessidade de suporte avançado à vida."""
        cardio_crit = cardio_opinion.mass_assignment.get("Critical", 0.0)
        pulmo_crit = pulmo_opinion.mass_assignment.get("Critical", 0.0)

        systemic_criticality = 0.5 * cardio_crit + 0.5 * pulmo_crit
        if cardio_crit > 0.4 and pulmo_crit > 0.4:
            systemic_criticality += 0.2

        if systemic_criticality >= 0.5:
            risk_level = "critical"
            rationale = f"Instabilidade multissistêmica aguda detectada (Cardio={cardio_opinion.risk_level}, Pulmo={pulmo_opinion.risk_level}). Alta prioridade de transferência para UTI."
            actions = ["Reserva de Leito de UTI imediata", "Acesso venoso central e monitorização invasiva", "Acionamento do Time de Resposta Rápida (TRR)"]
        elif systemic_criticality >= 0.25:
            risk_level = "moderate"
            rationale = f"Comprometimento moderado. Paciente elegível para leito de Semi-Intensiva ou enfermaria monitorizada."
            actions = ["Alocação em leito de enfermaria com telemetria contínua", "Reavaliação médica seriada a cada 2 horas"]
        else:
            risk_level = "low"
            rationale = f"Estabilidade clínica sistêmica. Baixa probabilidade de deterioração aguda no curto prazo."
            actions = ["Elegível para enfermaria geral ou desospitalização segura"]

        confidence = 0.92
        if risk_level == "critical":
            m_crit = 0.80 * confidence
            m_elev = 0.15 * confidence
            m_norm = 0.02 * confidence
        elif risk_level == "moderate":
            m_crit = 0.12 * confidence
            m_elev = 0.72 * confidence
            m_norm = 0.12 * confidence
        else:
            m_crit = 0.01 * confidence
            m_elev = 0.05 * confidence
            m_norm = 0.88 * confidence
        m_theta = 1.0 - (m_crit + m_elev + m_norm)

        return SpecialistOpinion(
            agent_id=self.agent_id,
            specialty=self.specialty,
            risk_level=risk_level,
            confidence=confidence,
            rationale=rationale,
            recommended_actions=actions,
            supporting_biomarkers={"systemic_criticality": systemic_criticality, "bed_pressure": bed_pressure},
            mass_assignment={"Critical": m_crit, "Elevated": m_elev, "Normal": m_norm, "Theta": m_theta},
        )


class ClinicalConsensusCoordinator:
    """Coordenador do Conselho Clínico Multi-Agente baseado em Dempster-Shafer."""

    def __init__(self):
        self.cardio_agent = CardiologyAgent()
        self.pulmo_agent = PulmonologyAgent()
        self.triage_agent = IntensivistTriageAgent()

    @staticmethod
    def combine_dempster_shafer(
        m1: Dict[str, float],
        m2: Dict[str, float],
    ) -> Tuple[Dict[str, float], float]:
        """
        Combina duas distribuições de massa m1 e m2 pelo operador ortogonal de Dempster.
        Espaço focal: {'Critical', 'Elevated', 'Normal', 'Theta'}
        Retorna (massa_fused, conflict_K).
        """
        unnormalized = {"Critical": 0.0, "Elevated": 0.0, "Normal": 0.0, "Theta": 0.0}
        conflict_k = 0.0

        for k1, v1 in m1.items():
            for k2, v2 in m2.items():
                mass_prod = v1 * v2
                if mass_prod == 0.0:
                    continue

                if k1 == "Theta" and k2 == "Theta":
                    unnormalized["Theta"] += mass_prod
                elif k1 == "Theta":
                    unnormalized[k2] += mass_prod
                elif k2 == "Theta":
                    unnormalized[k1] += mass_prod
                elif k1 == k2:
                    unnormalized[k1] += mass_prod
                else:
                    conflict_k += mass_prod

        norm_factor = 1.0 - conflict_k
        if norm_factor <= 1e-6:
            return {"Critical": 0.33, "Elevated": 0.33, "Normal": 0.33, "Theta": 0.01}, 1.0

        fused = {k: v / norm_factor for k, v in unnormalized.items()}
        return fused, conflict_k

    def reach_consensus(
        self,
        patient_id: str,
        vitals: Dict[str, float],
        phantom_data: Optional[Dict[str, Any]] = None,
        hrv_metrics: Optional[Dict[str, float]] = None,
        hemodynamics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Executa a deliberação completa do comitê multi-agente e sintetiza o parecer."""
        op_cardio = self.cardio_agent.evaluate(vitals, phantom_data, hrv_metrics, hemodynamics)
        op_pulmo = self.pulmo_agent.evaluate(vitals, phantom_data)
        op_triage = self.triage_agent.evaluate(vitals, op_cardio, op_pulmo)

        opinions = [op_cardio, op_pulmo, op_triage]

        fused_mass, k1 = self.combine_dempster_shafer(op_cardio.mass_assignment, op_pulmo.mass_assignment)
        final_mass, k2 = self.combine_dempster_shafer(fused_mass, op_triage.mass_assignment)
        total_conflict = min(1.0, k1 + k2)

        prob_critical = final_mass.get("Critical", 0.0)
        prob_elevated = final_mass.get("Elevated", 0.0)
        prob_normal = final_mass.get("Normal", 0.0)

        if prob_critical >= 0.5:
            consensus_risk = "CRITICAL"
            action_summary = "Risco Crítico Iminente — Escalonamento para UTI e Estabilização Imediata"
        elif prob_critical >= 0.25 or prob_elevated >= 0.45:
            consensus_risk = "ELEVATED"
            action_summary = "Risco Clínico Elevado — Vigilância Contínua e Terapia Dirigida"
        else:
            consensus_risk = "NORMAL"
            action_summary = "Condição Fisiológica Estável — Manter Monitoramento Remoto"

        all_actions = []
        for op in opinions:
            for act in op.recommended_actions:
                if act not in all_actions:
                    all_actions.append(act)

        fhir_report = {
            "resourceType": "DiagnosticReport",
            "id": f"diag-consensus-{patient_id.lower()}-{int(datetime.utcnow().timestamp())}",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                            "code": "CG",
                            "display": "Clinical Genetics / AI Consensus",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://healthtech.local/fhir/diagnostic-codes",
                        "code": "AI-MULTI-AGENT-CONSENSUS",
                        "display": "Multi-Agent Clinical Consensus Report",
                    }
                ]
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": datetime.utcnow().isoformat() + "Z",
            "conclusion": f"Consenso Multi-Agente: {consensus_risk}. {action_summary}.",
        }

        return {
            "patient_id": patient_id,
            "timestamp": datetime.utcnow().isoformat(),
            "consensus_risk": consensus_risk,
            "action_summary": action_summary,
            "consensus_probabilities": {
                "critical": float(round(prob_critical, 4)),
                "elevated": float(round(prob_elevated, 4)),
                "normal": float(round(prob_normal, 4)),
                "uncertainty_theta": float(round(final_mass.get("Theta", 0.0), 4)),
            },
            "evidence_conflict_k": float(round(total_conflict, 4)),
            "specialist_opinions": [op.to_dict() for op in opinions],
            "consolidated_actions": all_actions,
            "fhir_diagnostic_report": fhir_report,
        }
