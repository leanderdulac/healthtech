"""Chaves de idempotência / deduplicação para ingestão de wearables.

Precedência da chave de uma leitura:
1. ``client_reading_id`` no body (recomendado — UUID estável da outbox/Room)
2. header ``Idempotency-Key`` (ingest unitário; no batch vale como cache da request)
3. chave natural: patient_id + device_id + timestamp do client + tipo de métrica

Sem identificador de client e sem timestamp enviado pelo client, a leitura
não é deduplicada (o servidor gera o instante de recepção, que não é estável
entre retries).
"""

from __future__ import annotations

import re
from typing import AbstractSet, List, Optional

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

METRIC_FIELDS = (
    "heart_rate",
    "hrv_rmssd",
    "skin_temp",
    "spo2",
    "activity_level",
    "ppg_signal",
    "blood_pressure_sys",
    "blood_pressure_dia",
    "glucose_mgdl",
    "body_temp_c",
)


def normalize_client_id(value: Optional[str]) -> Optional[str]:
    """Normaliza um id de client / Idempotency-Key. None se vazio ou inválido."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not CLIENT_ID_PATTERN.fullmatch(text):
        return None
    return text


def metric_signature(
    fields_set: AbstractSet[str],
    metric_type: Optional[str] = None,
) -> str:
    """Tipo de métrica declarado ou derivado dos campos enviados pelo client."""
    declared = (metric_type or "").strip()
    if declared:
        return declared.lower()
    metrics = [name for name in METRIC_FIELDS if name in fields_set]
    return "+".join(metrics) if metrics else "heart_rate"


def canonical_timestamp(device_ts: Optional[str]) -> Optional[str]:
    """UTC canônico do timestamp *enviado pelo client*. None se ausente/inválido."""
    if device_ts is None or str(device_ts).strip() == "":
        return None
    try:
        from src.ops.timestamps import parse_timestamp, utc_iso
    except Exception:
        return str(device_ts).strip()
    parsed = parse_timestamp(device_ts)
    if parsed is None:
        return None
    return utc_iso(parsed)


def resolve_dedup_keys(
    *,
    patient_id: str,
    device_id: Optional[str],
    client_reading_id: Optional[str],
    idempotency_key: Optional[str],
    client_timestamp: Optional[str],
    fields_set: AbstractSet[str],
    metric_type: Optional[str] = None,
) -> List[str]:
    """Todas as chaves aplicáveis (client id, header, natural).

    Indexar todas evita que um retry com um identificador diferente
    (ex.: passou a enviar ``client_reading_id``) crie um segundo registro.
    """
    keys: List[str] = []
    cid = normalize_client_id(client_reading_id)
    if cid:
        keys.append(f"cid:{patient_id}:{cid}")
    hid = normalize_client_id(idempotency_key)
    if hid:
        keys.append(f"hdr:{patient_id}:{hid}")
    ts = canonical_timestamp(client_timestamp)
    if ts:
        device = (device_id or "wrist_wearable").strip() or "wrist_wearable"
        sig = metric_signature(fields_set, metric_type)
        keys.append(f"nat:{patient_id}:{device}:{ts}:{sig}")
    seen = set()
    unique: List[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def resolve_dedup_key(
    *,
    patient_id: str,
    device_id: Optional[str],
    client_reading_id: Optional[str],
    idempotency_key: Optional[str],
    client_timestamp: Optional[str],
    fields_set: AbstractSet[str],
    metric_type: Optional[str] = None,
) -> Optional[str]:
    """Chave primária (precedência client id → header → natural), ou None."""
    keys = resolve_dedup_keys(
        patient_id=patient_id,
        device_id=device_id,
        client_reading_id=client_reading_id,
        idempotency_key=idempotency_key,
        client_timestamp=client_timestamp,
        fields_set=fields_set,
        metric_type=metric_type,
    )
    return keys[0] if keys else None


def request_cache_key(
    *,
    path: str,
    patient_id: str,
    idempotency_key: Optional[str],
) -> Optional[str]:
    """Chave de cache da request HTTP (header Idempotency-Key)."""
    hid = normalize_client_id(idempotency_key)
    if not hid:
        return None
    return f"req:{path}:{patient_id}:{hid}"
