"""
Mapeia recursos FHIR → PatientBaseline para fusão de evidências.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.clinical_intelligence.models import PatientBaseline

logger = logging.getLogger(__name__)

CONDITION_RISK_MAP = {
    "hypertension": 0.15,
    "heart failure": 0.25,
    "coronary artery disease": 0.20,
    "atrial fibrillation": 0.22,
    "diabetes": 0.12,
    "copd": 0.18,
    "asthma": 0.10,
    "sleep apnea": 0.14,
    "chronic kidney disease": 0.16,
}

MEDICATION_RISK_BOOST = {
    "beta blocker": 0.05,
    "anticoagulant": 0.08,
    "diuretic": 0.06,
    "statin": 0.03,
}


class BaselineMapper:
    """Converte bundle FHIR em baseline clínico personalizado."""

    def from_fhir_bundle(
        self,
        patient_id: str,
        patient_resource: Dict,
        conditions: List[Dict],
        medications: List[Dict],
        observations: Optional[List[Dict]] = None,
        wearable_defaults: Optional[Dict] = None,
    ) -> PatientBaseline:
        age = self._extract_age(patient_resource)
        conditions_norm = [self._normalize_condition(c) for c in conditions]
        meds_norm = [self._normalize_medication(m) for m in medications]

        risk = self._compute_risk(conditions_norm, meds_norm)
        defaults = wearable_defaults or {}
        obs = observations or []
        resting_hr, spo2, hrv = self._extract_vitals_from_labs(obs, defaults)

        return PatientBaseline(
            patient_id=patient_id,
            resting_hr=resting_hr,
            baseline_spo2=spo2,
            baseline_hrv=hrv,
            age=age,
            risk_factor=min(1.0, risk),
            activity_level=defaults.get("activity_level", "moderate"),
            clinical_conditions=conditions_norm,
            medications=meds_norm,
        )

    def _extract_age(self, patient: Dict) -> int:
        birth = patient.get("birthDate")
        if not birth:
            return 0
        try:
            born = datetime.strptime(birth[:10], "%Y-%m-%d")
            return max(0, datetime.utcnow().year - born.year)
        except ValueError:
            return 0

    def _normalize_condition(self, condition: Dict) -> str:
        coding = condition.get("code", {}).get("coding", [])
        if coding:
            display = coding[0].get("display", "")
            code = coding[0].get("code", "")
            return (display or code).lower().strip()
        return condition.get("code", {}).get("text", "unknown").lower()

    def _normalize_medication(self, med: Dict) -> str:
        coding = med.get("medicationCodeableConcept", {}).get("coding", [])
        if coding:
            return coding[0].get("display", coding[0].get("code", "")).lower()
        return med.get("medicationCodeableConcept", {}).get("text", "unknown").lower()

    def _compute_risk(self, conditions: List[str], medications: List[str]) -> float:
        risk = 0.05
        for cond in conditions:
            for key, boost in CONDITION_RISK_MAP.items():
                if key in cond:
                    risk += boost
        for med in medications:
            for key, boost in MEDICATION_RISK_BOOST.items():
                if key in med:
                    risk += boost
        return min(1.0, risk)

    def _extract_vitals_from_labs(self, observations: List[Dict], defaults: Dict) -> tuple:
        hr = defaults.get("resting_hr", 70.0)
        spo2 = defaults.get("baseline_spo2", 97.0)
        hrv = defaults.get("baseline_hrv", 50.0)

        for obs in observations:
            code = ""
            coding = obs.get("code", {}).get("coding", [])
            if coding:
                code = coding[0].get("code", "").lower()
            val = self._obs_value(obs)
            if val is None:
                continue
            if "8867-4" in code or "heart rate" in code.lower():
                hr = float(val)
            elif "2708-6" in code or "oxygen" in code.lower():
                spo2 = float(val)
            elif "80404-7" in code or "hrv" in code.lower():
                hrv = float(val)

        return hr, spo2, hrv

    @staticmethod
    def _obs_value(obs: Dict) -> Optional[float]:
        if "valueQuantity" in obs:
            return obs["valueQuantity"].get("value")
        if "component" in obs:
            for comp in obs["component"]:
                v = comp.get("valueQuantity", {}).get("value")
                if v is not None:
                    return float(v)
        return None