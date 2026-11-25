"""Backfill idempotente da criptografia R8.

Não é chamado no boot da API. O CLI ``scripts/backfill_field_encryption.py``
recusa rodar sem ``BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes``.

Cada função percorre as linhas em lotes e só grava o que ainda está em
claro (ou, no modo decrypt, o que ainda está cifrado). Cada lote faz
commit. A segunda execução não reescreve ciphertext — o nonce não muda
à toa. Um lote que esbarra em deadlock (40P01) ou lock_timeout (55P03)
é tentado de novo, com backoff. O script pode ser interrompido e
retomado: a linha já cifrada é pulada.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.security.field_crypto import (
    FieldCryptoError,
    blind_index,
    is_blind_index,
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

DEFAULT_BATCH_SIZE = 500
DEFAULT_LOCK_TIMEOUT_MS = 3000
DEFAULT_STATEMENT_TIMEOUT_MS = 15000
_MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = 0.5
_RETRYABLE_SQLSTATES = frozenset({"40P01", "55P03"})

Sleeper = Callable[[float], None]
BatchObserver = Callable[[Dict[str, Any]], None]


def _require_enabled() -> None:
    if not is_enabled():
        raise FieldCryptoError(
            "backfill exige FIELD_ENCRYPTION_KEY (e FIELD_BLIND_INDEX_KEY em produção)"
        )


def _batch_size(value: int) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise FieldCryptoError("batch_size inválido") from exc
    if size < 1:
        raise FieldCryptoError("batch_size inválido")
    return size


def _dialect(engine: Engine) -> str:
    return (engine.dialect.name or "").lower()


def _json_expr(dialect: str, name: str) -> str:
    if dialect == "postgresql":
        return f"CAST(:{name} AS jsonb)"
    return f":{name}"


def _pgcode(exc: BaseException) -> str:
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    return str(code or "")


def timeout_statements(lock_timeout_ms: int, statement_timeout_ms: int) -> List[str]:
    """SET LOCAL só com inteiros. Vale dentro da transação do lote."""
    lock_ms = int(lock_timeout_ms)
    statement_ms = int(statement_timeout_ms)
    if lock_ms < 1 or statement_ms < 1:
        raise FieldCryptoError("timeout de lote inválido")
    return [
        f"SET LOCAL lock_timeout = '{lock_ms}ms'",
        f"SET LOCAL statement_timeout = '{statement_ms}ms'",
    ]


def commit_work(
    engine: Engine,
    dialect: str,
    work: Callable[[Any], None],
    *,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    attempts: int = _MAX_ATTEMPTS,
    sleeper: Sleeper = time.sleep,
) -> None:
    """Commit de um lote. 40P01 e 55P03 tentam de novo; o resto aborta."""
    delay = _BACKOFF_SECONDS
    last_code = ""
    for attempt in range(attempts):
        try:
            with engine.begin() as conn:
                if dialect == "postgresql":
                    for statement in timeout_statements(lock_timeout_ms, statement_timeout_ms):
                        conn.execute(text(statement))
                work(conn)
            return
        except FieldCryptoError:
            raise
        except SQLAlchemyError as exc:
            last_code = _pgcode(exc)
            if last_code not in _RETRYABLE_SQLSTATES or attempt == attempts - 1:
                label = last_code or "erro de banco"
                raise FieldCryptoError(f"lote interrompido ({label})") from exc
            sleeper(delay)
            delay = min(delay * 2, 8.0)
    raise FieldCryptoError(f"lote interrompido ({last_code or 'erro de banco'})")


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
            "WHERE table_schema = current_schema() "
            "AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).fetchone()
    return row is not None


def _fetch_page(engine: Engine, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [dict(row._mapping) for row in rows]


def _note_batch(stats: Dict[str, Any], on_batch: Optional[BatchObserver]) -> None:
    stats["batches"] = int(stats.get("batches") or 0) + 1
    if on_batch is not None:
        on_batch(dict(stats))


def backfill_wearable_readings(
    engine: Engine,
    *,
    decrypt: bool = False,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch: Optional[BatchObserver] = None,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    sleeper: Sleeper = time.sleep,
) -> Dict[str, int]:
    """Cifra (ou restaura) ``wearable_readings`` nas colunas que já existem.

    Identificadores de busca viram índice cego ``bi1.``. O valor reversível
    fica dentro de ``frame`` / ``extra``. ``value`` numérico vai a NULL
    enquanto o frame estiver cifrado (o número continua no frame).
    """
    _require_enabled()
    size = _batch_size(batch_size)
    dialect = _dialect(engine)
    stats: Dict[str, Any] = {"scanned": 0, "updated": 0, "skipped": 0, "batches": 0}
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
        SELECT reading_id, patient_id, device_id, reported_patient_id, value, frame, extra
        FROM wearable_readings
        WHERE reading_id > :after
        ORDER BY reading_id ASC
        LIMIT :limit
    """
    after = ""
    try:
        while True:
            page = _fetch_page(
                engine, select_sql, {"after": after, "limit": size}
            )
            if not page:
                break
            after = str(page[-1]["reading_id"])
            pending: List[Dict[str, Any]] = []
            for mapping in page:
                stats["scanned"] += 1
                params = _reading_update(mapping, decrypt=decrypt)
                if params is None:
                    stats["skipped"] += 1
                    continue
                pending.append(params)
            if not pending:
                continue
            stats["updated"] += len(pending)
            if dry_run:
                continue

            def work(conn, rows=pending):
                for params in rows:
                    conn.execute(text(update_sql), params)

            commit_work(
                engine,
                dialect,
                work,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                sleeper=sleeper,
            )
            _note_batch(stats, on_batch)
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever wearable_readings") from exc
    return {key: int(stats[key]) for key in ("scanned", "updated", "skipped", "batches")}


def _reading_update(mapping: Dict[str, Any], *, decrypt: bool) -> Optional[Dict[str, Any]]:
    sealed = _is_sealed(mapping.get("frame")) and _is_sealed(mapping.get("extra"))
    if decrypt and not _is_sealed(mapping.get("frame")):
        return None
    frame = _as_dict(mapping.get("frame"), aad="wearable.frame")
    extra = _as_dict(mapping.get("extra"), aad="wearable.extra")
    pid = str(frame.get("patient_id") or "").strip()
    did = str(frame.get("device_id") or "").strip()
    if not pid or not did:
        return None
    reported = frame.get("reported_patient_id")
    reported_text = str(reported).strip() if reported else ""
    if not decrypt and sealed and _row_ids_match(mapping, pid, did, reported_text):
        return None
    if decrypt:
        params = _plaintext_params(frame, extra, pid, did, reported_text)
    else:
        params = {
            "patient_id": blind_index(pid, context="patient_id"),
            "device_id": blind_index(did, context="device_id"),
            "reported_patient_id": (
                blind_index(reported_text, context="patient_id") if reported_text else None
            ),
            "value": None,
            "extra": seal_json(extra, aad="wearable.extra"),
            "frame": seal_json(frame, aad="wearable.frame"),
        }
    params["reading_id"] = mapping["reading_id"]
    return params


def _row_ids_match(
    mapping: Dict[str, Any],
    patient_id: str,
    device_id: str,
    reported: str,
) -> bool:
    expected_reported = blind_index(reported, context="patient_id") if reported else None
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
    engine: Engine,
    *,
    decrypt: bool = False,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch: Optional[BatchObserver] = None,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    sleeper: Sleeper = time.sleep,
) -> Dict[str, Any]:
    """Cifra nome, telefones e doenças em ``enrollments``.

    ``patient_id`` permanece a chave operacional (WHERE da autorização).
    Sem a tabela, não faz nada.
    """
    _require_enabled()
    size = _batch_size(batch_size)
    dialect = _dialect(engine)
    stats: Dict[str, Any] = {
        "table": True,
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "batches": 0,
    }
    select_sql = """
        SELECT patient_id, display_name, phone, caregiver_phone, diseases
        FROM enrollments
        WHERE patient_id > :after
        ORDER BY patient_id ASC
        LIMIT :limit
    """
    update_sql = """
        UPDATE enrollments SET
            display_name = :display_name,
            phone = :phone,
            caregiver_phone = :caregiver_phone,
            diseases = :diseases
        WHERE patient_id = :patient_id
    """
    after = ""
    try:
        with engine.connect() as conn:
            if not _table_exists(conn, dialect, "enrollments"):
                stats["table"] = False
                return stats
        while True:
            page = _fetch_page(engine, select_sql, {"after": after, "limit": size})
            if not page:
                break
            after = str(page[-1]["patient_id"])
            pending: List[Dict[str, Any]] = []
            for mapping in page:
                stats["scanned"] += 1
                updates = _enrollment_update(mapping, decrypt=decrypt)
                if updates is None:
                    stats["skipped"] += 1
                    continue
                pending.append(updates)
            if not pending:
                continue
            stats["updated"] += len(pending)
            if dry_run:
                continue

            def work(conn, rows=pending):
                for params in rows:
                    conn.execute(text(update_sql), params)

            commit_work(
                engine,
                dialect,
                work,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                sleeper=sleeper,
            )
            _note_batch(stats, on_batch)
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever enrollments") from exc
    return stats


def _enrollment_update(mapping: Dict[str, Any], *, decrypt: bool) -> Optional[Dict[str, Any]]:
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
        return None
    updates["patient_id"] = mapping["patient_id"]
    return updates


def backfill_last_vitals(
    engine: Engine,
    *,
    decrypt: bool = False,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch: Optional[BatchObserver] = None,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    sleeper: Sleeper = time.sleep,
) -> Dict[str, Any]:
    """Move SpO2/passos/pressão para colunas ``*_enc`` se a migração 005 existir.

    Sem as colunas, não altera a tabela (o script de schema é separado).
    """
    _require_enabled()
    size = _batch_size(batch_size)
    dialect = _dialect(engine)
    stats: Dict[str, Any] = {
        "columns": True,
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "batches": 0,
    }
    fields = (
        ("spo2", "spo2_enc", "vitals.spo2"),
        ("steps", "steps_enc", "vitals.steps"),
        ("blood_pressure_sys", "blood_pressure_sys_enc", "vitals.blood_pressure_sys"),
        ("blood_pressure_dia", "blood_pressure_dia_enc", "vitals.blood_pressure_dia"),
    )
    select_sql = """
        SELECT device_id, spo2, steps, blood_pressure_sys, blood_pressure_dia,
               spo2_enc, steps_enc, blood_pressure_sys_enc, blood_pressure_dia_enc
        FROM wearable_device_last_vitals
        WHERE device_id > :after
        ORDER BY device_id ASC
        LIMIT :limit
    """
    update_sql = """
        UPDATE wearable_device_last_vitals SET
            spo2 = :spo2, spo2_enc = :spo2_enc,
            steps = :steps, steps_enc = :steps_enc,
            blood_pressure_sys = :blood_pressure_sys,
            blood_pressure_sys_enc = :blood_pressure_sys_enc,
            blood_pressure_dia = :blood_pressure_dia,
            blood_pressure_dia_enc = :blood_pressure_dia_enc
        WHERE device_id = :device_id
    """
    after = ""
    try:
        with engine.connect() as conn:
            if not _table_exists(conn, dialect, "wearable_device_last_vitals"):
                stats["columns"] = False
                return stats
            if not _has_column(conn, dialect, "wearable_device_last_vitals", "spo2_enc"):
                stats["columns"] = False
                return stats
        while True:
            page = _fetch_page(engine, select_sql, {"after": after, "limit": size})
            if not page:
                break
            after = str(page[-1]["device_id"])
            pending: List[Dict[str, Any]] = []
            for mapping in page:
                stats["scanned"] += 1
                params = _vitals_update(mapping, fields=fields, decrypt=decrypt)
                if params is None:
                    stats["skipped"] += 1
                    continue
                pending.append(params)
            if not pending:
                continue
            stats["updated"] += len(pending)
            if dry_run:
                continue

            def work(conn, rows=pending):
                for params in rows:
                    conn.execute(text(update_sql), params)

            commit_work(
                engine,
                dialect,
                work,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                sleeper=sleeper,
            )
            _note_batch(stats, on_batch)
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever last vitals") from exc
    return stats


def _vitals_update(
    mapping: Dict[str, Any],
    *,
    fields: tuple,
    decrypt: bool,
) -> Optional[Dict[str, Any]]:
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
                    raise FieldCryptoError("vital cifrado não é numérico") from exc
                params[enc_col] = None
                changed = True
            else:
                params[plain_col] = plain
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
        return None
    return params


def backfill_overrides(
    engine: Engine,
    *,
    decrypt: bool = False,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch: Optional[BatchObserver] = None,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    sleeper: Sleeper = time.sleep,
) -> Dict[str, Any]:
    """Devolve ``device_patient_overrides`` ao claro.

    O painel lê essa tabela direto. ``device_id`` e ``patient_id`` ficam
    em claro de propósito. Linha já gravada como ``bi1.`` é reaberta a
    partir de ``device_id_enc`` / ``patient_id_enc`` e as colunas cifradas
    são esvaziadas. Sem as colunas da 005, não há o que reabrir.
    ``decrypt=True`` é o mesmo caminho: o estado desejado já é o claro.
    """
    _require_enabled()
    size = _batch_size(batch_size)
    dialect = _dialect(engine)
    stats: Dict[str, Any] = {
        "columns": True,
        "scanned": 0,
        "updated": 0,
        "skipped": 0,
        "conflicts": 0,
        "batches": 0,
    }
    if decrypt:
        stats["decrypt"] = True
    select_sql = """
        SELECT device_id, patient_id, device_id_enc, patient_id_enc
        FROM device_patient_overrides
        WHERE device_id > :after
        ORDER BY device_id ASC
        LIMIT :limit
    """
    update_sql = """
        UPDATE device_patient_overrides SET
            device_id = :plain_device,
            patient_id = :plain_patient,
            device_id_enc = NULL,
            patient_id_enc = NULL
        WHERE device_id = :stored_device_id
    """
    after = ""
    try:
        with engine.connect() as conn:
            if not _table_exists(conn, dialect, "device_patient_overrides"):
                stats["columns"] = False
                return stats
            if not _has_column(conn, dialect, "device_patient_overrides", "device_id_enc"):
                stats["columns"] = False
                return stats
        while True:
            page = _fetch_page(engine, select_sql, {"after": after, "limit": size})
            if not page:
                break
            after = str(page[-1]["device_id"])
            pending: List[Dict[str, Any]] = []
            for mapping in page:
                stats["scanned"] += 1
                params = _override_restore(mapping)
                if params is None:
                    stats["skipped"] += 1
                    continue
                pending.append(params)
            if not pending:
                continue
            if dry_run:
                stats["updated"] += len(pending)
                continue
            applied = {"updated": 0, "conflicts": 0}

            def work(conn, rows=pending):
                applied["updated"] = 0
                applied["conflicts"] = 0
                for params in rows:
                    clash = conn.execute(
                        text(
                            "SELECT 1 FROM device_patient_overrides "
                            "WHERE device_id = :plain_device "
                            "AND device_id <> :stored_device_id"
                        ),
                        params,
                    ).fetchone()
                    if clash is not None:
                        applied["conflicts"] += 1
                        continue
                    conn.execute(text(update_sql), params)
                    applied["updated"] += 1

            commit_work(
                engine,
                dialect,
                work,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
                sleeper=sleeper,
            )
            stats["updated"] += applied["updated"]
            stats["conflicts"] += applied["conflicts"]
            stats["skipped"] += applied["conflicts"]
            _note_batch(stats, on_batch)
    except FieldCryptoError:
        raise
    except SQLAlchemyError as exc:
        raise FieldCryptoError("falha ao reescrever device_patient_overrides") from exc
    return stats


def _override_restore(mapping: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    stored_device = mapping.get("device_id")
    stored_patient = mapping.get("patient_id")
    device_blind = isinstance(stored_device, str) and is_blind_index(stored_device)
    patient_blind = isinstance(stored_patient, str) and is_blind_index(stored_patient)
    if not device_blind and not patient_blind:
        return None
    plain_device = stored_device
    plain_patient = stored_patient
    if device_blind:
        enc = mapping.get("device_id_enc")
        if not isinstance(enc, str) or not is_ciphertext(enc):
            return None
        plain_device = open_text(enc, aad="override.device_id")
    if patient_blind:
        enc = mapping.get("patient_id_enc")
        if not isinstance(enc, str) or not is_ciphertext(enc):
            return None
        plain_patient = open_text(enc, aad="override.patient_id")
    if not plain_device or not plain_patient:
        return None
    return {
        "stored_device_id": stored_device,
        "plain_device": plain_device,
        "plain_patient": plain_patient,
    }
