"""
Construtores de recursos FHIR R4 conformes ao padrao HL7.
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.device import Device
from fhir.resources.flag import Flag
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient

from src.datalake.schemas.base import DeviceBinding, DeviceType, MetricType
from src.fhir.compat import fhir_parse, fhir_serialize
from src.fhir.terminology import (
    DEVICE_SNOMED,
    HEALTHTECH_DEVICE_SYSTEM,
    HEALTHTECH_PATIENT_SYSTEM,
    HL7_FLAG_CATEGORY,
    OBSERVATION_CATEGORY,
    PROFILE_DEVICE_WEARABLE,
    PROFILE_FLAG_ALERT,
    PROFILE_OBSERVATION_ACTIVITY,
    PROFILE_OBSERVATION_VITAL,
    PROFILE_PATIENT,
    SEVERITY_CODING,
    coding_to_dict,
    get_loinc,
    get_ucum_unit,
)


def _meta(profile: str) -> dict:
    return {"profile": [profile]}


def _reference(resource_type: str, resource_id: str) -> dict:
    return {"reference": f"{resource_type}/{resource_id}"}


def _quantity(value: float, unit: str, ucum_code: str) -> dict:
    return {
        "value": round(value, 2),
        "unit": unit,
        "system": "http://unitsofmeasure.org",
        "code": ucum_code,
    }


def _display_unit(metric: MetricType) -> str:
    labels = {
        MetricType.HEART_RATE: "beats/minute",
        MetricType.SPO2: "%",
        MetricType.HRV: "ms",
        MetricType.STEPS: "steps",
        MetricType.SLEEP_STAGE: "hours",
        MetricType.STRESS_INDEX: "score",
        MetricType.SKIN_TEMP: "Celsius",
        MetricType.RESPIRATORY_RATE: "breaths/minute",
    }
    return labels.get(metric, "score")


def build_patient(
    patient_id: str,
    gender: str = "unknown",
    birth_date: Optional[Union[str, date]] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: str = "BR",
    active: bool = True,
) -> Patient:
    """Constroi recurso FHIR Patient (perfil HealthtechPatient)."""
    safe_id = _fhir_safe_id(patient_id)
    resource: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": safe_id,
        "meta": _meta(PROFILE_PATIENT),
        "identifier": [
            {
                "system": HEALTHTECH_PATIENT_SYSTEM,
                "value": patient_id,
                "use": "official",
            }
        ],
        "active": active,
        "gender": gender,
    }

    if birth_date:
        if isinstance(birth_date, date):
            resource["birthDate"] = birth_date.isoformat()
        else:
            resource["birthDate"] = str(birth_date)

    if city or state or country:
        addr: Dict[str, Any] = {"use": "home", "type": "physical"}
        if city:
            addr["city"] = city
        if state:
            addr["state"] = state
        if country:
            addr["country"] = country
        resource["address"] = [addr]

    return fhir_parse(Patient, resource)


def _fhir_safe_id(raw_id: str) -> str:
    """Normaliza ID para pattern FHIR: [A-Za-z0-9\\-.]."""
    return raw_id.replace("_", "-")


def build_device(binding: DeviceBinding) -> Device:
    """Constroi recurso FHIR Device para wearable."""
    snomed = DEVICE_SNOMED.get(binding.device_type, DEVICE_SNOMED[DeviceType.SMARTWATCH])
    device_id = _fhir_safe_id(binding.device_id)
    resource = {
        "resourceType": "Device",
        "id": device_id,
        "meta": _meta(PROFILE_DEVICE_WEARABLE),
        "identifier": [
            {
                "system": HEALTHTECH_DEVICE_SYSTEM,
                "value": binding.device_id,
            }
        ],
        "displayName": binding.device_type.value,
        "type": [
            {
                "coding": [coding_to_dict(snomed)],
                "text": binding.device_type.value,
            }
        ],
        "manufacturer": binding.vendor,
        "modelNumber": binding.firmware_version,
        "owner": _reference("Patient", _fhir_safe_id(binding.patient_id)),
        "status": "active",
    }
    return fhir_parse(Device, resource)


def build_observation(
    observation_id: str,
    patient_id: str,
    metric: MetricType,
    value: float,
    effective_datetime: datetime,
    device_id: Optional[str] = None,
    status: str = "final",
    is_anomaly: bool = False,
    quality_score: Optional[float] = None,
    components: Optional[List[Dict[str, Any]]] = None,
) -> Observation:
    """Constroi recurso FHIR Observation para telemetria de wearable."""
    loinc = get_loinc(metric)
    if not loinc:
        raise ValueError(f"Metrica sem codigo LOINC: {metric}")

    category = OBSERVATION_CATEGORY.get(metric, OBSERVATION_CATEGORY[MetricType.HEART_RATE])
    profile = (
        PROFILE_OBSERVATION_ACTIVITY
        if category.code == "activity"
        else PROFILE_OBSERVATION_VITAL
    )

    resource: Dict[str, Any] = {
        "resourceType": "Observation",
        "id": observation_id,
        "meta": _meta(profile),
        "status": status,
        "category": [
            {
                "coding": [coding_to_dict(category)],
            }
        ],
        "code": {
            "coding": [coding_to_dict(loinc)],
            "text": loinc.display,
        },
        "subject": _reference("Patient", patient_id),
        "effectiveDateTime": effective_datetime.isoformat(),
        "valueQuantity": _quantity(
            value,
            _display_unit(metric),
            get_ucum_unit(metric),
        ),
    }

    if device_id:
        resource["device"] = _reference("Device", _fhir_safe_id(device_id))

    if is_anomaly:
        resource["interpretation"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": "A",
                        "display": "Abnormal",
                    }
                ]
            }
        ]

    extensions = []
    if quality_score is not None:
        extensions.append({
            "url": "http://healthtech.local/fhir/StructureDefinition/quality-score",
            "valueDecimal": round(quality_score, 3),
        })
    if extensions:
        resource["extension"] = extensions

    if components:
        resource["component"] = components

    return fhir_parse(Observation, resource)


def build_flag(
    flag_id: str,
    patient_id: str,
    alert_type: str,
    severity: str,
    metric_type: str,
    trigger_value: float,
    threshold: float,
    period_start: datetime,
    period_end: datetime,
) -> Flag:
    """Constroi recurso FHIR Flag para alertas clinicos."""
    sev = SEVERITY_CODING.get(severity, SEVERITY_CODING["medium"])
    resource = {
        "resourceType": "Flag",
        "id": flag_id,
        "meta": _meta(PROFILE_FLAG_ALERT),
        "status": "active",
        "category": [
            {
                "coding": [
                    {
                        "system": HL7_FLAG_CATEGORY,
                        "code": "safety",
                        "display": "Safety",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://healthtech.local/fhir/CodeSystem/alert-type",
                    "code": alert_type,
                    "display": alert_type.replace("_", " ").title(),
                }
            ],
            "text": f"{alert_type}: {metric_type}={trigger_value} (limiar={threshold})",
        },
        "subject": _reference("Patient", patient_id),
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
        },
        "extension": [
            {
                "url": "http://healthtech.local/fhir/StructureDefinition/alert-severity",
                "valueCodeableConcept": {
                    "coding": [coding_to_dict(sev)],
                },
            },
            {
                "url": "http://healthtech.local/fhir/StructureDefinition/trigger-metric",
                "valueString": metric_type,
            },
            {
                "url": "http://healthtech.local/fhir/StructureDefinition/trigger-value",
                "valueDecimal": trigger_value,
            },
        ],
    }
    return fhir_parse(Flag, resource)


def build_bundle(
    resources: List[Any],
    bundle_id: str,
    bundle_type: str = "collection",
    timestamp: Optional[datetime] = None,
) -> Bundle:
    """Empacota recursos FHIR em um Bundle HL7."""
    entries = []
    for resource in resources:
        data = fhir_serialize(resource)
        entries.append({
            "fullUrl": f"urn:uuid:{data.get('id', '')}",
            "resource": data,
        })

    bundle_data = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": bundle_type,
        "timestamp": (timestamp or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entry": entries,
    }
    return fhir_parse(Bundle, bundle_data)


def resource_to_dict(resource: Any) -> dict:
    """Serializa recurso FHIR para dict JSON-compativel."""
    return fhir_serialize(resource)