"""Revisão humana do piloto (regras, sem o classificador)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.security.auth import require_scope
from app.services.pilot_review import MARKS, mark_event, summary

router = APIRouter(prefix="/api/v1/pilot", tags=["pilot"])


class PilotMarkRequest(BaseModel):
    event_id: str = Field(..., min_length=8, max_length=64)
    mark: str = Field(..., min_length=4, max_length=32)


@router.get("/summary")
def pilot_summary(
    request: Request,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Alarmes falsos por 24 h. Só conta sessão ble_hband já marcada."""
    _ = request
    return summary()


@router.post("/review")
def pilot_review(
    body: PilotMarkRequest,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """Marca um evento: correct, false_alarm ou missed."""
    _ = request
    if body.mark not in MARKS:
        raise HTTPException(
            status_code=422,
            detail="marca inválida. Use correct, false_alarm ou missed.",
        )
    if not mark_event(body.event_id, body.mark):
        raise HTTPException(status_code=404, detail="evento de piloto não encontrado.")
    return {"status": "ok", "event_id": body.event_id, "mark": body.mark}
