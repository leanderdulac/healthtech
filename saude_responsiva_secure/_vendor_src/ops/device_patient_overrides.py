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
    """device_id e patient_id em claro são a fonte do painel.

    Só abre ``*_enc`` quando a coluna operacional ainda está como ``bi1.``
    (linha gravada antes desta exceção). O painel não vê esse fallback.
    """
    device_id = row.get("device_id")
    patient_id = row.get("patient_id")
    if _is_blind_value(device_id) or _is_blind_value(patient_id):
        from app.security.field_crypto import is_ciphertext, open_text

        enc_device = row.get("device_id_enc")
        enc_patient = row.get("patient_id_enc")
        try:
            if _is_blind_value(device_id) and isinstance(enc_device, str) and is_ciphertext(enc_device):
                device_id = open_text(enc_device, aad="override.device_id")
            if (
                _is_blind_value(patient_id)
                and isinstance(enc_patient, str)
                and is_ciphertext(enc_patient)
            ):
                patient_id = open_text(enc_patient, aad="override.patient_id")
        except Exception:
            logger.warning("Overrides: vínculo cifrado não pôde ser aberto")
    return {
        "device_id": device_id,
        "patient_id": patient_id,
        "created_by": row.get("created_by"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "motivo": row.get("motivo"),
    }


def _is_blind_value(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    from app.security.field_crypto import is_blind_index

    return is_blind_index(value)


def _encryption_on() -> bool:
    from app.security.field_crypto import is_enabled

    return is_enabled()


def _override_columns(conn) -> str:
    base = "device_id, patient_id, created_by, created_at, updated_at, motivo"
    from app.services.durable_readings import table_has_column

    if table_has_column(conn, "device_patient_overrides", "device_id_enc"):
        return base + ", device_id_enc, patient_id_enc"
    return base


_OVERRIDE_SQL = """
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


def _upsert_operational(conn, row: Dict[str, Any]):
    """Grava device_id e patient_id em claro.

    O painel healthtech-responsive lê a tabela direto e faz o join pelo
    MAC. ``bi1.`` não seria aplicado. Se a linha antiga ainda está cega,
    o UPDATE devolve a PK ao MAC em claro e esvazia ``*_enc``.
    """
    has_enc = _override_columns(conn).endswith("patient_id_enc")
    stored_id = None
    if _encryption_on():
        from app.security.field_crypto import blind_index

        found = conn.execute(
            text(
                "SELECT device_id FROM device_patient_overrides "
                "WHERE device_id = :plain OR device_id = :blind"
            ),
            {
                "plain": row["device_id"],
                "blind": blind_index(row["device_id"], context="device_id"),
            },
        ).fetchone()
        if found is not None:
            stored_id = found[0]
    if stored_id and _is_blind_value(str(stored_id)):
        clear = ""
        returning = "device_id, patient_id, created_by, created_at, updated_at, motivo"
        if has_enc:
            clear = ", device_id_enc = NULL, patient_id_enc = NULL"
            returning += ", device_id_enc, patient_id_enc"
        sql = f"""
            UPDATE device_patient_overrides SET
                device_id = :device_id,
                patient_id = :patient_id,
                created_by = :created_by,
                updated_at = :updated_at,
                motivo = :motivo
                {clear}
            WHERE device_id = :stored_device_id
            RETURNING {returning}
        """
        payload = {**row, "stored_device_id": stored_id}
        return conn.execute(text(sql), payload).fetchone()
    if has_enc:
        sql = """
            INSERT INTO device_patient_overrides (
                device_id, patient_id, created_by, created_at, updated_at, motivo,
                device_id_enc, patient_id_enc
            ) VALUES (
                :device_id, :patient_id, :created_by, :created_at, :updated_at, :motivo,
                NULL, NULL
            )
            ON CONFLICT (device_id) DO UPDATE SET
                patient_id = EXCLUDED.patient_id,
                created_by = EXCLUDED.created_by,
                updated_at = EXCLUDED.updated_at,
                motivo = EXCLUDED.motivo,
                device_id_enc = NULL,
                patient_id_enc = NULL
            RETURNING device_id, patient_id, created_by, created_at, updated_at, motivo,
                      device_id_enc, patient_id_enc
        """
        return conn.execute(text(sql), row).fetchone()
    return conn.execute(text(_OVERRIDE_SQL), row).fetchone()


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
                columns = _override_columns(conn)
                if _encryption_on():
                    from app.security.field_crypto import blind_index

                    row = conn.execute(
                        text(
                            f"SELECT {columns} FROM device_patient_overrides "
                            "WHERE device_id = :plain OR device_id = :blind"
                        ),
                        {
                            "plain": key,
                            "blind": blind_index(key, context="device_id"),
                        },
                    ).fetchone()
                else:
                    row = conn.execute(
                        text(
                            f"SELECT {columns} FROM device_patient_overrides "
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
                columns = _override_columns(conn)
                rows = conn.execute(
                    text(
                        f"SELECT {columns} FROM device_patient_overrides "
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
        try:
            with engine.begin() as conn:
                fetched = _upsert_operational(conn, row)
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
                if _encryption_on():
                    from app.security.field_crypto import blind_index

                    result = conn.execute(
                        text(
                            "DELETE FROM device_patient_overrides "
                            "WHERE device_id = :plain OR device_id = :blind"
                        ),
                        {
                            "plain": key,
                            "blind": blind_index(key, context="device_id"),
                        },
                    )
                else:
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


def load_override_map() -> Dict[str, Dict[str, Any]]:
    """Todos os vínculos, numa consulta só. Chave: device_id normalizado."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in list_overrides():
        key = normalize_device_id(row.get("device_id"))
        if key:
            out[key] = row
    return out


def _resolve_with_override(
    reported_patient_id: Optional[str], override: Optional[Mapping[str, Any]]
) -> Tuple[str, Optional[str]]:
    reported = normalize_patient_id(reported_patient_id)
    if not override:
        return reported, None
    canonical = normalize_patient_id(override.get("patient_id"))
    if not canonical or canonical == reported:
        # Vínculo aponta para o mesmo id: não há "recebido diferente".
        return (canonical or reported), None
    return canonical, reported or None


def resolve_for_ingest(
    device_id: Optional[str], reported_patient_id: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Devolve (patient_id a gravar, reported_patient_id se houve override).

    Sem override, retorna (reported, None) — comportamento atual.
    Uma leitura (detalhe/ingest). A frota deve usar apply_to_rows.
    """
    return _resolve_with_override(reported_patient_id, get_override(device_id))


def apply_to_row(
    row: Optional[Mapping[str, Any]],
    overrides: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Cópia da linha da frota/detalhe com patient_id canônico, se houver vínculo.

    Se `overrides` for um mapa pré-carregado, não consulta o banco de novo.
    """
    if not row:
        return {}
    out = dict(row)
    device_id = out.get("device_id")
    reported = out.get("reported_patient_id") or out.get("patient_id")
    if overrides is None:
        override: Optional[Mapping[str, Any]] = get_override(device_id)
    else:
        override = overrides.get(normalize_device_id(device_id))
    canonical, stored_reported = _resolve_with_override(reported, override)
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


def apply_to_rows(rows: Optional[List[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Aplica os vínculos a uma lista com uma única leitura da tabela."""
    if not rows:
        return []
    try:
        overrides = load_override_map()
    except Exception:
        overrides = {}
    return [apply_to_row(row, overrides=overrides) for row in rows]
