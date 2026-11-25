"""Backfill idempotente da criptografia R8.

Não é chamado no boot da API. O CLI ``scripts/backfill_field_encryption.py``
recusa rodar sem ``BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes``.

Cada função percorre as linhas e só grava o que ainda está em claro
(ou, no modo decrypt, o que ainda está cifrado). A segunda execução
não reescreve ciphertext — o nonce não muda à toa.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.security.field_crypto import (
    FieldCryptoError,
    blind_index,
    is_ciphertext,
    is_enabled,
    open_json_value,
    open_text,
    protect,
    seal_json,
)

_ENROLLMENT_FIELDS = (
    ("display_name", "enrollment.display_name"),
    ("phone", "enrollment.phone"),
    ("caregiver_phone", "enrollment.caregiver_phone"),
    ("diseases", "enrollment.diseases"),
)


def _require_enabled() -> None:
    if not is_enabled():
        raise FieldCryptoError(
            "backfill exige FIELD_ENCRYPTION_KEY (e FIELD_BLIND_INDEX_KEY em produção)"
        )


def _dialect(engine: Engine) -> str:
    return (engine.dialect.name or "").lower()


def _json_expr(dialect: str, name: str) -> str:
    if dialect == "postgresql":
        return f"CAST(:{name} AS jsonb)"
    return f":{name}"


def _as_dict(value: Any, *, aad: str) -> Dict[str, Any]:
    opened = open_json_value(value, aad=aad)
    if isinstance(opened, dict):
        return opened
    if isinstance(opened, str):
        try:
            parsed = json.loads(opened)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_sealed(value: Any) -> bool:
    if isinstance(value, dict):
        return set(value.keys()) == {"_enc"}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return False
        return isinstance(parsed, dict) and set(parsed.keys()) == {"_enc"}
    return False


def _table_exists(conn, dialect: str, name: str) -> bool:
    if dialect == "sqlite":
        row = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": name},
        ).fetchone()
        return row is not None
    row = conn.execute(text("SELECT to_regclass(:name)"), {"name": name}).fetchone()
    return bool(row and row[0])


def _has_column(conn, dialect: str, table: str, column: str) -> bool:
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).fetchone()
    return row is not None


def backfill_wearable_readings(
    engine: Engine, *, decrypt: bool = False, dry_run: bool = False
) -> Dict[str, int]:
    """Cifra (ou restaura) ``wearable_readings`` nas colunas que já existem.

    Identificadores de busca viram índice cego ``bi1.``. O valor reversível
    fica dentro de ``frame`` / ``extra``. ``value`` numérico vai a NULL
    enquanto o frame estiver cifrado (o número continua no frame).
    """
    _require_enabled()
    dialect = _dialect(engine)
    stats = {"scanned": 0, "updated": 0, "skipped": 0}
    extra_sql = _json_expr(dialect, "extra")
    frame_sql = _json_expr(dialect, "frame")
    update_sql = f"""
        UPDATE wearable_readings SET
            patient_id = :patient_id,
            device_id = :device_id,
            reported_patient_id = :reported_patient_id,
            natural_patient_id = CASE
                WHEN natural_measured_at IS NULL THEN NULL
                ELSE :patient_id
            END,
            natural_device_id = CASE
                WHEN natural_measured_at IS NULL THEN NULL
                ELSE :device_id
            END,
            value = :value,
            extra = {extra_sql},
            frame = {frame_sql}
        WHERE reading_id = :reading_id
    """
    select_sql = """
        SELECT reading_id, frame, extra
        FROM wearable_readings
        ORDER BY created_at ASC, reading_id ASC
    """
    try:
        with engine.begin() as conn:
            rows = conn.execute(text(select_sql)).fetchall()
            for row in rows:
                stats["scanned"] += 1
                mapping = dict(row._mapping)
                sealed = _is_sealed(mapping.get("frame")) and _is_sealed(mapping.get("extra"))
                if decrypt and not _is_sealed(mapping.get("frame")):
                    stats["skipped"] += 1
                    continue
                frame = _as_dict(mapping.get("frame"), aad="wearable.frame")
                extra = _as_dict(mapping.get("extra"), aad="wearable.extra")
                pid = str(frame.get("patient_id") or "").strip()
                did = str(frame.get("device_id") or "").strip()
                if not pid or not did:
                    stats["skipped"] += 1
                    continue
                reported = frame.get("reported_patient_id")
                reported_text = str(reported).strip() if reported else ""
                if not decrypt and sealed and _row_ids_match(
                    conn, mapping["reading_id"], pid, did, reported_text
                ):
                    stats["skipped"] += 1
                    continue
                if decrypt:
                    params = _plaintext_params(frame, extra, pid, did, reported_text)
                else:
                    params = {
                        "patient_id": blind_index(pid, context="patient_id"),
                        "device_id": blind_index(did, context="device_id"),
                        "reported_patient_id": (
                            blind_index(reported_text, context="patient_id")
                            if reported_text
                            else None
                        ),
                        "value": None,
                        "extra": seal_json(extra, aad="wearable.extra"),
                        "frame": seal_json(frame, aad="wearable.frame"),
                    }
                params["reading_id"] = mapping["reading_id"]
                if not dry_run:
                    conn.execute(text(update_sql), params)
                stats["updated"] += 1
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever wearable_readings") from exc
    return stats


def _row_ids_match(
    conn,
    reading_id: str,
    patient_id: str,
    device_id: str,
    reported: str,
) -> bool:
    row = conn.execute(
        text(
            "SELECT patient_id, device_id, reported_patient_id, value "
            "FROM wearable_readings WHERE reading_id = :reading_id"
        ),
        {"reading_id": reading_id},
    ).fetchone()
    if row is None:
        return False
    mapping = dict(row._mapping)
    expected_reported = (
        blind_index(reported, context="patient_id") if reported else None
    )
    return (
        mapping.get("patient_id") == blind_index(patient_id, context="patient_id")
        and mapping.get("device_id") == blind_index(device_id, context="device_id")
        and (mapping.get("reported_patient_id") or None) == expected_reported
        and mapping.get("value") is None
    )


def _plaintext_params(
    frame: Dict[str, Any],
    extra: Dict[str, Any],
    patient_id: str,
    device_id: str,
    reported: str,
) -> Dict[str, Any]:
    from app.services.durable_readings import _value_and_unit

    metric = str(frame.get("metric_type") or "")
    value, _unit = _value_and_unit(frame, extra, metric)
    return {
        "patient_id": patient_id,
        "device_id": device_id,
        "reported_patient_id": reported or None,
        "value": value,
        "extra": json.dumps(extra, default=str),
        "frame": json.dumps(frame, default=str),
    }


def backfill_enrollments(
    engine: Engine, *, decrypt: bool = False, dry_run: bool = False
) -> Dict[str, Any]:
    """Cifra nome, telefones e doenças em ``enrollments``.

    ``patient_id`` permanece a chave operacional (WHERE da autorização).
    Sem a tabela, não faz nada.
    """
    _require_enabled()
    dialect = _dialect(engine)
    stats: Dict[str, Any] = {
        "table": True,
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
    }
    try:
        with engine.begin() as conn:
            if not _table_exists(conn, dialect, "enrollments"):
                stats["table"] = False
                return stats
            rows = conn.execute(
                text(
                    "SELECT patient_id, display_name, phone, caregiver_phone, diseases "
                    "FROM enrollments ORDER BY patient_id ASC"
                )
            ).fetchall()
            for row in rows:
                stats["scanned"] += 1
                mapping = dict(row._mapping)
                updates: Dict[str, Optional[str]] = {}
                changed = False
                for column, aad in _ENROLLMENT_FIELDS:
                    current = mapping.get(column)
                    if current is None:
                        updates[column] = None
                        continue
                    text_value = current if isinstance(current, str) else json.dumps(current, default=str)
                    if decrypt:
                        if not is_ciphertext(text_value):
                            updates[column] = text_value
                            continue
                        updates[column] = open_text(text_value, aad=aad)
                        changed = True
                        continue
                    if is_ciphertext(text_value):
                        updates[column] = text_value
                        continue
                    updates[column] = protect(text_value, aad=aad)
                    changed = True
                if not changed:
                    stats["skipped"] += 1
                    continue
                updates["patient_id"] = mapping["patient_id"]
                if not dry_run:
                    conn.execute(
                        text(
                            "UPDATE enrollments SET "
                            "display_name = :display_name, "
                            "phone = :phone, "
                            "caregiver_phone = :caregiver_phone, "
                            "diseases = :diseases "
                            "WHERE patient_id = :patient_id"
                        ),
                        updates,
                    )
                stats["updated"] += 1
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever enrollments") from exc
    return stats


def backfill_last_vitals(
    engine: Engine, *, decrypt: bool = False, dry_run: bool = False
) -> Dict[str, Any]:
    """Move SpO2/passos/pressão para colunas ``*_enc`` se a migração 005 existir.

    Sem as colunas, não altera a tabela (o script de schema é separado).
    """
    _require_enabled()
    dialect = _dialect(engine)
    stats: Dict[str, Any] = {"columns": True, "scanned": 0, "updated": 0, "skipped": 0}
    fields = (
        ("spo2", "spo2_enc", "vitals.spo2"),
        ("steps", "steps_enc", "vitals.steps"),
        ("blood_pressure_sys", "blood_pressure_sys_enc", "vitals.blood_pressure_sys"),
        ("blood_pressure_dia", "blood_pressure_dia_enc", "vitals.blood_pressure_dia"),
    )
    try:
        with engine.begin() as conn:
            if not _table_exists(conn, dialect, "wearable_device_last_vitals"):
                stats["columns"] = False
                return stats
            if not _has_column(conn, dialect, "wearable_device_last_vitals", "spo2_enc"):
                stats["columns"] = False
                return stats
            rows = conn.execute(
                text(
                    "SELECT device_id, spo2, steps, blood_pressure_sys, blood_pressure_dia, "
                    "spo2_enc, steps_enc, blood_pressure_sys_enc, blood_pressure_dia_enc "
                    "FROM wearable_device_last_vitals"
                )
            ).fetchall()
            for row in rows:
                stats["scanned"] += 1
                mapping = dict(row._mapping)
                params: Dict[str, Any] = {"device_id": mapping["device_id"]}
                changed = False
                for plain_col, enc_col, aad in fields:
                    plain = mapping.get(plain_col)
                    enc = mapping.get(enc_col)
                    if decrypt:
                        if enc and is_ciphertext(str(enc)):
                            opened = open_text(str(enc), aad=aad)
                            try:
                                params[plain_col] = float(opened)
                            except (TypeError, ValueError) as exc:
                                raise FieldCryptoError(
                                    "vital cifrado não é numérico"
                                ) from exc
                            params[enc_col] = None
                            changed = True
                        else:
                            params[plain_col] = plain
                            params[enc_col] = enc
                        continue
                    if plain is None and enc:
                        params[plain_col] = None
                        params[enc_col] = enc
                        continue
                    if plain is None:
                        params[plain_col] = None
                        params[enc_col] = enc
                        continue
                    params[plain_col] = None
                    params[enc_col] = protect(str(plain), aad=aad)
                    changed = True
                if not changed:
                    stats["skipped"] += 1
                    continue
                if not dry_run:
                    conn.execute(
                        text(
                            "UPDATE wearable_device_last_vitals SET "
                            "spo2 = :spo2, spo2_enc = :spo2_enc, "
                            "steps = :steps, steps_enc = :steps_enc, "
                            "blood_pressure_sys = :blood_pressure_sys, "
                            "blood_pressure_sys_enc = :blood_pressure_sys_enc, "
                            "blood_pressure_dia = :blood_pressure_dia, "
                            "blood_pressure_dia_enc = :blood_pressure_dia_enc "
                            "WHERE device_id = :device_id"
                        ),
                        params,
                    )
                stats["updated"] += 1
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever last vitals") from exc
    return stats
