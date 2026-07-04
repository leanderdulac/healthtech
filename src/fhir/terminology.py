"""
Terminologias HL7/FHIR para interoperabilidade de saúde.

Referências:
  - HL7 FHIR R4: http://hl7.org/fhir/R4/
  - LOINC: https://loinc.org/
  - UCUM: http://unitsofmeasure.org/
  - SNOMED CT: http://snomed.info/sct
"""

from dataclasses import dataclass
from typing import Dict, Optional

from src.datalake.schemas.base import DeviceType, MetricType


# --- Sistemas de codificação HL7 ---

LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"
SNOMED_SYSTEM = "http://snomed.info/sct"
HL7_OBSERVATION_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
HL7_V3_ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
HL7_FLAG_CATEGORY = "http://terminology.hl7.org/CodeSystem/flag-category"
HL7_DEVICE_NAME_TYPE = "http://hl7.org/fhir/device-nametype"

# Identificadores brasileiros (RNDS / OpenHL7)
BR_CPF_SYSTEM = "urn:oid:2.16.840.1.113883.13.236"
BR_CNS_SYSTEM = "urn:oid:2.16.840.1.113883.13.236.1"
HEALTHTECH_PATIENT_SYSTEM = "urn:healthtech:patient"
HEALTHTECH_DEVICE_SYSTEM = "urn:healthtech:device"

# Perfis FHIR do projeto (Implementation Guide)
IG_BASE = "http://healthtech.local/fhir/StructureDefinition"
PROFILE_PATIENT = f"{IG_BASE}/HealthtechPatient"
PROFILE_OBSERVATION_VITAL = f"{IG_BASE}/HealthtechVitalSignObservation"
PROFILE_OBSERVATION_ACTIVITY = f"{IG_BASE}/HealthtechActivityObservation"
PROFILE_DEVICE_WEARABLE = f"{IG_BASE}/HealthtechWearableDevice"
PROFILE_FLAG_ALERT = f"{IG_BASE}/HealthtechClinicalAlert"


@dataclass(frozen=True)
class FhirCoding:
    system: str
    code: str
    display: str


# LOINC para sinais vitais e atividade (wearables)
METRIC_LOINC: Dict[MetricType, FhirCoding] = {
    MetricType.HEART_RATE: FhirCoding(LOINC_SYSTEM, "8867-4", "Heart rate"),
    MetricType.SPO2: FhirCoding(LOINC_SYSTEM, "2708-6", "Oxygen saturation in Arterial blood"),
    MetricType.HRV: FhirCoding(LOINC_SYSTEM, "80404-7", "R-R interval.standard deviation (Heart rate variability)"),
    MetricType.STEPS: FhirCoding(LOINC_SYSTEM, "55423-8", "Number of steps"),
    MetricType.SLEEP_STAGE: FhirCoding(LOINC_SYSTEM, "93832-4", "Sleep duration"),
    MetricType.STRESS_INDEX: FhirCoding(LOINC_SYSTEM, "8693-4", "Mental status"),
    MetricType.SKIN_TEMP: FhirCoding(LOINC_SYSTEM, "8310-5", "Body temperature"),
    MetricType.RESPIRATORY_RATE: FhirCoding(LOINC_SYSTEM, "9279-1", "Respiratory rate"),
}

# UCUM para unidades
METRIC_UCUM: Dict[MetricType, str] = {
    MetricType.HEART_RATE: "/min",
    MetricType.SPO2: "%",
    MetricType.HRV: "ms",
    MetricType.STEPS: "{steps}",
    MetricType.SLEEP_STAGE: "h",
    MetricType.STRESS_INDEX: "{score}",
    MetricType.SKIN_TEMP: "Cel",
    MetricType.RESPIRATORY_RATE: "/min",
}

# SNOMED para tipos de dispositivo wearable
DEVICE_SNOMED: Dict[DeviceType, FhirCoding] = {
    DeviceType.SMARTWATCH: FhirCoding(SNOMED_SYSTEM, "706767009", "Wearable cardiac monitor"),
    DeviceType.FITNESS_BAND: FhirCoding(SNOMED_SYSTEM, "706767009", "Wearable cardiac monitor"),
    DeviceType.CHEST_STRAP: FhirCoding(SNOMED_SYSTEM, "706172005", "Cardiac telemetry device"),
    DeviceType.RING: FhirCoding(SNOMED_SYSTEM, "706767009", "Wearable cardiac monitor"),
}

OBSERVATION_CATEGORY: Dict[MetricType, FhirCoding] = {
    MetricType.HEART_RATE: FhirCoding(HL7_OBSERVATION_CATEGORY, "vital-signs", "Vital Signs"),
    MetricType.SPO2: FhirCoding(HL7_OBSERVATION_CATEGORY, "vital-signs", "Vital Signs"),
    MetricType.HRV: FhirCoding(HL7_OBSERVATION_CATEGORY, "vital-signs", "Vital Signs"),
    MetricType.STEPS: FhirCoding(HL7_OBSERVATION_CATEGORY, "activity", "Activity"),
    MetricType.SLEEP_STAGE: FhirCoding(HL7_OBSERVATION_CATEGORY, "activity", "Activity"),
    MetricType.STRESS_INDEX: FhirCoding(HL7_OBSERVATION_CATEGORY, "survey", "Survey"),
    MetricType.SKIN_TEMP: FhirCoding(HL7_OBSERVATION_CATEGORY, "vital-signs", "Vital Signs"),
    MetricType.RESPIRATORY_RATE: FhirCoding(HL7_OBSERVATION_CATEGORY, "vital-signs", "Vital Signs"),
}

SEVERITY_CODING = {
    "low": FhirCoding(HL7_V3_ACT_CODE, "L", "low"),
    "medium": FhirCoding(HL7_V3_ACT_CODE, "M", "moderate"),
    "high": FhirCoding(HL7_V3_ACT_CODE, "H", "high"),
    "critical": FhirCoding(HL7_V3_ACT_CODE, "CRIT", "critical"),
}


def coding_to_dict(coding: FhirCoding) -> dict:
    return {"system": coding.system, "code": coding.code, "display": coding.display}


def get_loinc(metric: MetricType) -> Optional[FhirCoding]:
    return METRIC_LOINC.get(metric)


def get_ucum_unit(metric: MetricType) -> str:
    return METRIC_UCUM.get(metric, "{score}")