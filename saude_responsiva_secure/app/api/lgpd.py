"""Endpoints de conformidade LGPD (purge / anonimização)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security.auth import require_scope
from app.services import telemetry_store

router = APIRouter(tags=["lgpd"])


@router.delete("/api/v1/patient/{patient_id}/anonymize")
def anonymize_patient(
    patient_id: str,
    request: Request,
    _api_key: str = Depends(require_scope("admin")),
):
    """LGPD: purga histórico em memória do paciente. Requer admin."""
    _ = request
    had = telemetry_store.anonymize_patient(patient_id)
    if not had:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado ativo registrado para o paciente '{patient_id}'.",
        )
    return {
        "status": "success",
        "message": (
            f"Dados do paciente '{patient_id}' purgados com sucesso "
            "para conformidade LGPD."
        ),
        "patient_id": patient_id,
    }
