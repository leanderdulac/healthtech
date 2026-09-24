"""Chaves de idempotência / deduplicação para ingestão de wearables.

Precedência:
1. ``client_reading_id`` no body
2. header ``Idempotency-Key`` (ingest unitário)
3. chave natural estruturada: patient_id + device_id + timestamp UTC + métrica

A chave natural **não** é serializada com ``:`` (ISO-8601 e MACs têm dois-pontos).
Colunas estruturadas no Postgres são a fonte da verdade.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import AbstractSet, List, Optional, Tuple

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

MemoryKey = Tuple[str, ...]


@dataclass(frozen=True)
class NaturalKey:
    patient_id: str
    device_id: str
    measured_at: str
    metric_type: str


@dataclass(frozen=True)
class DedupIdentity:
    """Identidade de dedup sem encoding frágil por split(':')."""

    patient_id: str
    client_reading_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    natural: Optional[NaturalKey] = None

    def has_any(self) -> bool:
        return bool(self.client_reading_id or self.idempotency_key or self.natural)

    def memory_keys(self) -> List[MemoryKey]:
        """Tuplas opacas para o índice em memória. Nunca faça split por ':'."""
        keys: List[MemoryKey] = []
        if self.client_reading_id:
            keys.append(("cid", self.patient_id, self.client_reading_id))
        if self.idempotency_key:
            keys.append(("hdr", self.patient_id, self.idempotency_key))
        if self.natural:
            nat = self.natural
            keys.append(
                ("nat", nat.patient_id, nat.device_id, nat.measured_at, nat.metric_type)
            )
        return keys


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


def resolve_dedup_identity(
    *,
    patient_id: str,
    device_id: Optional[str],
    client_reading_id: Optional[str],
    idempotency_key: Optional[str],
    client_timestamp: Optional[str],
    fields_set: AbstractSet[str],
    metric_type: Optional[str] = None,
) -> DedupIdentity:
    """Identidade estruturada (colunas). Não serializa timestamp com ':'."""
    cid = normalize_client_id(client_reading_id)
    hid = normalize_client_id(idempotency_key)
    natural: Optional[NaturalKey] = None
    ts = canonical_timestamp(client_timestamp)
    if ts:
        device = (device_id or "wrist_wearable").strip() or "wrist_wearable"
        natural = NaturalKey(
            patient_id=patient_id,
            device_id=device,
            measured_at=ts,
            metric_type=metric_signature(fields_set, metric_type),
        )
    return DedupIdentity(
        patient_id=patient_id,
        client_reading_id=cid,
        idempotency_key=hid,
        natural=natural,
    )


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
    """Rótulos estáveis para testes/log. Não parsear com split(':')."""
    ident = resolve_dedup_identity(
        patient_id=patient_id,
        device_id=device_id,
        client_reading_id=client_reading_id,
        idempotency_key=idempotency_key,
        client_timestamp=client_timestamp,
        fields_set=fields_set,
        metric_type=metric_type,
    )
    labels: List[str] = []
    if ident.client_reading_id:
        labels.append(f"cid:{ident.patient_id}:{ident.client_reading_id}")
    if ident.idempotency_key:
        labels.append(f"hdr:{ident.patient_id}:{ident.idempotency_key}")
    if ident.natural:
        nat = ident.natural
        labels.append(
            f"nat|{nat.patient_id}|{nat.device_id}|{nat.measured_at}|{nat.metric_type}"
        )
    return labels


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
    """Primeiro rótulo (precedência client id → header → natural), ou None."""
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
    return f"req|{path}|{patient_id}|{hid}"
