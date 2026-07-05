"""
Bridge FHIR → modelos internos (PatientBaseline, EvidenceFusionEngine).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.clinical_intelligence.evidence_fusion import EvidenceFusionEngine
from src.clinical_intelligence.models import PatientBaseline
from src.integrations.clinical.baseline_mapper import BaselineMapper
from src.integrations.clinical.config import ClinicalIntegrationConfig
from src.integrations.clinical.fhir_client import FhirServerClient

logger = logging.getLogger(__name__)


class ClinicalDataBridge:
    """
    Sincroniza dados clínicos reais do FHIR Server e integra
    com o motor de fusão de evidências multimodal.
    """

    def __init__(
        self,
        config: Optional[ClinicalIntegrationConfig] = None,
        client: Optional[FhirServerClient] = None,
    ):
        self.config = config or ClinicalIntegrationConfig()
        self.client = client or FhirServerClient(self.config)
        self.mapper = BaselineMapper()
        self.fusion = EvidenceFusionEngine()
        self.output_dir = Path(self.config.local_cache_dir) / "baselines"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def sync_patient(
        self,
        patient_id: str,
        fhir_patient_id: Optional[str] = None,
        wearable_defaults: Optional[Dict] = None,
    ) -> PatientBaseline:
        fhir_id = fhir_patient_id or patient_id

        try:
            patient = self.client.read("Patient", fhir_id)
        except Exception:
            patients = self.client.search_patients(identifier=patient_id)
            patient = patients[0] if patients else self._sample_patient(patient_id)

        conditions = self.client.get_patient_conditions(fhir_id)
        medications = self.client.get_patient_medications(fhir_id)
        observations = self.client.get_patient_observations(fhir_id)
        flags = self.client.get_patient_flags(fhir_id)

        baseline = self.mapper.from_fhir_bundle(
            patient_id=patient_id,
            patient_resource=patient,
            conditions=conditions,
            medications=medications,
            observations=observations,
            wearable_defaults=wearable_defaults,
        )

        self._save_baseline(baseline, flags)
        return baseline

    def sync_cohort(
        self,
        patient_ids: List[str],
        wearable_defaults_map: Optional[Dict[str, Dict]] = None,
    ) -> Dict[str, PatientBaseline]:
        defaults_map = wearable_defaults_map or {}
        baselines = {}
        errors = []

        for pid in patient_ids:
            try:
                baselines[pid] = self.sync_patient(
                    patient_id=pid,
                    wearable_defaults=defaults_map.get(pid),
                )
            except Exception as e:
                errors.append({"patient_id": pid, "error": str(e)})
                logger.warning("Sync falhou para %s: %s", pid, e)

        return baselines

    def enrich_fusion_clinical_score(
        self,
        baseline: PatientBaseline,
        wearable_score: float = 0.0,
    ) -> float:
        return self.fusion._clinical_score(baseline)

    def get_clinical_events(self, patient_id: str) -> List[Dict]:
        """Ground truth clínico: Flags e Conditions ativas."""
        fhir_id = patient_id
        events = []

        for flag in self.client.get_patient_flags(fhir_id):
            events.append({
                "type": "flag",
                "resource_id": flag.get("id"),
                "code": self._extract_code(flag),
                "period_start": flag.get("period", {}).get("start"),
                "status": flag.get("status"),
            })

        for cond in self.client.get_patient_conditions(fhir_id):
            if cond.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") == "active":
                events.append({
                    "type": "condition",
                    "resource_id": cond.get("id"),
                    "code": self._extract_code(cond),
                    "onset": cond.get("onsetDateTime") or cond.get("recordedDate"),
                    "status": "active",
                })

        return events

    def _save_baseline(self, baseline: PatientBaseline, flags: List[Dict]) -> Path:
        path = self.output_dir / f"{baseline.patient_id}_baseline.json"
        payload = {
            "synced_at": datetime.utcnow().isoformat(),
            "baseline": baseline.to_dict(),
            "active_flags": len(flags),
            "fhir_live": self.client.is_live,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path

    @staticmethod
    def _extract_code(resource: Dict) -> str:
        coding = resource.get("code", {}).get("coding", [])
        if coding:
            return coding[0].get("display", coding[0].get("code", ""))
        return resource.get("code", {}).get("text", "unknown")

    @staticmethod
    def _sample_patient(patient_id: str) -> Dict:
        return {
            "resourceType": "Patient",
            "id": patient_id,
            "birthDate": "1970-01-01",
            "name": [{"family": "Sample", "given": ["Patient"]}],
        }