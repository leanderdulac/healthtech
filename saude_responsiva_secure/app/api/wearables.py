"""Ingestão e leitura de telemetria de wearables."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.config import Settings, get_settings
from app.models.schemas import WearableBatchIngestRequest, WearableTelemetryRequest
from app.security.auth import require_patient_access, require_scope
from app.services import telemetry_store
from app.services.ingest_idempotency import (
    normalize_client_id,
    request_cache_key,
    resolve_dedup_keys,
)
from app.services.signal_core import process_ingest_frame

router = APIRouter(prefix="/api/v1/wearables", tags=["wearables"])

_INGEST_STATUSES = ("accepted", "duplicate", "rejected")


def _with_timestamp(payload: WearableTelemetryRequest) -> Dict[str, Any]:
    data = payload.model_dump()
    from src.ops.timestamps import stamp_ingest

    data.update(stamp_ingest(data.get("timestamp")))
    return data


def _require_valid_optional_id(value: Optional[str], name: str) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    normalized = normalize_client_id(value)
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail=f"{name} inválido. Use 1–128 caracteres [A-Za-z0-9._:-].",
        )
    return normalized


def _decorate_frame(frame: Dict[str, Any], status: str) -> Dict[str, Any]:
    out = dict(frame)
    out["ingest_status"] = status
    out["duplicate"] = status == "duplicate"
    return out


def _ingest_one(
    payload: WearableTelemetryRequest,
    *,
    patient_id: str,
    idempotency_key: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """Processa uma leitura. Retorna (frame, status, error)."""
    client_ts = payload.timestamp
    fields_set = set(payload.model_fields_set)
    dedup_keys = resolve_dedup_keys(
        patient_id=patient_id,
        device_id=payload.device_id,
        client_reading_id=payload.client_reading_id,
        idempotency_key=idempotency_key,
        client_timestamp=client_ts,
        fields_set=fields_set,
        metric_type=payload.metric_type,
    )
    existing = telemetry_store.find_duplicate(dedup_keys=dedup_keys)
    if existing is not None:
        return existing, "duplicate", None
    try:
        data = _with_timestamp(payload)
        data["patient_id"] = patient_id
        frame = process_ingest_frame(data)
        if payload.client_reading_id:
            frame["client_reading_id"] = payload.client_reading_id
        if payload.metric_type:
            frame["metric_type"] = payload.metric_type
        stored, status = telemetry_store.upsert_reading(
            patient_id, frame, dedup_keys=dedup_keys
        )
        return stored, status, None
    except Exception as exc:
        return None, "rejected", str(exc)


@router.post("/ingest")
def ingest_wearable_reading(
    payload: WearableTelemetryRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    _api_key: str = Depends(require_scope("wearables:write")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    Recebe telemetria de wearable (PPG / HR / SpO2).
    Requer escopo wearables:write.

    Reenvio da mesma leitura (mesmo ``client_reading_id``, ``Idempotency-Key``
    ou chave natural patient+device+timestamp+métrica) devolve 200 com
    ``ingest_status=duplicate`` e **não** cria outro registro.
    """
    _ = request  # disponível para auditoria / rate-limit middleware
    _ = settings
    header_key = _require_valid_optional_id(idempotency_key, "Idempotency-Key")
    cache_key = request_cache_key(
        path="/api/v1/wearables/ingest",
        patient_id=payload.patient_id,
        idempotency_key=header_key,
    )
    cached = telemetry_store.get_cached_response(cache_key)
    if cached is not None:
        return _decorate_frame(cached, "duplicate")

    frame, status, error = _ingest_one(
        payload,
        patient_id=payload.patient_id,
        idempotency_key=header_key,
    )
    if status == "rejected" or frame is None:
        raise HTTPException(
            status_code=500,
            detail=error or "Falha ao processar a leitura.",
        )
    decorated = _decorate_frame(frame, status)
    telemetry_store.put_cached_response(cache_key, decorated)
    return decorated


@router.post("/batch-ingest")
@router.post("/ingest/batch")
def batch_ingest_wearables(
    batch: WearableBatchIngestRequest,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:write")),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Ingestão em lote (sincronização periódica). Requer wearables:write.

    Duplicatas parciais são reportadas por item em ``results``
    (``accepted`` / ``duplicate`` / ``rejected``). Itens já armazenados
    contam como sucesso para o client marcar a outbox como synced.
    """
    _ = request
    header_key = _require_valid_optional_id(idempotency_key, "Idempotency-Key")
    cache_key = request_cache_key(
        path="/api/v1/wearables/batch-ingest",
        patient_id=batch.patient_id,
        idempotency_key=header_key,
    )
    cached = telemetry_store.get_cached_response(cache_key)
    if cached is not None:
        return cached

    results: List[Dict[str, Any]] = []
    frames: List[Dict[str, Any]] = []
    accepted = 0
    duplicates = 0
    rejected = 0
    for index, reading in enumerate(batch.readings):
        reading.patient_id = batch.patient_id
        frame, status, error = _ingest_one(
            reading,
            patient_id=batch.patient_id,
            idempotency_key=None,
        )
        item: Dict[str, Any] = {
            "index": index,
            "status": status if status in _INGEST_STATUSES else "rejected",
            "client_reading_id": reading.client_reading_id,
        }
        if status == "rejected" or frame is None:
            rejected += 1
            item["status"] = "rejected"
            item["error"] = error or "Falha ao processar a leitura."
        else:
            decorated = _decorate_frame(frame, status)
            item["result"] = decorated
            frames.append(decorated)
            if status == "duplicate":
                duplicates += 1
            else:
                accepted += 1
        results.append(item)

    payload = {
        "status": "success" if rejected == 0 else "partial",
        "patient_id": batch.patient_id,
        "processed_count": accepted + duplicates,
        "accepted_count": accepted,
        "duplicate_count": duplicates,
        "rejected_count": rejected,
        "latest_result": frames[-1] if frames else None,
        "results": results,
    }
    telemetry_store.put_cached_response(cache_key, payload)
    return payload


@router.get("/devices")
def list_wearable_devices(
    request: Request,
    q: str = Query(default=""),
    online: Optional[bool] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10000),
    include_latest: bool = Query(default=False),
    include_synthetic: bool = Query(
        default=False,
        description="Se true, inclui devices de smoke/probe/timecheck. Padrão: ocultos.",
    ),
    patient_id: Optional[str] = Query(
        default=None,
        description="Se informado, restringe a frota a esse Patient antes da paginação.",
    ),
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Frota de relógios (payload compacto). Requer wearables:read."""
    from app.security.auth import check_patient_authorization

    _ = request
    wanted = (patient_id or "").strip() or None
    if wanted and not check_patient_authorization(_api_key, wanted):
        raise HTTPException(
            status_code=403,
            detail=(
                "Acesso proibido. A chave fornecida não tem autorização "
                f"para os dados do paciente '{wanted}'."
            ),
        )
    return telemetry_store.list_devices(
        q=q,
        online=online,
        limit=limit,
        offset=offset,
        include_latest=include_latest,
        patient_id=wanted,
        include_synthetic=include_synthetic,
    )


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
