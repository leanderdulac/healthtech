"""
Cliente REST genérico para FHIR Server R4 (HAPI, Azure, GCP Healthcare API).
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.integrations.clinical.config import ClinicalIntegrationConfig

logger = logging.getLogger(__name__)


class FhirServerClient:
    """Cliente HTTP para recursos FHIR R4 com cache local de fallback."""

    def __init__(self, config: Optional[ClinicalIntegrationConfig] = None):
        self.config = config or ClinicalIntegrationConfig()
        self.base_url = self.config.fhir_server_url.rstrip("/")
        self.session = requests.Session()
        if self.config.fhir_server_token:
            self.session.headers["Authorization"] = f"Bearer {self.config.fhir_server_token}"
        self.session.headers["Accept"] = "application/fhir+json"
        self.session.headers["Content-Type"] = "application/fhir+json"
        self.cache_dir = Path(self.config.local_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_live(self) -> bool:
        try:
            resp = self.session.get(f"{self.base_url}/metadata", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def search(
        self,
        resource_type: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{resource_type}"
        try:
            resp = self.session.get(url, params=params or {}, timeout=30)
            resp.raise_for_status()
            bundle = resp.json()
            self._cache_response(resource_type, params, bundle)
            return bundle
        except requests.RequestException as e:
            logger.warning("FHIR search falhou (%s), tentando cache: %s", resource_type, e)
            cached = self._load_cache(resource_type, params)
            if cached:
                return cached
            empty_bundle = {"resourceType": "Bundle", "type": "searchset", "entry": []}
            return empty_bundle

    def read(self, resource_type: str, resource_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/{resource_type}/{resource_id}"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("FHIR read falhou (%s/%s): %s", resource_type, resource_id, e)
            cached = self._load_sample_resource(resource_type, resource_id)
            if cached:
                return cached
            raise

    def search_patients(self, identifier: Optional[str] = None, name: Optional[str] = None) -> List[Dict]:
        params = {}
        if identifier:
            params["identifier"] = identifier
        if name:
            params["name"] = name
        bundle = self.search("Patient", params)
        return self._extract_entries(bundle)

    def get_patient_conditions(self, patient_id: str) -> List[Dict]:
        bundle = self.search("Condition", {"patient": patient_id, "_count": "100"})
        return self._extract_entries(bundle)

    def get_patient_medications(self, patient_id: str) -> List[Dict]:
        bundle = self.search("MedicationRequest", {"subject": patient_id, "_count": "100"})
        return self._extract_entries(bundle)

    def get_patient_observations(
        self,
        patient_id: str,
        category: Optional[str] = "laboratory",
    ) -> List[Dict]:
        params = {"patient": patient_id, "_count": "200", "_sort": "-date"}
        if category:
            params["category"] = category
        bundle = self.search("Observation", params)
        return self._extract_entries(bundle)

    def get_patient_flags(self, patient_id: str) -> List[Dict]:
        bundle = self.search("Flag", {"subject": patient_id, "_count": "100"})
        return self._extract_entries(bundle)

    def _extract_entries(self, bundle: Dict) -> List[Dict]:
        return [e.get("resource", e) for e in bundle.get("entry", []) if e.get("resource")]

    def _cache_key(self, resource_type: str, params: Optional[Dict]) -> str:
        key = f"{resource_type}_{json.dumps(params or {}, sort_keys=True)}"
        import hashlib
        return hashlib.md5(key.encode()).hexdigest()

    def _cache_response(self, resource_type: str, params: Optional[Dict], bundle: Dict) -> None:
        path = self.cache_dir / f"{self._cache_key(resource_type, params)}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cached_at": datetime.utcnow().isoformat(), "bundle": bundle}, f)

    def _load_cache(self, resource_type: str, params: Optional[Dict]) -> Optional[Dict]:
        path = self.cache_dir / f"{self._cache_key(resource_type, params)}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("bundle")
        return self._load_sample_bundle(resource_type)

    def _load_sample_bundle(self, resource_type: str) -> Optional[Dict]:
        fallback = self.cache_dir / f"{resource_type}_sample.json"
        if fallback.exists():
            with open(fallback, encoding="utf-8") as f:
                return json.load(f).get("bundle")
        return None

    def _load_sample_resource(self, resource_type: str, resource_id: str) -> Optional[Dict]:
        bundle = self._load_sample_bundle(resource_type)
        if not bundle:
            return None
        for entry in bundle.get("entry", []):
            res = entry.get("resource", {})
            if res.get("id") == resource_id or resource_type == "Patient":
                return res
        entries = self._extract_entries(bundle)
        return entries[0] if entries else None