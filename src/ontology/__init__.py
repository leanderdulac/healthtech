"""
Módulo de Ontologia Clínica e Ponte Diagnóstica Bayesiana.

Este pacote fornece ferramentas para mapeamento de tópicos LDA a ontologias
clínicas padronizadas (ICD-10, SNOMED-CT, MeSH) e inferência diagnóstica
bayesiana a partir de sinais fantasma (phantom signals) estimados por
algoritmos de decomposição de dados de wearables.
"""

from .clinical_ontology_mapper import (
    CLINICAL_ONTOLOGY,
    ClinicalOntologyMapper,
)
from .phantom_ontology_bridge import (
    BayesianDiagnosticNetwork,
    OntologyEnrichedReport,
)

# Tenta importar classes da ontologia remota
try:
    from src.ontology.registry import MedicalOntologyRegistry
    from src.ontology.feature_enricher import OntologyFeatureEnricher
    from src.ontology.fhir_bridge import OntologyFhirBridge
    _HAS_REMOTE_ONTOLOGY = True
except ImportError:
    _HAS_REMOTE_ONTOLOGY = False

__all__ = [
    "CLINICAL_ONTOLOGY",
    "ClinicalOntologyMapper",
    "BayesianDiagnosticNetwork",
    "OntologyEnrichedReport",
]

if _HAS_REMOTE_ONTOLOGY:
    __all__.extend([
        "MedicalOntologyRegistry",
        "OntologyFeatureEnricher",
        "OntologyFhirBridge",
    ])
