"""
Módulo FHIR/HL7 — interoperabilidade conforme padrão HL7 FHIR R4.

Recursos suportados: Patient, Device, Observation, Flag, Bundle.
Terminologias: LOINC, UCUM, SNOMED CT, HL7 CodeSystems.
"""

from src.fhir.builders import (
    build_bundle,
    build_device,
    build_flag,
    build_observation,
    build_patient,
    resource_to_dict,
)
from src.fhir.export import FhirExporter
from src.fhir.mappers import (
    bronze_to_observation,
    lakehouse_to_fhir_bundle,
    patient_fhir_mock_to_anonymized,
    silver_row_to_observation,
)
from src.fhir.validator import validate_bundle, validate_resource

__all__ = [
    "FhirExporter",
    "build_bundle",
    "build_device",
    "build_flag",
    "build_observation",
    "build_patient",
    "bronze_to_observation",
    "lakehouse_to_fhir_bundle",
    "patient_fhir_mock_to_anonymized",
    "resource_to_dict",
    "silver_row_to_observation",
    "validate_bundle",
    "validate_resource",
]