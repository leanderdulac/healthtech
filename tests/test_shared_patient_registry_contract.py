"""DRAFT P1 shared-patient-registry contract — markdown ↔ OpenAPI alignment.

Docs only. Does not implement cadastro mutations. Fails if the contract
is silently marked CONFIRMED or if the review inconsistencies regress.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs/contracts/SHARED_PATIENT_REGISTRY_MUTATIONS_P1.md"
YAML_PATH = ROOT / "docs/contracts/shared-patient-registry-mutations-p1.yaml"
INDEX = ROOT / "docs/contracts/README.md"

CONFLICT_CODES = {
    "idempotency_key_reuse",
    "duplicate_fingerprint",
    "duplicate_patient_id",
    "already_merged",
    "merge_race",
    "territory_mismatch",
}


def _spec() -> dict:
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))


def test_contract_files_exist():
    assert MD.is_file()
    assert YAML_PATH.is_file()
    assert INDEX.is_file()


def test_status_remains_draft_not_confirmed():
    md = MD.read_text(encoding="utf-8")
    spec = _spec()
    assert "**Status:** **DRAFT**" in md
    assert "não** implementar como CONFIRMED" in md or "não implementar como CONFIRMED" in md
    assert spec["info"]["version"].endswith("-draft")
    assert "NOT CONFIRMED" in spec["info"]["description"]
    assert "0.2.0-draft" in INDEX.read_text(encoding="utf-8")
    # Promotion is a workshop step — this revision must not flip the index.
    index = INDEX.read_text(encoding="utf-8")
    assert "Não** CONFIRMED" in index or "**Não** CONFIRMED" in index


def test_patient_get_is_additive_p0_compatible():
    spec = _spec()
    patient = spec["components"]["schemas"]["Patient"]
    assert patient["required"] == ["patient_id", "updated_at"]
    assert "registry_version" not in patient["required"]
    for field in (
        "display_name",
        "phone",
        "caregiver_phone",
        "programs",
        "diseases",
        "isolation_social",
        "is_demo",
        "municipality_id",
        "ubs_id",
        "created_at",
        "updated_at",
    ):
        assert field in patient["properties"]
    list_schema = spec["components"]["schemas"]["PatientListResponse"]
    assert set(list_schema["required"]) >= {"items", "patients", "total", "limit", "offset"}


def test_links_do_not_own_programs():
    spec = _spec()
    links = spec["components"]["schemas"]["PatientLinks"]
    assert "program_enrollments" not in links.get("properties", {})
    assert links.get("additionalProperties") is False
    md = MD.read_text(encoding="utf-8")
    assert "program_enrollments` **não existe**" in md or "program_enrollments" in md


def test_create_includes_clinical_flags_and_patch_has_sex_enum():
    spec = _spec()
    create = spec["components"]["schemas"]["PatientCreateRequest"]
    patch = spec["components"]["schemas"]["PatientPatchRequest"]
    assert "clinical_flags" in create["properties"]
    assert patch["properties"]["sex"]["enum"] == ["female", "male", "other", "unknown"]
    assert create.get("additionalProperties") is False
    assert patch.get("additionalProperties") is False


def test_idempotency_replay_is_not_a_conflict():
    spec = _spec()
    codes = set(
        spec["components"]["schemas"]["ConflictError"]["allOf"][1]["properties"]["conflict_code"][
            "enum"
        ]
    )
    assert codes == CONFLICT_CODES
    assert "idempotency_replay" not in codes
    create_409 = spec["paths"]["/api/v1/patients"]["post"]["responses"]["409"]["description"]
    assert "idempotency_key_reuse" in create_409
    assert "Idempotent-Replayed" in spec["paths"]["/api/v1/patients"]["post"]["responses"]["201"]["headers"]


def test_search_and_dedup_reuse_p0_territory_params():
    spec = _spec()
    for path in ("/api/v1/patients/search", "/api/v1/patients/dedup/candidates"):
        names = {p.get("$ref", "").split("/")[-1] for p in spec["paths"][path]["post"]["parameters"]}
        assert {"Territory", "MunicipalityId", "UbsId"} <= names


def test_merge_requires_idempotency_and_if_match():
    spec = _spec()
    params = spec["paths"]["/api/v1/patients/{patient_id}/merge"]["post"]["parameters"]
    refs = {p["$ref"].split("/")[-1] for p in params}
    assert "IdempotencyKey" in refs
    assert "IfMatch" in refs
    merge_req = spec["components"]["schemas"]["MergeRequest"]["properties"]
    assert "duplicate_registry_version" in merge_req
    assert spec["paths"]["/api/v1/patients/{patient_id}"]["get"]["responses"]["410"]["$ref"].endswith(
        "GoneMerged"
    )


def test_consents_are_upsert_by_purpose_not_wipe():
    spec = _spec()
    put = spec["paths"]["/api/v1/patients/{patient_id}/consents"]["put"]
    assert put["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ConsentWriteRequest"
    )
    assert "upsert" in put["description"].lower()
    assert "wipe" in put["description"].lower()
    write = spec["components"]["schemas"]["ConsentWriteRequest"]
    assert write.get("additionalProperties") is False
    assert "registry_version" in spec["components"]["schemas"]["ConsentList"]["required"]


def test_attachments_do_not_claim_version_bump():
    spec = _spec()
    post = spec["paths"]["/api/v1/patients/{patient_id}/attachments"]["post"]
    assert "NOT increment" in post["description"]
    md = MD.read_text(encoding="utf-8")
    assert "não** incrementa `registry_version`" in md or "não incrementa `registry_version`" in md


def test_markdown_and_yaml_share_review_tokens():
    md = MD.read_text(encoding="utf-8")
    yml = YAML_PATH.read_text(encoding="utf-8")
    for token in CONFLICT_CODES | {
        "registry_version_mismatch",
        "Idempotent-Replayed",
        "patients:merge",
        "patients:consent",
        "authz-before-rank",
        "If-Match",
    }:
        assert token in md, token
        assert token in yml, token
