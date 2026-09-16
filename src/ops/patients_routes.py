"""GET /api/v1/patients — cadastro operacional (PostgreSQL).

O frontend / ChatGPT consome só este HTTP. A senha do banco fica no servidor.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query

from src.ops.operational_patients import (
    OperationalDbUnavailable,
    get_patient,
    list_patients,
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


@router.get("/patients")
def get_patients(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Lista o cadastro operacional. Não lê BigQuery nem gera alerta."""
    try:
        patients, total = list_patients(limit=limit, offset=offset)
    except OperationalDbUnavailable as exc:
        raise _unavailable(exc) from exc
    scopes = get_key_scopes(_api_key)
    allowed_raw = os.getenv("ALLOWED_PATIENT_IDS", "").strip()
    if allowed_raw and "admin" not in scopes:
        allowed = {p.strip() for p in allowed_raw.split(",") if p.strip()}
        if not (allowed & {"*", "ALL", "all"}):
            patients = [p for p in patients if p.get("patient_id") in allowed]
            total = len(patients)
    return {
        "patients": patients,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
