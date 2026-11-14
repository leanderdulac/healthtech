"""GET /api/v1/ops/devices/{device_id} — detalhe autenticado (wearables:read)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.ops.device_detail import build_device_detail, lookup_device_row

try:
    from app.security.auth import check_patient_authorization, require_scope
except ImportError:
    from src.security.auth import check_patient_authorization, require_scope

router = APIRouter(prefix="/api/v1/ops", tags=["ops-dashboard"])


@router.get("/devices/{device_id}")
def get_ops_device_detail(
    device_id: str,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Detalhe de um relógio. Mesma authz de GET /wearables/devices e /patients/{id}.

    Região = IDs do cadastro, não localização. Sem municipality_name/UBS name.
    """
    wanted = (device_id or "").strip()
    if not wanted:
        raise HTTPException(status_code=404, detail="Relógio não encontrado.")

    row = lookup_device_row(wanted)
    if row is None:
        raise HTTPException(status_code=404, detail="Relógio não encontrado.")

    patient_id = str(row.get("patient_id") or "").strip()
    if patient_id and not check_patient_authorization(_api_key, patient_id):
        raise HTTPException(
            status_code=403,
            detail=(
                "Acesso proibido. A chave fornecida não tem autorização "
                f"para os dados do paciente '{patient_id}'."
            ),
        )
    return build_device_detail(row)
