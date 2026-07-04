"""
Motor prognóstico: análise de trajetória temporal e persistência.

Detecta mudanças de regime (CUSUM), calcula persistência de sinais
anômalos e estima horizonte preditivo em horas/dias.
"""

import logging
from typing import Dict, List, Optional

import numpy as np

from src.clinical_intelligence.models import DenoisedSignal, PatientBaseline
from src.clinical_intelligence.signal_processing import WearableSignalProcessor

logger = logging.getLogger(__name__)


class PrognosticEngine:
    """Análise temporal para antecipação de eventos clínicos."""

    def __init__(self):
        self.processor = WearableSignalProcessor()

    def compute_persistence(
        self,
        signals: Dict[str, DenoisedSignal],
        baseline: PatientBaseline,
        threshold_sigma: float = 2.0,
    ) -> float:
        """
        Fração de janelas recentes com desvio sustentado acima do threshold.
        Persistência alta → menor chance de falso positivo.
        """
        persistences = []
        for signal in signals.values():
            dev = self.processor.deviation_from_baseline(signal, baseline)
            if len(dev) < 5:
                continue
            recent = dev[-20:]
            above = np.abs(recent) > threshold_sigma
            run_length = self._max_run_length(above)
            persistences.append(run_length / len(recent))

        return float(np.mean(persistences)) if persistences else 0.0

    def cusum_change_point(
        self,
        signal: DenoisedSignal,
        baseline: PatientBaseline,
        drift: float = 0.5,
    ) -> Dict:
        """
        CUSUM (Cumulative Sum) para detecção de mudança de regime.
        Identifica início de deterioração subclínica.
        """
        dev = self.processor.deviation_from_baseline(signal, baseline)
        if len(dev) < 10:
            return {"detected": False, "change_index": -1, "magnitude": 0.0}

        target = 0.0
        s_pos = np.zeros(len(dev))
        s_neg = np.zeros(len(dev))

        for i in range(1, len(dev)):
            s_pos[i] = max(0, s_pos[i - 1] + dev[i] - target - drift)
            s_neg[i] = max(0, s_neg[i - 1] - dev[i] + target - drift)

        threshold = 4.0
        change_idx = -1
        for i in range(len(dev)):
            if s_pos[i] > threshold or s_neg[i] > threshold:
                change_idx = i
                break

        return {
            "detected": change_idx >= 0,
            "change_index": change_idx,
            "magnitude": float(max(s_pos.max(), s_neg.max())),
            "metric": signal.metric,
        }

    def wearable_risk_score(
        self,
        signals: Dict[str, DenoisedSignal],
        baseline: PatientBaseline,
    ) -> float:
        """Score agregado de risco a partir de sinais diretos filtrados."""
        scores = []

        hr = signals.get("heart_rate")
        if hr and len(hr.filtered) > 0:
            dev = self.processor.deviation_from_baseline(hr, baseline)
            hr_risk = min(1.0, float(np.max(np.abs(dev[-10:]))) / 4.0)
            slope = abs(self.processor.trajectory_slope(hr))
            hr_risk = min(1.0, hr_risk + slope * 0.2)
            scores.append(hr_risk * hr.quality_score)

        spo2 = signals.get("spo2")
        if spo2 and len(spo2.filtered) > 0:
            arr = np.array(spo2.filtered[-10:])
            spo2_risk = max(0.0, (baseline.baseline_spo2 - float(np.min(arr))) / 5.0)
            scores.append(min(1.0, spo2_risk) * spo2.quality_score)

        hrv = signals.get("hrv")
        if hrv and len(hrv.filtered) > 0:
            arr = np.array(hrv.filtered[-10:])
            hrv_risk = max(0.0, (baseline.baseline_hrv - float(np.mean(arr))) / baseline.baseline_hrv)
            scores.append(min(1.0, hrv_risk) * hrv.quality_score)

        return float(np.mean(scores)) if scores else 0.0

    def spo2_risk(self, signals: Dict[str, DenoisedSignal], baseline: PatientBaseline) -> float:
        spo2 = signals.get("spo2")
        if not spo2 or len(spo2.filtered) == 0:
            return 0.0
        arr = np.array(spo2.filtered[-10:])
        return min(1.0, max(0.0, (baseline.baseline_spo2 - float(np.min(arr))) / 5.0))

    def hrv_suppression(self, signals: Dict[str, DenoisedSignal], baseline: PatientBaseline) -> float:
        hrv = signals.get("hrv")
        if not hrv or len(hrv.filtered) == 0:
            return 0.0
        arr = np.array(hrv.filtered[-10:])
        return min(1.0, max(0.0, (baseline.baseline_hrv - float(np.mean(arr))) / baseline.baseline_hrv))

    def hr_deviation(self, signals: Dict[str, DenoisedSignal], baseline: PatientBaseline) -> float:
        hr = signals.get("heart_rate")
        if not hr or len(hr.filtered) == 0:
            return 0.0
        dev = self.processor.deviation_from_baseline(hr, baseline)
        return float(np.mean(np.abs(dev[-10:])))

    def noise_level(self, signals: Dict[str, DenoisedSignal]) -> float:
        if not signals:
            return 0.0
        noise_vals = [s.noise_estimate / max(1.0, abs(s.filtered[-1]) if s.filtered else 1.0) for s in signals.values()]
        return min(1.0, float(np.mean(noise_vals)) * 5)

    def artifact_ratio(self, signals: Dict[str, DenoisedSignal]) -> float:
        if not signals:
            return 0.0
        return float(np.mean([s.artifact_ratio for s in signals.values()]))

    def trajectory_slope(self, signals: Dict[str, DenoisedSignal]) -> float:
        hr = signals.get("heart_rate")
        if not hr:
            return 0.0
        return self.processor.trajectory_slope(hr)

    @staticmethod
    def _max_run_length(mask: np.ndarray) -> int:
        max_run = 0
        current = 0
        for v in mask:
            if v:
                current += 1
                max_run = max(max_run, current)
            else:
                current = 0
        return max_run