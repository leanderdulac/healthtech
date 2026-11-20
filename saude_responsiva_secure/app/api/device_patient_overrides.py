"""Admin: criar/consultar/remover vínculo canônico device→paciente."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.security.auth import mask_api_key, require_scope
from src.ops.device_patient_overrides import (
    delete_override,
    get_override,
    list_overrides,
    normalize_device_id,
    upsert_override,
)

router = APIRouter(prefix="/api/v1/admin/device-patient-overrides", tags=["admin"])


class OverrideIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    patient_id: str = Field(..., min_length=3, max_length=64)
    motivo: Optional[str] = Field(default=None, max_length=500)


@router.get("")
def list_device_patient_overrides(
    _api_key: str = Depends(require_scope("admin")),
):
    return {"ok": True, "overrides": list_overrides()}


@router.get("/{device_id}")
def get_device_patient_override(
    device_id: str,
    _api_key: str = Depends(require_scope("admin")),
):
    row = get_override(device_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum vínculo canônico para este aparelho.",
        )
    return {"ok": True, "override": row}


@router.put("")
@router.post("")
def upsert_device_patient_override(
    body: OverrideIn,
    api_key: str = Depends(require_scope("admin")),
):
    try:
        row = upsert_override(
            device_id=body.device_id,
            patient_id=body.patient_id,
            created_by=mask_api_key(api_key),
            motivo=body.motivo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return {"ok": True, "override": row}


@router.delete("/{device_id}")
def delete_device_patient_override(
    device_id: str,
    _api_key: str = Depends(require_scope("admin")),
):
    key = normalize_device_id(device_id)
    try:
        removed = delete_override(key)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum vínculo canônico para este aparelho.",
        )
    return {"ok": True, "deleted": True, "device_id": key}
