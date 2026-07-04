"""
Validação de recursos FHIR R4 contra schemas HL7.
"""

import logging
from typing import Any, Dict, List, Tuple

from src.fhir.compat import fhir_parse
from fhir.resources.bundle import Bundle
from fhir.resources.device import Device
from fhir.resources.flag import Flag
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient

logger = logging.getLogger(__name__)

RESOURCE_VALIDATORS = {
    "Patient": Patient,
    "Observation": Observation,
    "Device": Device,
    "Flag": Flag,
    "Bundle": Bundle,
}


def validate_resource(resource: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Valida um recurso FHIR individual.
    Retorna (válido, lista_de_erros).
    """
    errors = []
    resource_type = resource.get("resourceType")

    if not resource_type:
        return False, ["Campo obrigatório 'resourceType' ausente"]

    validator_cls = RESOURCE_VALIDATORS.get(resource_type)
    if not validator_cls:
        return False, [f"Tipo de recurso não suportado: {resource_type}"]

    try:
        fhir_parse(validator_cls, resource)
        return True, []
    except Exception as e:
        errors.append(str(e))
        return False, errors


def validate_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Valida Bundle FHIR e todos os recursos contidos."""
    is_valid, errors = validate_resource(bundle)
    result = {
        "bundle_valid": is_valid,
        "bundle_errors": errors,
        "entries_total": 0,
        "entries_valid": 0,
        "entries_invalid": 0,
        "resource_counts": {},
        "entry_errors": [],
    }

    if not is_valid:
        return result

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        result["entries_total"] += 1
        rtype = resource.get("resourceType", "Unknown")
        result["resource_counts"][rtype] = result["resource_counts"].get(rtype, 0) + 1

        entry_valid, entry_errors = validate_resource(resource)
        if entry_valid:
            result["entries_valid"] += 1
        else:
            result["entries_invalid"] += 1
            result["entry_errors"].append({
                "resourceType": rtype,
                "id": resource.get("id"),
                "errors": entry_errors,
            })

    result["all_valid"] = result["entries_invalid"] == 0
    return result