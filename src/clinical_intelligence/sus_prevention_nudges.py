"""
sus_prevention_nudges.py — Motor de Prevenção no SUS & Nudges Clínicos
========================================================================

Este módulo implementa o protocolo de prevenção de internações evitáveis no SUS,
com foco em idosos e populações vulneráveis.

Funcionalidades:
    1. **Detecção Preditiva de Desidratação e ITU (Infecção do Trato Urinário)**:
       Monitora desvios sustentados de HRV, microclima térmico e taquicardia persistente.
    2. **Emissão de Nudges de Autocuidado**:
       Envia notificações de incentivo à hidratação e mobilização.
    3. **Protocolos de Suporte à Decisão para Enfermagem**:
       Sugere ações de cuidado sem substituir o julgamento do profissional de saúde.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SUSPreventionNudgeEngine:
    """
    Motor de Prevenção no SUS e Nudges de Autocuidado para Enfermagem e Pacientes.
    """

    def __init__(self) -> None:
        self.disclaimer = (
            "Aviso: Tecnologia de apoio à tomada de decisão para equipes de saúde "
            "e enfermagem. Não substitui o diagnóstico ou julgamento médico."
        )

    def evaluate_prevention_protocols(
        self,
        patient_age: int,
        hr_series: List[float],
        hrv_series: List[float],
        stress_series: List[float],
        temp_delta: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Avalia o risco de complicações básicas evitáveis (ITU, Desidratação, Crise Hipertensiva/Catecolaminas).
        """
        avg_hr = sum(hr_series) / len(hr_series) if hr_series else 70.0
        avg_hrv = sum(hrv_series) / len(hrv_series) if hrv_series else 50.0
        avg_stress = sum(stress_series) / len(stress_series) if stress_series else 30.0

        nudges: List[str] = []
        nursing_protocols: List[str] = []
        risk_level = "BAIXO"
        condition_detected = None

        is_elderly = patient_age >= 60

        # Protocolo 1: Desidratação em Idosos
        if is_elderly and (avg_hr > 85.0 and avg_hrv < 25.0):
            risk_level = "ALTO" if avg_hr > 95.0 else "MEDIO"
            condition_detected = "Risco de Desidratação Aguda / Distúrbio Eletrolítico"
            nudges.append(
                "🥛 Lembrete de Hidratação: Incentivar ingestão de 200ml de água nas próximas 2 horas."
            )
            nursing_protocols.append(
                "Protocolo Enfermagem SUS: Verificar turgor cutâneo, diurese e ofertar hidratação oral guiada."
            )

        # Protocolo 2: Suspeita de Infecção do Trato Urinário (ITU) em Idosos
        if is_elderly and (avg_hr > 90.0 and avg_stress > 65.0 and temp_delta > 0.5):
            risk_level = "CRITICO"
            condition_detected = "Suspeita Preditiva de ITU (Infecção Urinária) / Infecção Sistêmica"
            nudges.append(
                "⚠️ Alerta de Saúde: Monitorar aparecimento de prostração, febre ou alteração urinária."
            )
            nursing_protocols.append(
                "Protocolo Enfermagem SUS: Coletar elementos físicos de urina (EAS), checar temperatura corporal e reportar ao médico responsável."
            )

        # Protocolo 3: Sobrecarga Adrenérgica / Catecolaminas e Estresse
        if avg_stress > 75.0 and avg_hrv < 20.0:
            if risk_level != "CRITICO":
                risk_level = "MEDIO"
            if not condition_detected:
                condition_detected = "Sobrecarga de Catecolaminas / Estresse Fisiológico Severo"
            nudges.append(
                "🫁 Exercício de Respiração Guiada: Realizar 5 minutos de respiração diafragmática."
            )
            nursing_protocols.append(
                "Protocolo Enfermagem SUS: Avaliar pressão arterial e investigar fatores causais de estresse físico/emocional."
            )

        if not nudges:
            nudges.append("✅ Sinais vitais e microclima estáveis. Manter rotina regular de autocuidado.")
            nursing_protocols.append("Manter monitoramento contínuo regular via wearable.")

        return {
            "timestamp": datetime.now().isoformat(),
            "patient_age": patient_age,
            "is_elderly": is_elderly,
            "risk_level": risk_level,
            "condition_detected": condition_detected or "Nenhuma anomalia detectada",
            "patient_nudges": nudges,
            "nursing_decision_support": nursing_protocols,
            "clinical_disclaimer": self.disclaimer,
        }
