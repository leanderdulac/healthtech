"""Vínculo canônico device→paciente.

O patient_id enviado pelo app pode estar errado (perfil antigo no celular).
Quando existe um override para o device_id, ele prevalece na ingestão e
na apresentação da frota/detalhe. O valor recebido fica em reported_patient_id.

Não registra sinais vitais. created_by nunca guarda a chave de API completa.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_PATIENT_RE = re.compile(r"^[A-Za-z0-9\-_]{3,64}$")

_memory: Dict[str, Dict[str, Any]] = {}
_memory_lock = threading.Lock()

# Evita import circular com durable_readings no carregamento do módulo.


def normalize_device_id(device_id: Optional[str]) -> str:
    raw = str(device_id or "").strip()
    if _MAC_RE.fullmatch(raw):
        return raw.upper()
    return raw


def normalize_patient_id(patient_id: Optional[str]) -> str:
    return str(patient_id or "").strip()


def validate_patient_id(patient_id: str) -> Optional[str]:
    pid = normalize_patient_id(patient_id)
    if not pid or not _PATIENT_RE.fullmatch(pid):
        return None
    return pid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _public_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "device_id": row.get("device_id"),
        "patient_id": row.get("patient_id"),
        "created_by": row.get("created_by"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "motivo": row.get("motivo"),
    }


def clear_memory() -> None:
    """Só para testes: esvazia o fallback em memória."""
    with _memory_lock:
        _memory.clear()


def _engine():
    try:
        from app.services.durable_readings import get_engine

        return get_engine()
    except Exception:
        try:
            from src.ops.operational_patients import get_engine as ops_engine

            return ops_engine()
        except Exception:
            return None


def _use_durable() -> bool:
    engine = _engine()
    if engine is None:
        return False
    try:
        from app.services.durable_readings import apply_schema

        apply_schema(engine)
        return True
    except Exception as exc:
        logger.warning("Overrides: store durável indisponível, usando memória (%s)", exc)
        return False


def get_override(device_id: Optional[str]) -> Optional[Dict[str, Any]]:
    key = normalize_device_id(device_id)
    if not key:
        return None
    if _use_durable():
        try:
            engine = _engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT device_id, patient_id, created_by, created_at, "
                        "updated_at, motivo FROM device_patient_overrides "
                        "WHERE device_id = :device_id"
                    ),
                    {"device_id": key},
                ).fetchone()
            if row is None:
                return None
            mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            return _public_row(mapping)
        except SQLAlchemyError as exc:
            logger.warning("Overrides: falha ao ler store durável (%s)", exc)
            return None
    with _memory_lock:
        row = _memory.get(key)
        return dict(row) if row else None


def list_overrides() -> List[Dict[str, Any]]:
    if _use_durable():
        try:
            engine = _engine()
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT device_id, patient_id, created_by, created_at, "
                        "updated_at, motivo FROM device_patient_overrides "
                        "ORDER BY updated_at DESC"
                    )
                ).fetchall()
            out = []
            for row in rows:
                mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
                out.append(_public_row(mapping))
            return out
        except SQLAlchemyError as exc:
            logger.warning("Overrides: falha ao listar store durável (%s)", exc)
            return []
    with _memory_lock:
        return [dict(v) for v in _memory.values()]


def upsert_override(
    *,
    device_id: str,
    patient_id: str,
    created_by: str,
    motivo: Optional[str] = None,
) -> Dict[str, Any]:
    key = normalize_device_id(device_id)
    pid = validate_patient_id(patient_id)
    if not key:
        raise ValueError("device_id é obrigatório.")
    if not pid:
        raise ValueError(
            "patient_id inválido. Use 3–64 caracteres [A-Za-z0-9_-] "
            "(ex.: PAT-TESTE-0001)."
        )
    actor = (created_by or "").strip() or "admin"
    # Nunca persista uma chave de API completa.
    if len(actor) > 80:
        actor = actor[:20] + "***"
    note = (motivo or "").strip() or None
    if note and len(note) > 500:
        note = note[:500]
    now = _now()
    row = {
        "device_id": key,
        "patient_id": pid,
        "created_by": actor,
        "created_at": now,
        "updated_at": now,
        "motivo": note,
    }
    if _use_durable():
        engine = _engine()
        sql = """
            INSERT INTO device_patient_overrides (
                device_id, patient_id, created_by, created_at, updated_at, motivo
            ) VALUES (
                :device_id, :patient_id, :created_by, :created_at, :updated_at, :motivo
            )
            ON CONFLICT (device_id) DO UPDATE SET
                patient_id = EXCLUDED.patient_id,
                created_by = EXCLUDED.created_by,
                updated_at = EXCLUDED.updated_at,
                motivo = EXCLUDED.motivo
            RETURNING device_id, patient_id, created_by, created_at, updated_at, motivo
        """
        try:
            with engine.begin() as conn:
                fetched = conn.execute(text(sql), row).fetchone()
            mapping = (
                dict(fetched._mapping)
                if fetched is not None and hasattr(fetched, "_mapping")
                else row
            )
            return _public_row(mapping)
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Não foi possível gravar o vínculo: {exc}") from exc
    with _memory_lock:
        previous = _memory.get(key)
        if previous and previous.get("created_at"):
            row["created_at"] = previous["created_at"]
        _memory[key] = dict(row)
        return _public_row(_memory[key])


def delete_override(device_id: str) -> bool:
    key = normalize_device_id(device_id)
    if not key:
        return False
    if _use_durable():
        engine = _engine()
        try:
            with engine.begin() as conn:
                result = conn.execute(
                    text(
                        "DELETE FROM device_patient_overrides WHERE device_id = :device_id"
                    ),
                    {"device_id": key},
                )
            return int(result.rowcount or 0) > 0
        except SQLAlchemyError as exc:
            raise RuntimeError(f"Não foi possível remover o vínculo: {exc}") from exc
    with _memory_lock:
        return _memory.pop(key, None) is not None


def resolve_for_ingest(
    device_id: Optional[str], reported_patient_id: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Devolve (patient_id a gravar, reported_patient_id se houve override).

    Sem override, retorna (reported, None) — comportamento atual.
    """
    reported = normalize_patient_id(reported_patient_id)
    override = get_override(device_id)
    if not override:
        return reported, None
    canonical = normalize_patient_id(override.get("patient_id"))
    if not canonical or canonical == reported:
        # Vínculo aponta para o mesmo id: não há "recebido diferente".
        return (canonical or reported), None
    return canonical, reported or None


def apply_to_row(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Cópia da linha da frota/detalhe com patient_id canônico, se houver vínculo."""
    if not row:
        return {}
    out = dict(row)
    device_id = out.get("device_id")
    reported = out.get("reported_patient_id") or out.get("patient_id")
    canonical, stored_reported = resolve_for_ingest(device_id, reported)
    if stored_reported:
        out["patient_id"] = canonical
        out["reported_patient_id"] = stored_reported
        latest = out.get("latest")
        if isinstance(latest, dict):
            patched = dict(latest)
            patched["patient_id"] = canonical
            patched["reported_patient_id"] = stored_reported
            out["latest"] = patched
    return out
