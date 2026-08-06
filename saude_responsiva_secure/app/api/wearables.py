"""Ingestão e leitura de telemetria de wearables."""

from __future__ import annotations

import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import Settings, get_settings
from app.models.schemas import WearableBatchIngestRequest, WearableTelemetryRequest
from app.security.auth import require_patient_access, require_scope
from app.services import telemetry_store
from app.services.signal_core import process_ingest_frame

router = APIRouter(prefix="/api/v1/wearables", tags=["wearables"])


def _with_timestamp(payload: WearableTelemetryRequest) -> Dict[str, Any]:
    data = payload.model_dump()
    if not data.get("timestamp"):
        data["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return data


@router.post("/ingest")
def ingest_wearable_reading(
    payload: WearableTelemetryRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """
    Recebe telemetria de wearable (PPG / HR / SpO2).
    Requer escopo wearables:write.
    """
    _ = request  # disponível para auditoria / rate-limit middleware
    data = _with_timestamp(payload)
    frame = process_ingest_frame(data)
    telemetry_store.append_reading(payload.patient_id, frame)
    return frame


@router.post("/batch-ingest")
def batch_ingest_wearables(
    batch: WearableBatchIngestRequest,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """Ingestão em lote (sincronização periódica). Requer wearables:write."""
    _ = request
    results = []
    for reading in batch.readings:
        reading.patient_id = batch.patient_id
        data = _with_timestamp(reading)
        frame = process_ingest_frame(data)
        telemetry_store.append_reading(batch.patient_id, frame)
        results.append(frame)
    return {
        "status": "success",
        "patient_id": batch.patient_id,
        "processed_count": len(results),
        "latest_result": results[-1] if results else None,
    }


@router.get("/patient/{patient_id}/latest")
def get_latest_patient_telemetry(
    patient_id: str,
    request: Request,
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """Último estado fisiológico do paciente (anti-IDOR)."""
    _ = request
    latest = telemetry_store.get_latest(patient_id)
    if not latest:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado encontrado para o paciente '{patient_id}'.",
        )
    return latest


@router.get("/patient/{patient_id}/history")
def get_patient_telemetry_history(
    patient_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """Histórico recente do paciente (anti-IDOR)."""
    _ = request
    history = telemetry_store.get_history(patient_id, limit=limit)
    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum histórico encontrado para o paciente '{patient_id}'.",
        )
    return {
        "patient_id": patient_id,
        "total_records": len(history),
        "records": history,
    }
