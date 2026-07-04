"""
Ontologia médica do projeto — derivada de teses USP e integrada ao FHIR/ML.
"""

from src.ontology.registry import MedicalOntologyRegistry
from src.ontology.feature_enricher import OntologyFeatureEnricher
from src.ontology.fhir_bridge import OntologyFhirBridge

__all__ = [
    "MedicalOntologyRegistry",
    "OntologyFeatureEnricher",
    "OntologyFhirBridge",
]