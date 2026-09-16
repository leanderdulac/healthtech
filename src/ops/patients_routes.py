"""GET /api/v1/patients — cadastro operacional (PostgreSQL).

Listagem autorizada aplica allow-list e/ou território no acesso a dados
**antes** de LIMIT/OFFSET. Sem restrição, a chave não-admin não recebe
páginas globais (fail-closed).
"""

from __future__ import annotations

import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ops.operational_patients import (
    InvalidTerritoryScope,
    OperationalDbUnavailable,
    get_patient,
    list_patients,
    parse_allowed_patient_ids,
    parse_territory_scopes,
)

try:
    from app.security.auth import get_key_scopes, require_patient_access, require_scope
except ImportError:
    from src.security.auth import get_key_scopes, require_patient_access, require_scope

router = APIRouter(prefix="/api/v1", tags=["patients"])


def _unavailable(exc: OperationalDbUnavailable) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "Cadastro operacional indisponível. "
            "Configure DATABASE_URL no FastAPI (PostgreSQL operacional). "
            f"({exc})"
        ),
    )


def _list_payload(patients, total: int, limit: int, offset: int) -> dict:
    return {
        "items": patients,
        "patients": patients,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/patients")
def get_patients(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
    territory: List[str] = Query(
        default=[],
        description=(
            "Escopo territorial repetível: `municipality_id` (municipal) ou "
            "`municipality_id:ubs_id` (UBS). União sem duplicar Patient."
        ),
    ),
    municipality_id: List[str] = Query(
        default=[],
        description="Atalho de escopo municipal (ou UBS se pareado com ubs_id).",
    ),
    ubs_id: List[str] = Query(
        default=[],
        description="Pareado por índice com municipality_id (ubs_id ≡ health_unit_id).",
    ),
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Lista o cadastro operacional. Não lê BigQuery nem gera alerta."""
    scopes = get_key_scopes(_api_key)
    is_admin = "admin" in scopes
    try:
        territories = parse_territory_scopes(
            territory=territory,
            municipality_id=municipality_id,
            ubs_id=ubs_id,
        )
    except InvalidTerritoryScope as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    allowed_ids, _wildcard = parse_allowed_patient_ids(
        os.getenv("ALLOWED_PATIENT_IDS", "")
    )
    if is_admin:
        allowed_ids = None
        if not territories:
            try:
                patients, total = list_patients(limit=limit, offset=offset)
            except OperationalDbUnavailable as exc:
                raise _unavailable(exc) from exc
            return _list_payload(patients, total, limit, offset)

    try:
        patients, total = list_patients(
            limit=limit,
            offset=offset,
            allowed_patient_ids=allowed_ids,
            territories=territories,
            require_defined_territory=True,
            fail_closed_without_constraint=True,
        )
    except OperationalDbUnavailable as exc:
        raise _unavailable(exc) from exc
    return _list_payload(patients, total, limit, offset)


@router.get("/patients/{patient_id}")
def get_patient_by_id(
    patient_id: str,
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """Um paciente do cadastro operacional, correlacionado por patient_id."""
    try:
        patient = get_patient(patient_id)
    except OperationalDbUnavailable as exc:
        raise _unavailable(exc) from exc
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail=f"Paciente operacional '{patient_id}' não encontrado.",
        )
    return patient
