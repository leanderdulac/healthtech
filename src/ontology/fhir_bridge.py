"""
Ponte ontologia → FHIR CodeSystem / extensões HL7.
"""

from datetime import datetime
from typing import Dict, List, Optional

from src.fhir.builders import resource_to_dict
from src.fhir.compat import fhir_parse
from src.fhir.terminology import IG_BASE
from src.ontology.registry import MedicalOntologyRegistry

ONTOLOGY_SYSTEM = f"{IG_BASE}/CodeSystem/healthtech-ontology"
ONTOLOGY_PROFILE = f"{IG_BASE}/HealthtechMedicalOntology"


class OntologyFhirBridge:
    """Exporta conceitos da ontologia como recursos FHIR."""

    def __init__(self, registry: Optional[MedicalOntologyRegistry] = None):
        self.registry = registry or MedicalOntologyRegistry()
        if not self.registry.is_loaded:
            self.registry.load()

    def build_codesystem(self) -> dict:
        concepts = []
        for item in self.registry.get_top_keywords(100):
            concepts.append({
                "code": item["keyword"].replace(" ", "-")[:60],
                "display": item["keyword"],
                "definition": f"Conceito médico (freq={item['count']}) da ontologia USP",
            })

        for item in self.registry.get_top_areas(30):
            concepts.append({
                "code": f"area-{item['area'][:40].replace(' ', '-')}",
                "display": item["area"],
                "definition": f"Área de concentração USP (n={item['count']})",
            })

        return {
            "resourceType": "CodeSystem",
            "id": "healthtech-medical-ontology",
            "meta": {"profile": [ONTOLOGY_PROFILE]},
            "url": ONTOLOGY_SYSTEM,
            "version": "1.0.0",
            "name": "HealthtechMedicalOntology",
            "title": "Ontologia Médica Healthtech (USP Teses)",
            "status": "active",
            "experimental": True,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "publisher": "Healthtech",
            "description": "Ontologia derivada de teses e dissertações de medicina da USP",
            "content": "complete",
            "concept": concepts,
        }

    def enrich_flag_extensions(
        self,
        flag_resource: dict,
        alert_text: str,
    ) -> dict:
        if not self.registry.is_loaded:
            return flag_resource

        keywords = self.registry.match_keywords(alert_text, top_k=5)
        domains = self.registry.domain_scores(alert_text)

        extensions = flag_resource.get("extension", [])
        for kw, score in keywords:
            extensions.append({
                "url": f"{IG_BASE}/StructureDefinition/ontology-keyword",
                "valueCodeableConcept": {
                    "coding": [{
                        "system": ONTOLOGY_SYSTEM,
                        "code": kw.replace(" ", "-")[:60],
                        "display": kw,
                    }],
                    "text": kw,
                },
            })

        if domains:
            top_domain = max(domains, key=domains.get)
            extensions.append({
                "url": f"{IG_BASE}/StructureDefinition/ontology-domain",
                "valueCode": top_domain,
            })

        if extensions:
            flag_resource["extension"] = extensions
        return flag_resource

    def export_bundle_entry(self) -> Optional[dict]:
        if not self.registry.is_loaded:
            return None
        cs = self.build_codesystem()
        return {
            "fullUrl": f"urn:uuid:{cs['id']}",
            "resource": cs,
        }