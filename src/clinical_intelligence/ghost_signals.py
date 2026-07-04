"""
Detecção de sinais fantasmas (ghost signals).

Biomarcadores inferidos algoritmicamente a partir de combinações de
sinais diretos, hemodinâmica proxy, ontologia e contexto clínico FHIR.
Não são medidos diretamente pelo smartwatch, mas correlacionam com
eventos clínicos com horas/dias de antecedência.
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from src.clinical_intelligence.models import DenoisedSignal, GhostSignal, PatientBaseline
from src.clinical_intelligence.signal_processing import WearableSignalProcessor

logger = logging.getLogger(__name__)


class GhostSignalDetector:
    """
    Extrai sinais latentes com base em teoria de engenharia biomédica:

    1. Desequilíbrio autonômico (HRV suppression + HR elevation)
    2. Acoplamento cardiorrespiratório degradado
    3. Hipoxemia oculta (dips noturnos de SpO2)
    4. Estresse fisiológico desacoplado de atividade
    5. Irregularidade hemodinâmica proxy (variação de pressão de pulso)
    6. Índice de recuperação pós-esforço
    7. Desincronização circadiana
    """

    def __init__(self):
        self.processor = WearableSignalProcessor()

    def detect(
        self,
        signals: Dict[str, DenoisedSignal],
        baseline: PatientBaseline,
        hemodynamic_score: float = 0.0,
        ontology_domains: Optional[Dict[str, float]] = None,
    ) -> List[GhostSignal]:
        ghosts: List[GhostSignal] = []
        hr = signals.get("heart_rate")
        spo2 = signals.get("spo2")
        hrv = signals.get("hrv")
        stress = signals.get("stress")

        ghosts.append(self._autonomic_imbalance(hr, hrv, baseline))
        ghosts.append(self._hidden_hypoxemia(spo2, baseline))
        ghosts.append(self._stress_activity_decoupling(hr, stress, baseline))
        ghosts.append(self._pulse_pressure_irregularity(hr, baseline))
        ghosts.append(self._recovery_deficit(hr, hrv, baseline))
        ghosts.append(self._circadian_desync(hr, baseline))

        if hemodynamic_score > 0:
            ghosts.append(GhostSignal(
                name="hemodynamic_irregularity_proxy",
                value=min(1.0, hemodynamic_score),
                confidence=0.75,
                derivation="hemodynamics_grad_div_curl",
                clinical_relevance="Estenose/aneurisma/turbulência vascular inferida",
                operator="hemodynamics",
            ))

        if ontology_domains:
            cardio = ontology_domains.get("cardiovascular", 0.0)
            if cardio > 0.3:
                ghosts.append(GhostSignal(
                    name="semantic_cardiovascular_risk",
                    value=cardio,
                    confidence=0.6,
                    derivation="medical_ontology_registry",
                    clinical_relevance="Risco cardiovascular contextualizado por ontologia",
                    operator="ontology",
                ))

        return [g for g in ghosts if g.value > 0.05]

    def _autonomic_imbalance(
        self, hr: Optional[DenoisedSignal], hrv: Optional[DenoisedSignal], baseline: PatientBaseline,
    ) -> GhostSignal:
        if not hr or not hrv or len(hr.filtered) < 5:
            return GhostSignal("autonomic_imbalance", 0.0, 0.0, "hrv+hr", "ANS dysfunction")

        hr_dev = self.processor.deviation_from_baseline(hr, baseline)
        hrv_arr = np.array(hrv.filtered)
        hrv_suppression = max(0.0, (baseline.baseline_hrv - np.mean(hrv_arr[-10:])) / baseline.baseline_hrv)
        hr_elevation = max(0.0, float(np.mean(hr_dev[-10:]))) / 3.0

        value = min(1.0, 0.6 * hrv_suppression + 0.4 * hr_elevation)
        confidence = min(hr.quality_score, hrv.quality_score) * 0.9

        return GhostSignal(
            name="autonomic_imbalance",
            value=value,
            confidence=confidence,
            derivation="hrv_suppression + hr_elevation",
            clinical_relevance="Arritmia, ICC descompensada, sepse precoce, evento coronariano",
            operator="inference",
        )

    def _hidden_hypoxemia(
        self, spo2: Optional[DenoisedSignal], baseline: PatientBaseline,
    ) -> GhostSignal:
        if not spo2 or len(spo2.filtered) < 10:
            return GhostSignal("hidden_hypoxemia", 0.0, 0.0, "spo2_night_dips", "Sleep apnea, COPD")

        arr = np.array(spo2.filtered)
        dips = arr[arr < baseline.baseline_spo2 - 2]
        dip_frequency = len(dips) / len(arr)
        dip_depth = max(0.0, baseline.baseline_spo2 - float(np.percentile(arr, 10))) / 5.0

        value = min(1.0, 0.5 * dip_frequency * 5 + 0.5 * dip_depth)
        return GhostSignal(
            name="hidden_hypoxemia",
            value=value,
            confidence=spo2.quality_score * 0.85,
            derivation="spo2_percentile_dips",
            clinical_relevance="Apneia do sono, descompensação respiratória, embolia",
            operator="inference",
        )

    def _stress_activity_decoupling(
        self,
        hr: Optional[DenoisedSignal],
        stress: Optional[DenoisedSignal],
        baseline: PatientBaseline,
    ) -> GhostSignal:
        if not hr or not stress or len(hr.filtered) < 5:
            return GhostSignal("stress_decoupling", 0.0, 0.0, "hr+stress", "Autonomic failure")

        hr_slope = self.processor.trajectory_slope(hr)
        stress_arr = np.array(stress.filtered[-10:])
        stress_high = float(np.mean(stress_arr)) > 60
        hr_rising = hr_slope > 0.3
        low_activity_context = baseline.activity_level == "sedentary"

        value = 0.0
        if stress_high and hr_rising and low_activity_context:
            value = min(1.0, float(np.mean(stress_arr)) / 100)

        return GhostSignal(
            name="stress_activity_decoupling",
            value=value,
            confidence=0.7,
            derivation="hr_slope + stress_without_activity",
            clinical_relevance="Crise hipertensiva, ansiedade patológica, arritmia supraventricular",
            operator="inference",
        )

    def _pulse_pressure_irregularity(
        self, hr: Optional[DenoisedSignal], baseline: PatientBaseline,
    ) -> GhostSignal:
        if not hr or len(hr.filtered) < 15:
            return GhostSignal("pulse_irregularity", 0.0, 0.0, "hr_variability", "Arrhythmia")

        arr = np.array(hr.filtered)
        diffs = np.diff(arr)
        irregularity = float(np.std(diffs)) / max(1.0, float(np.mean(arr)))
        value = min(1.0, irregularity * 5)

        return GhostSignal(
            name="pulse_irregularity",
            value=value,
            confidence=hr.quality_score * (1 - hr.artifact_ratio),
            derivation="hr_beat_to_beat_variation",
            clinical_relevance="FA, extrassístoles, bloqueio AV, flutter",
            operator="inference",
        )

    def _recovery_deficit(
        self,
        hr: Optional[DenoisedSignal],
        hrv: Optional[DenoisedSignal],
        baseline: PatientBaseline,
    ) -> GhostSignal:
        if not hr or not hrv or len(hr.filtered) < 20:
            return GhostSignal("recovery_deficit", 0.0, 0.0, "post_exertion", "Overtraining, HF")

        hr_arr = np.array(hr.filtered)
        peak_idx = int(np.argmax(hr_arr))
        if peak_idx >= len(hr_arr) - 5:
            return GhostSignal("recovery_deficit", 0.0, 0.0, "post_exertion", "Overtraining, HF")

        recovery_window = hr_arr[peak_idx:peak_idx + 10]
        if len(recovery_window) < 5:
            return GhostSignal("recovery_deficit", 0.0, 0.0, "post_exertion", "Overtraining, HF")

        recovery_rate = (recovery_window[0] - recovery_window[-1]) / max(1, len(recovery_window))
        slow_recovery = max(0.0, 1.0 - recovery_rate / 2.0)

        hrv_arr = np.array(hrv.filtered)
        hrv_recovery = max(0.0, (baseline.baseline_hrv - float(np.mean(hrv_arr[-5:]))) / baseline.baseline_hrv)
        value = min(1.0, 0.5 * slow_recovery + 0.5 * hrv_recovery)

        return GhostSignal(
            name="recovery_deficit",
            value=value,
            confidence=0.65,
            derivation="hr_recovery_slope + hrv_suppression",
            clinical_relevance="Insuficiência cardíaca, miocardite, overtraining syndrome",
            operator="inference",
        )

    def _circadian_desync(
        self, hr: Optional[DenoisedSignal], baseline: PatientBaseline,
    ) -> GhostSignal:
        if not hr or len(hr.filtered) < 24:
            return GhostSignal("circadian_desync", 0.0, 0.0, "hr_circadian", "Shift work disorder")

        arr = np.array(hr.filtered)
        n = len(arr)
        first_half = arr[:n // 2]
        second_half = arr[n // 2:]
        expected_drop = baseline.resting_hr * 0.08
        actual_drop = float(np.mean(first_half)) - float(np.mean(second_half))
        desync = max(0.0, (expected_drop - actual_drop) / max(1.0, expected_drop))

        return GhostSignal(
            name="circadian_desync",
            value=min(1.0, desync),
            confidence=0.55,
            derivation="hr_day_night_amplitude",
            clinical_relevance="Distúrbio circadiano, depressão, apneia, evento cardiovascular noturno",
            operator="inference",
        )