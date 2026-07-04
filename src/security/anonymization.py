import copy
import hashlib
import os

from dotenv import load_dotenv

load_dotenv()

FHIR_DEID_PROFILE = "http://hl7.org/fhir/uv/anonymization/StructureDefinition/anonymized"
HEALTHTECH_PATIENT_SYSTEM = "urn:healthtech:patient"


def anonimizar_paciente_fhir(paciente_fhir: dict) -> dict:
    """
    Descaracteriza PII de um recurso FHIR Patient conforme perfil HL7 de anonimizacao.

    Aplica regras de de-identificacao:
      - Remove nomes, telecom e endereco detalhado
      - Generaliza birthDate para ano
      - Substitui identificadores por hash deterministico (longitudinal)
      - Adiciona meta.security com codigo HTEST
    """
    paciente_anonimizado = copy.deepcopy(paciente_fhir)

    if "name" in paciente_anonimizado:
        del paciente_anonimizado["name"]

    if "birthDate" in paciente_anonimizado:
        ano = str(paciente_anonimizado["birthDate"]).split("-")[0]
        paciente_anonimizado["birthDate"] = f"{ano}-01-01"

    if "telecom" in paciente_anonimizado:
        del paciente_anonimizado["telecom"]

    if "photo" in paciente_anonimizado:
        del paciente_anonimizado["photo"]

    if "contact" in paciente_anonimizado:
        del paciente_anonimizado["contact"]

    if "identifier" in paciente_anonimizado:
        id_original = str(paciente_anonimizado["identifier"][0].get("value", ""))
        salt = os.getenv("SECRET_SALT", "default-salt")
        hash_id = hashlib.sha256((id_original + salt).encode("utf-8")).hexdigest()
        paciente_anonimizado["identifier"] = [
            {
                "system": HEALTHTECH_PATIENT_SYSTEM,
                "value": hash_id,
                "use": "official",
            }
        ]
        paciente_anonimizado["id"] = hash_id[:16]

    if "address" in paciente_anonimizado:
        para_manter = []
        for addr in paciente_anonimizado["address"]:
            novo_addr = {"use": "home", "type": "physical"}
            if "city" in addr:
                novo_addr["city"] = addr["city"]
            if "state" in addr:
                novo_addr["state"] = addr["state"]
            if "country" in addr:
                novo_addr["country"] = addr["country"]
            para_manter.append(novo_addr)
        paciente_anonimizado["address"] = para_manter

    meta = paciente_anonimizado.get("meta", {})
    profiles = meta.get("profile", [])
    if FHIR_DEID_PROFILE not in profiles:
        profiles.append(FHIR_DEID_PROFILE)
    meta["profile"] = profiles
    meta["security"] = [
        {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
            "code": "HTEST",
            "display": "test health data",
        }
    ]
    paciente_anonimizado["meta"] = meta

    return paciente_anonimizado