"""
Análise de incentivos e modelagem de Teoria dos Jogos aplicada à medicina interna.
Mapeia os modelos do artigo PMC9924631 (Dilema do Prisioneiro, Centopeia, Stag Hunt, Chicken).
"""

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.clinical_intelligence.models import DenoisedSignal, GhostSignal, PatientBaseline

logger = logging.getLogger(__name__)


@dataclass
class GameTheoryAssessment:
    """Métricas de incentivos e riscos de Teoria dos Jogos."""

    patient_id: str
    ama_evasion_risk: float         # Risco de alta à revelia / evasão (Jogo da Centopeia)
    overtreatment_pressure: float   # Pressão para sobretratamento fútil (Dilema do Prisioneiro)
    discharge_assurance: float      # Confiança de cooperação pós-alta (Stag Hunt / Jogo da Confiança)
    team_deadlock_risk: float       # Risco de impasse assistencial interdisciplinar (Jogo do Frango)
    recommended_alignment: str      # Ação de alinhamento recomendada

    def to_dict(self) -> Dict:
        return asdict(self)


class GameTheoryAligner:
    """
    Motor de alinhamento de incentivos. 
    Analisa interações clínicas e dados biométricos como escolhas em jogos estratégicos.
    """

    def evaluate_dynamics(
        self,
        baseline: PatientBaseline,
        signals: Dict[str, DenoisedSignal],
        ghost_signals: List[GhostSignal],
        clinical_complexity_score: float,
    ) -> GameTheoryAssessment:
        """
        Avalia o estado dinâmico do paciente sob a ótica de incentivos.
        """
        # 1. Jogo da Centopeia: Risco de Alta à Revelia (AMA Evasion Risk)
        # Ocorre em sequências iteradas onde o estresse alto ou falta de analgesia estimula deserção.
        stress_signal = signals.get("stress")
        avg_stress = 0.0
        if stress_signal and len(stress_signal.filtered) > 0:
            avg_stress = float(np.mean(stress_signal.filtered[-10:]))

        has_sud = any(
            c in " ".join(baseline.clinical_conditions).lower()
            for c in ["substance", "opioid", "abuse", "addiction", "dependencia", "alcoolismo"]
        )
        
        autonomic_strain = 0.0
        for g in ghost_signals:
            if g.name == "autonomic_imbalance":
                autonomic_strain = g.value * g.confidence

        # Se o paciente está cooperando e usando muito o relógio, o risco AMA cai levemente (sinal de cooperação no jogo)
        wear_compliance = 1.0
        for s in signals.values():
            if len(s.filtered) < 5:
                wear_compliance *= 0.8

        ama_risk = 0.1
        if has_sud:
            ama_risk += 0.35
        if avg_stress > 0.6:
            ama_risk += 0.25
        if autonomic_strain > 0.4:
            ama_risk += 0.20
        
        # Reduz risco baseado em conformidade de wear
        ama_risk = max(0.05, min(0.95, ama_risk * (1.2 - 0.4 * wear_compliance)))

        # 2. Dilema do Prisioneiro: Pressão de Sobretratamento (Overtreatment Pressure)
        # Induzido por incerteza diagnóstica (ruído/sinal de má qualidade) e queixas subjetivas (vagas)
        telemetry_quality = 1.0
        noise_level = 0.0
        if signals:
            telemetry_quality = float(np.mean([s.quality_score for s in signals.values()]))
            # Estimativa de ruído
            noise_estimates = []
            for s in signals.values():
                denom = max(1.0, abs(s.filtered[-1]) if s.filtered else 1.0)
                noise_estimates.append(s.noise_estimate / denom)
            noise_level = float(np.mean(noise_estimates))

        vague_history = any(
            c in " ".join(baseline.clinical_conditions).lower()
            for c in ["somatoform", "fibromyalgia", "chronic pain", "unspecified", "fadiga", "ansiedade"]
        )

        overtreatment = 0.25
        if vague_history:
            overtreatment += 0.25
        if telemetry_quality < 0.6:
            overtreatment += 0.25
        if noise_level > 0.15:
            overtreatment += 0.15

        overtreatment = max(0.05, min(0.95, overtreatment))

        # 3. Jogo da Confiança (Stag Hunt): Garantia de Alta (Discharge Cooperation Assurance)
        # Mede a segurança de dar alta segura. Aderência alta ao wearable + sinais estáveis = caçar cervo (alta segura).
        vitals_stable = True
        for s in signals.values():
            if len(s.filtered) >= 10:
                recent_std = float(np.std(s.filtered[-10:]))
                recent_mean = float(np.mean(s.filtered[-10:]))
                # Se desvia demais do desvio normal, sinaliza instabilidade
                if recent_std > 0.3 * (recent_mean if recent_mean != 0 else 1.0):
                    vitals_stable = False
                    break
        
        assurance = 0.20
        if telemetry_quality > 0.8:
            assurance += 0.35
        if vitals_stable:
            assurance += 0.30
        
        # Reduz se o paciente tem complexidade clínica crítica recente
        if clinical_complexity_score > 0.7:
            assurance -= 0.25
            
        assurance = max(0.05, min(0.95, assurance))

        # 4. Jogo do Frango (Chicken): Risco de Impasse Assistencial (Team Deadlock Risk)
        # Ocorre em pacientes limiares com risco complexo multifatorial (ex: hemodinâmica instável + metabólica instável)
        # onde as especialidades médicas evitam assumir a responsabilidade direta ou discordam da conduta.
        has_cardio = any("cardio" in c or "heart" in c or "hipertensao" in c for c in baseline.clinical_conditions)
        has_renal_or_pulm = any(
            c in " ".join(baseline.clinical_conditions).lower()
            for c in ["kidney", "renal", "copd", "pulmonary", "respiratorio", "pneumo", "asma"]
        )
        
        deadlock_risk = 0.1
        # Pacientes "cardiorrenais" ou "cardiopulmonares" têm alto risco de impasse de especialidades
        if has_cardio and has_renal_or_pulm:
            deadlock_risk += 0.35
        if clinical_complexity_score > 0.6:
            deadlock_risk += 0.25
        if telemetry_quality < 0.5:
            deadlock_risk += 0.15
            
        deadlock_risk = max(0.05, min(0.95, deadlock_risk))

        # Ações de Alinhamento Clínico Recomendadas
        if ama_risk > 0.65:
            rec = (
                "Risco crítico de evasão (AMA) - Jogo da Centopeia. Ação: Realinhar incentivos "
                "via otimização analgésica ativa, apoio psicossocial e reavaliação de restrições de leito."
            )
        elif deadlock_risk > 0.7:
            rec = (
                "Risco de impasse assistencial (Jogo do Frango) detectado entre especialidades. "
                "Ação: Convocar rodada clínica multidisciplinar para definição imediata de conduta "
                "e responsabilização de tarefas."
            )
        elif overtreatment > 0.7:
            rec = (
                "Elevada pressão por sobretratamento (Dilema do Prisioneiro) devido à incerteza. "
                "Ação: Apresentar relatório de estabilidade de telemetria contínua limpa (Gold) "
                "para apoiar vigilância ativa ao invés de exames invasivos redundantes."
            )
        elif assurance > 0.75:
            rec = (
                "Excelente garantia de cooperação (Stag Hunt). Ação: Elegível para alta precoce "
                "segura com transição para monitoramento domiciliar remoto via telemetria contínua."
            )
        else:
            rec = "Manter monitoramento de telemetria padrão. Incentivos clínicos alinhados."

        return GameTheoryAssessment(
            patient_id=baseline.patient_id,
            ama_evasion_risk=round(ama_risk, 4),
            overtreatment_pressure=round(overtreatment, 4),
            discharge_assurance=round(assurance, 4),
            team_deadlock_risk=round(deadlock_risk, 4),
            recommended_alignment=rec,
        )

# Adição do Jogo de Triagem e Alocação de Recursos (Triage Game)

@dataclass
class TriageAllocationResult:
    patient_id: str
    bed_type_recommended: str  # 'ICU', 'StepDown', 'Ward'
    nash_equilibrium_strategy: Dict[str, float]
    pareto_efficiency_score: float
    urgency_index: float
    resource_congestion_factor: float


class TriageGameEngine:
    """
    Modela o jogo não-cooperativo e cooperativo entre o médico emergencista e o gestor
    de leitos para alocação ótima em cenário de escassez de recursos hospitalares.
    """

    def evaluate_triage(
        self,
        patient_id: str,
        clinical_severity: float,
        icu_occupancy_ratio: float = 0.85,
        risk_progression: float = 0.40
    ) -> TriageAllocationResult:
        """
        Calcula o Equilíbrio de Nash e Alocação de Pareto para o paciente.
        """
        # Matriz de Payoff (Médico Emergencista vs Gestor de Leitos)
        # Estratégias: [Solicitar UTI, Solicitar Semi-Intensiva, Solicitar Enfermaria]
        urgency = 0.6 * clinical_severity + 0.4 * risk_progression

        if urgency > 0.70 or (urgency > 0.50 and icu_occupancy_ratio < 0.90):
            bed_type = "ICU"
            pareto_score = 0.92
            nash_strat = {"ICU": 0.85, "StepDown": 0.10, "Ward": 0.05}
        elif urgency > 0.40:
            bed_type = "StepDown"
            pareto_score = 0.88
            nash_strat = {"ICU": 0.15, "StepDown": 0.75, "Ward": 0.10}
        else:
            bed_type = "Ward"
            pareto_score = 0.95
            nash_strat = {"ICU": 0.02, "StepDown": 0.18, "Ward": 0.80}

        return TriageAllocationResult(
            patient_id=patient_id,
            bed_type_recommended=bed_type,
            nash_equilibrium_strategy=nash_strat,
            pareto_efficiency_score=pareto_score,
            urgency_index=float(urgency),
            resource_congestion_factor=float(icu_occupancy_ratio)
        )

    def solve_triage_game(
        self,
        icu_capacity: int = 10,
        ward_capacity: int = 40,
        icu_demand: int = 14,
        ward_demand: int = 35,
        high_risk_fraction: float = 0.4
    ) -> Dict[str, Any]:
        """
        Calcula o Equilíbrio de Nash e a Fronteira de Pareto para o jogo de alocação de leitos.
        """
        icu_congestion = min(1.5, icu_demand / max(1, icu_capacity))
        ward_congestion = min(1.5, ward_demand / max(1, ward_capacity))

        if icu_congestion > 1.2:
            nash_strategy = "Triagem Restritiva de UTI com Escalonamento em Semi-Intensiva"
            icu_allocated = icu_capacity
            ward_allocated = min(ward_capacity, ward_demand + (icu_demand - icu_capacity))
            nash_probs = {"ICU_Priority": 0.35, "StepDown_Buffer": 0.55, "Ward_Direct": 0.10}
            recommendation = "Alocar leitos de UTI estritamente para choque refratário e insuficiência respiratória grave. Expandir leitos monitorizados de enfermaria."
        elif icu_congestion > 0.9:
            nash_strategy = "Alocação Balanceada de Recursos Críticos"
            icu_allocated = min(icu_capacity, icu_demand)
            ward_allocated = min(ward_capacity, ward_demand)
            nash_probs = {"ICU_Priority": 0.70, "StepDown_Buffer": 0.20, "Ward_Direct": 0.10}
            recommendation = "Equilíbrio sustentável. Monitorar rotatividade de leitos nas próximas 12 horas."
        else:
            nash_strategy = "Admissão Liberal em UTI / Suporte Total"
            icu_allocated = icu_demand
            ward_allocated = ward_demand
            nash_probs = {"ICU_Priority": 0.90, "StepDown_Buffer": 0.08, "Ward_Direct": 0.02}
            recommendation = "Capacidade hospitalar preservada. Todos os pacientes críticos elegíveis podem ser admitidos na UTI."

        pareto_points = []
        for i in range(max(1, icu_capacity - 4), icu_capacity + 1):
            w = min(ward_capacity, ward_capacity - int((icu_capacity - i) * 1.5))
            pareto_points.append({"icu_allocated": i, "ward_allocated": w})

        return {
            "nash_equilibrium": {
                "strategy": nash_strategy,
                "probabilities": nash_probs,
                "icu_allocated": icu_allocated,
                "ward_allocated": ward_allocated
            },
            "congestion": {
                "icu_congestion_ratio": float(round(icu_congestion, 2)),
                "ward_congestion_ratio": float(round(ward_congestion, 2))
            },
            "pareto_frontier": pareto_points,
            "clinical_recommendation": recommendation
        }
