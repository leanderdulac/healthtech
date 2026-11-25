"""Persistência durável de leituras de wearable no PostgreSQL operacional.

Reusa o engine de ``src.ops.operational_patients`` (DATABASE_URL /
OPERATIONAL_DATABASE_URL, Cloud SQL ``healthtech-pg``). Sem URL, o
``telemetry_store`` cai para memória — este módulo não deve ser usado.

Se a URL está definida e o banco está inacessível, as operações
levantam ``DurableStoreUnavailable`` (ingest/leitura → 5xx).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.services.ingest_idempotency import DedupIdentity, NaturalKey, metric_signature

logger = logging.getLogger(__name__)

MIGRATION_NAME = "001_wearable_readings.sql"
# Aplicadas em ordem por apply_schema(). Só mudanças aditivas e idempotentes.
MIGRATION_NAMES = (
    "001_wearable_readings.sql",
    "002_wearable_device_label.sql",
    "003_wearable_device_last_vitals.sql",
    "004_device_patient_overrides.sql",
)


class DurableStoreUnavailable(RuntimeError):
    """DATABASE_URL configurada mas o Postgres está inacessível / schema ausente."""


_COLUMN_PROBE = {
    ("wearable_device_last_vitals", "spo2_enc"),
    ("device_patient_overrides", "device_id_enc"),
    ("device_patient_overrides", "patient_id_enc"),
}


def table_has_column(conn, table: str, column: str) -> bool:
    """True se a coluna aditiva da migração 005 já existe. Nomes são fixos."""
    if (table, column) not in _COLUMN_PROBE:
        raise ValueError("consulta de coluna não permitida")
    dialect = (getattr(getattr(conn, "dialect", None), "name", "") or "").lower()
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)
    found = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).fetchone()
    return found is not None


def _crypto():
    from app.security import field_crypto

    return field_crypto


def _stored_id(value: Optional[str], context: str) -> Optional[str]:
    """Identificador como está na coluna: claro, ou índice cego se a chave existe."""
    if value is None or value == "":
        return None
    crypto = _crypto()
    if not crypto.is_enabled() or crypto.is_blind_index(value):
        return value
    return crypto.blind_index(value, context=context)


def _id_pair(value: Optional[str], context: str) -> Tuple[Optional[str], Optional[str]]:
    """(valor legado em claro, forma gravada). Iguais quando a cifra está desligada.

    Se ``value`` já é índice cego, os dois lados batem na coluna — não re-hash.
    """
    if value is None:
        return None, None
    crypto = _crypto()
    if not crypto.is_enabled() or crypto.is_blind_index(value):
        return value, value
    return value, crypto.blind_index(value, context=context)


def _open_stored_json(value: Any, *, aad: str) -> Dict[str, Any]:
    opened = _crypto().open_json_value(_load_json(value), aad=aad)
    if isinstance(opened, dict):
        return opened
    return {}


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or os.getenv("OPERATIONAL_DATABASE_URL") or "").strip()


def redact_database_url(url: str) -> str:
    """Esconde senha para logs."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(f":{parsed.password}", ":***")
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    if "@" in url:
        head, tail = url.rsplit("@", 1)
        return f"{head.split(':')[0]}:***@{tail}"
    return url


def get_engine() -> Optional[Engine]:
    try:
        from src.ops.operational_patients import get_engine as ops_engine

        return ops_engine()
    except Exception as exc:
        if database_url():
            raise DurableStoreUnavailable(str(exc)) from exc
        return None


def is_configured() -> bool:
    if database_url():
        return True
    try:
        from src.ops.operational_patients import get_engine as ops_engine

        return ops_engine() is not None
    except Exception:
        return False


def _require_engine() -> Engine:
    engine = get_engine()
    if engine is None:
        raise DurableStoreUnavailable("DATABASE_URL não configurada")
    return engine


def _dialect_name(engine: Engine) -> str:
    return (engine.dialect.name or "").lower()


def migration_sql_path(name: str = MIGRATION_NAME) -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "migrations" / name,
        here.parents[1] / "migrations" / name,
        Path.cwd() / "migrations" / name,
        Path.cwd() / "saude_responsiva_secure" / "migrations" / name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"{name} não encontrado. Procurado em: "
        + ", ".join(str(p) for p in candidates)
    )


def _sqlite_ddl() -> List[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS wearable_readings (
            reading_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            device_label TEXT,
            reported_patient_id TEXT,
            metric_type TEXT NOT NULL,
            value DOUBLE PRECISION,
            unit TEXT,
            measured_at DATETIME,
            received_at DATETIME NOT NULL,
            client_reading_id TEXT,
            idempotency_key TEXT,
            natural_patient_id TEXT,
            natural_device_id TEXT,
            natural_measured_at DATETIME,
            natural_metric_type TEXT,
            extra JSON NOT NULL DEFAULT '{}',
            frame JSON NOT NULL DEFAULT '{}',
            created_at DATETIME NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wearable_readings_client_reading
            ON wearable_readings (patient_id, client_reading_id)
            WHERE client_reading_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wearable_readings_idempotency
            ON wearable_readings (patient_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_wearable_readings_natural
            ON wearable_readings (
                natural_patient_id,
                natural_device_id,
                natural_measured_at,
                natural_metric_type
            )
            WHERE natural_measured_at IS NOT NULL
              AND natural_patient_id IS NOT NULL
              AND natural_device_id IS NOT NULL
              AND natural_metric_type IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_wearable_readings_patient_time
            ON wearable_readings (patient_id, received_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_wearable_readings_device_time
            ON wearable_readings (device_id, received_at DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS wearable_device_last_vitals (
            device_id TEXT PRIMARY KEY,
            spo2 DOUBLE PRECISION,
            last_spo2_at DATETIME,
            steps DOUBLE PRECISION,
            last_steps_at DATETIME,
            blood_pressure_sys DOUBLE PRECISION,
            blood_pressure_dia DOUBLE PRECISION,
            last_bp_at DATETIME,
            updated_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS device_patient_overrides (
            device_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            motivo TEXT
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_device_patient_overrides_patient
            ON device_patient_overrides (patient_id)
        """,
    ]


def _sqlite_add_missing_columns(conn) -> None:
    """SQLite não tem ADD COLUMN IF NOT EXISTS: checa antes (bancos locais antigos)."""
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(wearable_readings)"))}
    if "device_label" not in cols:
        conn.execute(text("ALTER TABLE wearable_readings ADD COLUMN device_label TEXT"))
    if "reported_patient_id" not in cols:
        conn.execute(text("ALTER TABLE wearable_readings ADD COLUMN reported_patient_id TEXT"))


def apply_schema(engine: Optional[Engine] = None) -> str:
    """Aplica as migrações (001–004: leituras, rótulo, last vitals, overrides).

    Tudo idempotente e aditivo. Retorna o dialeto.
    """
    engine = engine or _require_engine()
    dialect = _dialect_name(engine)
    try:
        with engine.begin() as conn:
            if dialect == "sqlite":
                for stmt in _sqlite_ddl():
                    conn.execute(text(stmt))
                _sqlite_add_missing_columns(conn)
            else:
                for name in MIGRATION_NAMES:
                    sql = migration_sql_path(name).read_text(encoding="utf-8")
                    for chunk in _split_sql(sql):
                        conn.execute(text(chunk))
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc
    return dialect


def _split_sql(sql: str) -> List[str]:
    statements: List[str] = []
    buf: List[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        statements.append(tail)
    return statements


def ping() -> None:
    """Falha com DurableStoreUnavailable se o banco não responde."""
    engine = _require_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        from src.ops.timestamps import parse_timestamp

        return parse_timestamp(text_value)
    except Exception:
        pass
    try:
        normalized = text_value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _row_frame(row: Any) -> Dict[str, Any]:
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    frame = _open_stored_json(mapping.get("frame"), aad="wearable.frame")
    out = dict(frame)
    out.setdefault("reading_id", mapping.get("reading_id"))
    out.setdefault("patient_id", mapping.get("patient_id"))
    out.setdefault("device_id", mapping.get("device_id"))
    if mapping.get("reported_patient_id"):
        out.setdefault("reported_patient_id", mapping.get("reported_patient_id"))
    if mapping.get("client_reading_id"):
        out.setdefault("client_reading_id", mapping.get("client_reading_id"))
    if mapping.get("metric_type"):
        out.setdefault("metric_type", mapping.get("metric_type"))
    extra = _open_stored_json(mapping.get("extra"), aad="wearable.extra")
    if extra and "extra" not in out:
        out["extra"] = extra
    label = _row_device_label(mapping, frame, extra)
    if label:
        out["device_label"] = label
    return out


def _row_device_label(
    mapping: Dict[str, Any], frame: Dict[str, Any], extra: Any
) -> Optional[str]:
    """Coluna ``device_label``; para linhas antigas, o que ficou no JSON."""
    from app.models.schemas import normalize_device_label

    candidates = [mapping.get("device_label"), frame.get("device_label")]
    if isinstance(extra, dict):
        candidates.append(extra.get("device_label"))
    for value in candidates:
        try:
            label = normalize_device_label(value) if isinstance(value, str) else None
        except ValueError:
            label = None
        if label:
            return label
    return None


def _value_and_unit(frame: Dict[str, Any], extra: Dict[str, Any], metric_type: str) -> Tuple[Optional[float], Optional[str]]:
    raw = frame.get("raw_telemetry") if isinstance(frame.get("raw_telemetry"), dict) else {}
    candidates = [
        ("heart_rate_bpm", extra.get("heart_rate"), "bpm"),
        ("spo2_percent", extra.get("spo2"), "percent"),
        ("hrv_rmssd_ms", extra.get("hrv_rmssd"), "ms"),
        ("skin_temp_celsius", extra.get("skin_temp"), "celsius"),
        ("activity_level", extra.get("activity_level"), "count"),
    ]
    metric = (metric_type or "").lower()
    if "spo2" in metric and "heart_rate" not in metric:
        spo2 = raw.get("spo2_percent", extra.get("spo2"))
        try:
            return (float(spo2) if spo2 is not None else None), "percent"
        except (TypeError, ValueError):
            return None, "percent"
    for raw_key, extra_val, unit in candidates:
        val = raw.get(raw_key)
        if val is None:
            val = extra_val
        if val is not None:
            try:
                return float(val), unit
            except (TypeError, ValueError):
                continue
    return None, None


def _select_by_keys(
    conn,
    patient_id: str,
    *,
    client_reading_id: Optional[str],
    idempotency_key: Optional[str],
    natural_patient_id: Optional[str],
    natural_device_id: Optional[str],
    natural_measured_at: Optional[datetime],
    natural_metric_type: Optional[str],
) -> Optional[Dict[str, Any]]:
    plain_pid, blind_pid = _id_pair(patient_id, "patient_id")
    plain_npid, blind_npid = _id_pair(natural_patient_id, "patient_id")
    plain_ndid, blind_ndid = _id_pair(natural_device_id, "device_id")
    params: Dict[str, Any] = {
        "patient_id": plain_pid,
        "patient_id_bidx": blind_pid,
        "client_reading_id": client_reading_id,
        "idempotency_key": idempotency_key,
        "natural_patient_id": plain_npid,
        "natural_patient_id_bidx": blind_npid,
        "natural_device_id": plain_ndid,
        "natural_device_id_bidx": blind_ndid,
        "natural_measured_at": natural_measured_at,
        "natural_metric_type": natural_metric_type,
    }
    # OR cobre linha legada (id em claro) e linha nova (índice cego).
    patient_match = "(patient_id = :patient_id OR patient_id = :patient_id_bidx)"
    where = []
    if client_reading_id:
        where.append(f"({patient_match} AND client_reading_id = :client_reading_id)")
    if idempotency_key:
        where.append(f"({patient_match} AND idempotency_key = :idempotency_key)")
    if natural_measured_at and natural_patient_id and natural_device_id and natural_metric_type:
        where.append(
            "("
            "(natural_patient_id = :natural_patient_id "
            "OR natural_patient_id = :natural_patient_id_bidx) "
            "AND (natural_device_id = :natural_device_id "
            "OR natural_device_id = :natural_device_id_bidx) "
            "AND natural_measured_at = :natural_measured_at "
            "AND natural_metric_type = :natural_metric_type"
            ")"
        )
    if not where:
        return None
    sql = (
        "SELECT reading_id, patient_id, device_id, device_label, metric_type, "
        "client_reading_id, extra, frame FROM wearable_readings WHERE "
        + " OR ".join(where)
        + " LIMIT 1"
    )
    row = conn.execute(text(sql), params).fetchone()
    return _row_frame(row) if row else None


def find_duplicate(
    patient_id: str,
    identity: Optional[DedupIdentity] = None,
    *,
    client_reading_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    measured_at: Optional[str] = None,
    metric_type: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Lookup por colunas estruturadas — nunca faz split de string com ':'."""
    ident = identity or DedupIdentity(
        patient_id=patient_id,
        client_reading_id=client_reading_id,
        idempotency_key=idempotency_key,
        natural=(
            NaturalKey(
                patient_id=patient_id,
                device_id=(device_id or "wrist_wearable"),
                measured_at=measured_at or "",
                metric_type=metric_type or "heart_rate",
            )
            if measured_at
            else None
        ),
    )
    if not ident.has_any():
        return None
    nat = ident.natural
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            return _select_by_keys(
                conn,
                ident.patient_id or patient_id,
                client_reading_id=ident.client_reading_id,
                idempotency_key=ident.idempotency_key,
                natural_patient_id=nat.patient_id if nat else None,
                natural_device_id=nat.device_id if nat else None,
                natural_measured_at=_parse_dt(nat.measured_at) if nat else None,
                natural_metric_type=nat.metric_type if nat else None,
            )
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def upsert_reading(
    patient_id: str,
    frame: Dict[str, Any],
    *,
    identity: Optional[DedupIdentity] = None,
    dedup_keys: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
    client_reading_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    measured_at: Optional[str] = None,
    metric_type: Optional[str] = None,
    device_label: Optional[str] = None,
    reported_patient_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """INSERT ... ON CONFLICT DO NOTHING; duplicate devolve o registro original."""
    from app.models.schemas import normalize_device_label

    extra = dict(extra or {})
    stored = dict(frame)
    label = normalize_device_label(device_label or stored.get("device_label"))
    if label:
        stored["device_label"] = label
    stored.setdefault("reading_id", uuid4().hex)
    stored["patient_id"] = patient_id
    reported = (reported_patient_id or stored.get("reported_patient_id") or "").strip() or None
    if reported:
        stored["reported_patient_id"] = reported
    _ = dedup_keys  # legado: não parsear strings com ':'
    nat = identity.natural if identity else None
    cid = (
        client_reading_id
        or (identity.client_reading_id if identity else None)
        or stored.get("client_reading_id")
    )
    hid = idempotency_key or (identity.idempotency_key if identity else None)
    device_id = str(
        stored.get("device_id") or (nat.device_id if nat else None) or "wrist_wearable"
    )
    measured = _parse_dt(measured_at) or (_parse_dt(nat.measured_at) if nat else None)
    metric = (
        (metric_type or stored.get("metric_type") or (nat.metric_type if nat else "") or "").strip()
        or metric_signature(set(extra.keys()), metric_type)
    )
    received = _parse_dt(stored.get("received_at")) or datetime.now(timezone.utc)
    if cid:
        stored["client_reading_id"] = cid
    stored["metric_type"] = metric
    value, unit = _value_and_unit(stored, extra, metric)
    now = datetime.now(timezone.utc)
    crypto = _crypto()
    encrypting = crypto.is_enabled()
    params = {
        "reading_id": stored["reading_id"],
        "patient_id": _stored_id(patient_id, "patient_id"),
        "device_id": _stored_id(device_id, "device_id"),
        "device_label": label,
        "reported_patient_id": _stored_id(reported, "patient_id") if reported else None,
        "metric_type": metric,
        "value": None if encrypting else value,
        "unit": unit,
        "measured_at": measured,
        "received_at": received,
        "client_reading_id": cid,
        "idempotency_key": hid,
        "natural_patient_id": _stored_id(patient_id, "patient_id") if measured else None,
        "natural_device_id": _stored_id(device_id, "device_id") if measured else None,
        "natural_measured_at": measured,
        "natural_metric_type": metric if measured else None,
        "extra": crypto.seal_json(extra, aad="wearable.extra"),
        "frame": crypto.seal_json(stored, aad="wearable.frame"),
        "created_at": now,
    }
    try:
        engine = _require_engine()
        dialect = _dialect_name(engine)
        # Nunca use :nome::jsonb — o bind do SQLAlchemy come o primeiro ':' extra.
        extra_sql = "CAST(:extra AS jsonb)" if dialect == "postgresql" else ":extra"
        frame_sql = "CAST(:frame AS jsonb)" if dialect == "postgresql" else ":frame"
        insert_sql = f"""
            INSERT INTO wearable_readings (
                reading_id, patient_id, device_id, device_label, reported_patient_id,
                metric_type,
                value, unit,
                measured_at, received_at, client_reading_id, idempotency_key,
                natural_patient_id, natural_device_id, natural_measured_at,
                natural_metric_type, extra, frame, created_at
            ) VALUES (
                :reading_id, :patient_id, :device_id, :device_label, :reported_patient_id,
                :metric_type,
                :value, :unit,
                :measured_at, :received_at, :client_reading_id, :idempotency_key,
                :natural_patient_id, :natural_device_id, :natural_measured_at,
                :natural_metric_type, {extra_sql}, {frame_sql}, :created_at
            )
            ON CONFLICT DO NOTHING
            RETURNING reading_id
        """
        with engine.begin() as conn:
            if encrypting:
                # O índice único não casa id em claro com índice cego.
                # A busca OR evita duplicar a leitura legada na virada da chave.
                existing = _select_by_keys(
                    conn,
                    patient_id,
                    client_reading_id=cid,
                    idempotency_key=hid,
                    natural_patient_id=patient_id if measured else None,
                    natural_device_id=device_id if measured else None,
                    natural_measured_at=measured,
                    natural_metric_type=metric if measured else None,
                )
                if existing is not None:
                    return existing, "duplicate"
            inserted = conn.execute(text(insert_sql), params).fetchone()
            if inserted is None:
                existing = _select_by_keys(
                    conn,
                    patient_id,
                    client_reading_id=cid,
                    idempotency_key=hid,
                    natural_patient_id=params["natural_patient_id"],
                    natural_device_id=params["natural_device_id"],
                    natural_measured_at=params["natural_measured_at"],
                    natural_metric_type=params["natural_metric_type"],
                )
                if existing is None:
                    raise DurableStoreUnavailable(
                        "INSERT em conflito sem linha existente (schema incompleto?)"
                    )
                return existing, "duplicate"
            _upsert_device_last_vitals(conn, device_id, stored, dialect)
        return stored, "accepted"
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def get_latest(patient_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT reading_id, patient_id, device_id, device_label, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        WHERE patient_id = :patient_id OR patient_id = :patient_id_bidx
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC, created_at DESC
        LIMIT 1
    """
    plain, blind = _id_pair(patient_id, "patient_id")
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text(sql), {"patient_id": plain, "patient_id_bidx": blind}
            ).fetchone()
        return _row_frame(row) if row else None
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def get_history(patient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    sql = """
        SELECT reading_id, patient_id, device_id, device_label, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        WHERE patient_id = :patient_id OR patient_id = :patient_id_bidx
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC, created_at DESC
        LIMIT :limit
    """
    plain, blind = _id_pair(patient_id, "patient_id")
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(sql),
                {"patient_id": plain, "patient_id_bidx": blind, "limit": int(limit)},
            ).fetchall()
        frames = [_row_frame(row) for row in rows]
        frames.reverse()
        return frames
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc



def _frame_last_vitals(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai SpO₂/passos/pressão válidos de um frame, sem inventar valor."""
    from src.ops.live_devices import valid_blood_pressure, valid_spo2, valid_steps

    raw = frame.get("raw_telemetry") if isinstance(frame.get("raw_telemetry"), dict) else {}
    stamp = frame.get("received_at") or frame.get("timestamp")
    spo2 = valid_spo2((raw or {}).get("spo2_percent", (raw or {}).get("spo2")))
    steps = valid_steps((raw or {}).get("steps"))
    sys_val, dia_val = valid_blood_pressure(
        (raw or {}).get("blood_pressure_sys"), (raw or {}).get("blood_pressure_dia")
    )
    return {
        "spo2": spo2,
        "last_spo2_at": stamp if spo2 is not None else None,
        "steps": steps,
        "last_steps_at": stamp if steps is not None else None,
        "blood_pressure_sys": sys_val,
        "blood_pressure_dia": dia_val,
        "last_bp_at": stamp if sys_val is not None and dia_val is not None else None,
    }


def _seal_optional_vital(value: Any, aad: str) -> Optional[str]:
    if value is None:
        return None
    return _crypto().protect(str(value), aad=aad)


def _open_optional_vital(enc: Any, plain: Any, aad: str) -> Any:
    if enc and _crypto().is_enabled():
        opened = _crypto().open_text(str(enc), aad=aad)
        try:
            return float(opened)
        except (TypeError, ValueError):
            return None
    return plain


def _upsert_device_last_vitals_sealed(conn, device_id: str, frame: Dict[str, Any]) -> None:
    """Grava vitais em ``*_enc`` e zera o DOUBLE quando a migração 005 existe."""
    vitals = _frame_last_vitals(frame)
    if not device_id:
        return
    params = {
        "device_id": device_id,
        "updated_at": datetime.now(timezone.utc),
        "last_spo2_at": vitals["last_spo2_at"],
        "last_steps_at": vitals["last_steps_at"],
        "last_bp_at": vitals["last_bp_at"],
        "spo2_enc": _seal_optional_vital(vitals["spo2"], "vitals.spo2"),
        "steps_enc": _seal_optional_vital(vitals["steps"], "vitals.steps"),
        "blood_pressure_sys_enc": _seal_optional_vital(
            vitals["blood_pressure_sys"], "vitals.blood_pressure_sys"
        ),
        "blood_pressure_dia_enc": _seal_optional_vital(
            vitals["blood_pressure_dia"], "vitals.blood_pressure_dia"
        ),
    }
    conn.execute(
        text(
            """
            INSERT INTO wearable_device_last_vitals (
                device_id, spo2, last_spo2_at, steps, last_steps_at,
                blood_pressure_sys, blood_pressure_dia, last_bp_at, updated_at,
                spo2_enc, steps_enc, blood_pressure_sys_enc, blood_pressure_dia_enc
            ) VALUES (
                :device_id, NULL, :last_spo2_at, NULL, :last_steps_at,
                NULL, NULL, :last_bp_at, :updated_at,
                :spo2_enc, :steps_enc, :blood_pressure_sys_enc, :blood_pressure_dia_enc
            )
            ON CONFLICT (device_id) DO UPDATE SET
                spo2_enc = COALESCE(EXCLUDED.spo2_enc, wearable_device_last_vitals.spo2_enc),
                spo2 = CASE
                    WHEN COALESCE(EXCLUDED.spo2_enc, wearable_device_last_vitals.spo2_enc) IS NOT NULL
                    THEN NULL ELSE wearable_device_last_vitals.spo2 END,
                last_spo2_at = CASE
                    WHEN EXCLUDED.spo2_enc IS NOT NULL THEN EXCLUDED.last_spo2_at
                    ELSE wearable_device_last_vitals.last_spo2_at END,
                steps_enc = COALESCE(EXCLUDED.steps_enc, wearable_device_last_vitals.steps_enc),
                steps = CASE
                    WHEN COALESCE(EXCLUDED.steps_enc, wearable_device_last_vitals.steps_enc) IS NOT NULL
                    THEN NULL ELSE wearable_device_last_vitals.steps END,
                last_steps_at = CASE
                    WHEN EXCLUDED.steps_enc IS NOT NULL THEN EXCLUDED.last_steps_at
                    ELSE wearable_device_last_vitals.last_steps_at END,
                blood_pressure_sys_enc = COALESCE(
                    EXCLUDED.blood_pressure_sys_enc, wearable_device_last_vitals.blood_pressure_sys_enc
                ),
                blood_pressure_dia_enc = COALESCE(
                    EXCLUDED.blood_pressure_dia_enc, wearable_device_last_vitals.blood_pressure_dia_enc
                ),
                blood_pressure_sys = CASE
                    WHEN COALESCE(
                        EXCLUDED.blood_pressure_sys_enc,
                        wearable_device_last_vitals.blood_pressure_sys_enc
                    ) IS NOT NULL THEN NULL
                    ELSE wearable_device_last_vitals.blood_pressure_sys END,
                blood_pressure_dia = CASE
                    WHEN COALESCE(
                        EXCLUDED.blood_pressure_dia_enc,
                        wearable_device_last_vitals.blood_pressure_dia_enc
                    ) IS NOT NULL THEN NULL
                    ELSE wearable_device_last_vitals.blood_pressure_dia END,
                last_bp_at = CASE
                    WHEN EXCLUDED.blood_pressure_sys_enc IS NOT NULL
                     AND EXCLUDED.blood_pressure_dia_enc IS NOT NULL
                    THEN EXCLUDED.last_bp_at
                    ELSE wearable_device_last_vitals.last_bp_at END,
                updated_at = EXCLUDED.updated_at
            """
        ),
        params,
    )


def _upsert_device_last_vitals(
    conn, device_id: str, frame: Dict[str, Any], dialect: str
) -> None:
    if _crypto().is_enabled() and table_has_column(
        conn, "wearable_device_last_vitals", "spo2_enc"
    ):
        _upsert_device_last_vitals_sealed(conn, device_id, frame)
        return
    vitals = _frame_last_vitals(frame)
    if not device_id:
        return
    if all(
        vitals[key] is None
        for key in ("spo2", "steps", "blood_pressure_sys", "blood_pressure_dia")
    ):
        # Mesmo sem vitais novos, garante a linha para merges posteriores.
        pass
    now = datetime.now(timezone.utc)
    params = {"device_id": device_id, "updated_at": now, **vitals}
    sql = """
        INSERT INTO wearable_device_last_vitals (
            device_id, spo2, last_spo2_at, steps, last_steps_at,
            blood_pressure_sys, blood_pressure_dia, last_bp_at, updated_at
        ) VALUES (
            :device_id, :spo2, :last_spo2_at, :steps, :last_steps_at,
            :blood_pressure_sys, :blood_pressure_dia, :last_bp_at, :updated_at
        )
        ON CONFLICT (device_id) DO UPDATE SET
            spo2 = COALESCE(EXCLUDED.spo2, wearable_device_last_vitals.spo2),
            last_spo2_at = CASE
                WHEN EXCLUDED.spo2 IS NOT NULL THEN EXCLUDED.last_spo2_at
                ELSE wearable_device_last_vitals.last_spo2_at
            END,
            steps = COALESCE(EXCLUDED.steps, wearable_device_last_vitals.steps),
            last_steps_at = CASE
                WHEN EXCLUDED.steps IS NOT NULL THEN EXCLUDED.last_steps_at
                ELSE wearable_device_last_vitals.last_steps_at
            END,
            blood_pressure_sys = COALESCE(
                EXCLUDED.blood_pressure_sys, wearable_device_last_vitals.blood_pressure_sys
            ),
            blood_pressure_dia = COALESCE(
                EXCLUDED.blood_pressure_dia, wearable_device_last_vitals.blood_pressure_dia
            ),
            last_bp_at = CASE
                WHEN EXCLUDED.blood_pressure_sys IS NOT NULL
                 AND EXCLUDED.blood_pressure_dia IS NOT NULL
                THEN EXCLUDED.last_bp_at
                ELSE wearable_device_last_vitals.last_bp_at
            END,
            updated_at = EXCLUDED.updated_at
    """
    _ = dialect
    conn.execute(text(sql), params)


def list_device_last_vitals() -> Dict[str, Dict[str, Any]]:
    """Snapshot compacto (uma linha por device) para merge na frota."""
    base = (
        "device_id, spo2, last_spo2_at, steps, last_steps_at, "
        "blood_pressure_sys, blood_pressure_dia, last_bp_at"
    )
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            sealed = table_has_column(conn, "wearable_device_last_vitals", "spo2_enc")
            columns = base
            if sealed:
                columns += (
                    ", spo2_enc, steps_enc, blood_pressure_sys_enc, blood_pressure_dia_enc"
                )
            rows = conn.execute(
                text(f"SELECT {columns} FROM wearable_device_last_vitals")
            ).fetchall()
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        device_id = str(mapping.get("device_id") or "")
        if not device_id:
            continue
        out[device_id] = {
            "device_id": device_id,
            "spo2": _open_optional_vital(
                mapping.get("spo2_enc"), mapping.get("spo2"), "vitals.spo2"
            ),
            "last_spo2_at": mapping.get("last_spo2_at"),
            "steps": _open_optional_vital(
                mapping.get("steps_enc"), mapping.get("steps"), "vitals.steps"
            ),
            "last_steps_at": mapping.get("last_steps_at"),
            "blood_pressure_sys": _open_optional_vital(
                mapping.get("blood_pressure_sys_enc"),
                mapping.get("blood_pressure_sys"),
                "vitals.blood_pressure_sys",
            ),
            "blood_pressure_dia": _open_optional_vital(
                mapping.get("blood_pressure_dia_enc"),
                mapping.get("blood_pressure_dia"),
                "vitals.blood_pressure_dia",
            ),
            "last_bp_at": mapping.get("last_bp_at"),
        }
    return out


_backfill_lock = threading.Lock()
_backfill_done = False



def _latest_valid_vital_frame(conn, device_id: str, raw_key: str) -> Optional[Dict[str, Any]]:
    """Último frame do device com um vital no JSON (lookup pontual, não a tabela inteira)."""
    allowed = {"spo2_percent", "steps", "blood_pressure_sys", "blood_pressure_dia"}
    if raw_key not in allowed:
        return None
    if _crypto().is_enabled():
        return _latest_vital_opened(conn, device_id, raw_key)
    dialect = _dialect_name(_require_engine())
    if dialect == "sqlite":
        path = "$.raw_telemetry." + raw_key
        sql = text(
            f"""
            SELECT reading_id, patient_id, device_id, device_label, metric_type,
                   client_reading_id, extra, frame, received_at, measured_at
            FROM wearable_readings
            WHERE device_id = :device_id
              AND NULLIF(TRIM(json_extract(frame, '{path}')), '') IS NOT NULL
            ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC
            LIMIT 1
            """
        )
        row = conn.execute(sql, {"device_id": device_id}).fetchone()
    else:
        sql = text(
            """
            SELECT reading_id, patient_id, device_id, device_label, metric_type,
                   client_reading_id, extra, frame, received_at, measured_at
            FROM wearable_readings
            WHERE device_id = :device_id
              AND NULLIF(TRIM(frame->'raw_telemetry'->>:raw_key), '') IS NOT NULL
            ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC
            LIMIT 1
            """
        )
        row = conn.execute(sql, {"device_id": device_id, "raw_key": raw_key}).fetchone()
    return _row_frame(row) if row else None


def _latest_vital_opened(conn, device_id: str, raw_key: str) -> Optional[Dict[str, Any]]:
    """Último frame com o vital, abrindo ciphertext. O JSON path não enxerga ``_enc``."""
    plain, blind = _id_pair(device_id, "device_id")
    rows = conn.execute(
        text(
            """
            SELECT reading_id, patient_id, device_id, device_label, metric_type,
                   client_reading_id, extra, frame, received_at, measured_at
            FROM wearable_readings
            WHERE device_id = :plain OR device_id = :blind
            ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC
            LIMIT 400
            """
        ),
        {"plain": plain, "blind": blind},
    ).fetchall()
    for row in rows:
        frame = _row_frame(row)
        raw = frame.get("raw_telemetry") if isinstance(frame.get("raw_telemetry"), dict) else {}
        val = raw.get(raw_key)
        if val is None or (isinstance(val, str) and not str(val).strip()):
            continue
        return frame
    return None


def backfill_device_last_vitals(*, force: bool = False) -> int:
    """Preenche o snapshot a partir do histórico. Uma vez (ou force=True).

    Usa as leituras já persistidas, em memória no dialeto de teste e via
    varredura única no Postgres. Não entra no caminho de GET /devices.
    """
    global _backfill_done
    with _backfill_lock:
        if _backfill_done and not force:
            return 0
        try:
            engine = _require_engine()
            apply_schema(engine)
            with engine.connect() as conn:
                if not force:
                    existing = conn.execute(
                        text("SELECT COUNT(*) FROM wearable_device_last_vitals")
                    ).scalar()
                    if int(existing or 0) > 0:
                        _backfill_done = True
                        return 0
            latest = latest_frames_by_device()
        except DurableStoreUnavailable as exc:
            logger.warning("Backfill de last vitals adiado: %s", exc)
            return 0
        except SQLAlchemyError as exc:
            logger.warning("Backfill de last vitals adiado: %s", exc)
            return 0
        count = 0
        try:
            dialect = _dialect_name(engine)
            with engine.begin() as conn:
                for frame in latest:
                    device_id = str(frame.get("device_id") or "")
                    if not device_id:
                        continue
                    # Completa vitais ausentes no último frame com um lookup pontual.
                    filled = dict(frame)
                    raw = dict(filled.get("raw_telemetry") or {})
                    vitals = _frame_last_vitals(filled)
                    if vitals.get("spo2") is None:
                        prev = _latest_valid_vital_frame(conn, device_id, "spo2_percent")
                        if prev:
                            raw["spo2_percent"] = (prev.get("raw_telemetry") or {}).get("spo2_percent")
                            filled["raw_telemetry"] = raw
                    if vitals.get("steps") is None:
                        prev = _latest_valid_vital_frame(conn, device_id, "steps")
                        if prev:
                            raw["steps"] = (prev.get("raw_telemetry") or {}).get("steps")
                            filled["raw_telemetry"] = raw
                    if vitals.get("blood_pressure_sys") is None:
                        prev = _latest_valid_vital_frame(conn, device_id, "blood_pressure_sys")
                        if prev:
                            prev_raw = prev.get("raw_telemetry") or {}
                            raw["blood_pressure_sys"] = prev_raw.get("blood_pressure_sys")
                            raw["blood_pressure_dia"] = prev_raw.get("blood_pressure_dia")
                            filled["raw_telemetry"] = raw
                    _upsert_device_last_vitals(conn, device_id, filled, dialect)
                    count += 1
        except SQLAlchemyError as exc:
            logger.warning("Backfill de last vitals falhou: %s", exc)
            return 0
        _backfill_done = True
        if count:
            logger.info("Backfill de last vitals: %s frames processados", count)
        return count


def list_frames() -> List[Dict[str, Any]]:
    """Todos os frames persistidos, mais novos primeiro (uso em testes / fallback)."""
    sql = """
        SELECT reading_id, patient_id, device_id, device_label, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        return [_row_frame(row) for row in rows]
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


_PG_LATEST_BY_DEVICE = """
    SELECT DISTINCT ON (device_id)
        reading_id, patient_id, device_id, device_label, metric_type,
        client_reading_id, extra, frame
    FROM wearable_readings
    ORDER BY device_id, COALESCE(measured_at, received_at) DESC, received_at DESC
"""

_PG_LATEST_LABEL_BY_DEVICE = """
    SELECT DISTINCT ON (device_id)
        device_id, COALESCE(device_label, extra->>'device_label') AS device_label
    FROM wearable_readings
    WHERE device_label IS NOT NULL OR extra->>'device_label' IS NOT NULL
    ORDER BY device_id, COALESCE(measured_at, received_at) DESC, received_at DESC
"""


def _pg_latest_frames_by_device(engine: Engine) -> List[Dict[str, Any]]:
    """Uma linha por device no próprio Postgres (sem trazer a tabela inteira)."""
    from app.models.schemas import normalize_device_label

    with engine.connect() as conn:
        rows = conn.execute(text(_PG_LATEST_BY_DEVICE)).fetchall()
        label_rows = conn.execute(text(_PG_LATEST_LABEL_BY_DEVICE)).fetchall()
    # A chave do mapa é o device_id da COLUNA (claro ou índice cego).
    # O frame aberto devolve o id original; casar os dois quebraria o rótulo.
    paired: List[Tuple[str, Dict[str, Any]]] = []
    for row in rows:
        mapping = dict(row._mapping)
        paired.append((str(mapping.get("device_id") or ""), _row_frame(row)))
    labels: Dict[str, str] = {}
    for row in label_rows:
        mapping = dict(row._mapping)
        try:
            label = normalize_device_label(mapping.get("device_label"))
        except ValueError:
            label = None
        if label:
            labels[str(mapping.get("device_id"))] = label
    frames = []
    for storage_id, frame in paired:
        label = labels.get(storage_id)
        if label:
            frame["device_label"] = label
        frames.append(frame)
    frames.sort(key=lambda f: str(f.get("timestamp") or ""), reverse=True)
    return frames


def latest_frames_by_device() -> List[Dict[str, Any]]:
    """Último frame por device. No Postgres usa DISTINCT ON; nos testes, agrupa em memória."""
    try:
        engine = _require_engine()
        if _dialect_name(engine) == "postgresql":
            return _pg_latest_frames_by_device(engine)
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc
    sql = """
        SELECT reading_id, patient_id, device_id, device_label, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        latest: Dict[str, Dict[str, Any]] = {}
        labels: Dict[str, str] = {}
        for row in rows:
            frame = _row_frame(row)
            device_id = str(frame.get("device_id") or "unknown")
            if device_id not in latest:
                latest[device_id] = frame
            if device_id not in labels and frame.get("device_label"):
                labels[device_id] = str(frame["device_label"])
        for device_id, label in labels.items():
            latest[device_id]["device_label"] = label
        return list(latest.values())
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def iter_patients(limit_per_patient: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    sql = """
        SELECT reading_id, patient_id, device_id, device_label, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        ORDER BY patient_id ASC, COALESCE(measured_at, received_at) ASC, received_at ASC
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            frame = _row_frame(row)
            pid = str(frame.get("patient_id") or "")
            if not pid:
                continue
            grouped.setdefault(pid, []).append(frame)
        for pid, frames in list(grouped.items()):
            if len(frames) > limit_per_patient:
                grouped[pid] = frames[-limit_per_patient:]
        return grouped
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def anonymize_patient(patient_id: str) -> bool:
    plain, blind = _id_pair(patient_id, "patient_id")
    try:
        engine = _require_engine()
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM wearable_readings "
                    "WHERE patient_id = :patient_id OR patient_id = :patient_id_bidx"
                ),
                {"patient_id": plain, "patient_id_bidx": blind},
            )
        return bool(result.rowcount)
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def stats() -> Dict[str, int]:
    sql = """
        SELECT COUNT(DISTINCT patient_id) AS patients_tracked,
               COUNT(*) AS history_entries
        FROM wearable_readings
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            row = conn.execute(text(sql)).fetchone()
        mapping = dict(row._mapping) if row is not None and hasattr(row, "_mapping") else {}
        return {
            "patients_tracked": int(mapping.get("patients_tracked") or 0),
            "history_entries": int(mapping.get("history_entries") or 0),
        }
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def clear_all() -> None:
    """Utilitário de teste — apaga todas as leituras duráveis."""
    engine = _require_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM wearable_readings"))
        conn.execute(text("DELETE FROM wearable_device_last_vitals"))


def log_backend() -> str:
    """Loga qual store está ativo. Retorna ``durable`` ou ``memory``."""
    if not is_configured():
        logger.info(
            "Wearable telemetry store: in-memory "
            "(DATABASE_URL unset; local/tests only — readings are not durable)"
        )
        return "memory"
    url = database_url()
    label = redact_database_url(url) or "injected-engine"
    try:
        apply_schema()
        ping()
        logger.info("Wearable telemetry store: durable (%s)", label)
        threading.Thread(
            target=backfill_device_last_vitals,
            name="last-vitals-backfill",
            daemon=True,
        ).start()
        return "durable"
    except DurableStoreUnavailable as exc:
        logger.error(
            "Wearable telemetry store: DATABASE_URL is set but unreachable (%s). "
            "Ingest will return 5xx (no in-memory fallback). error=%s",
            label,
            exc,
        )
        return "durable-unavailable"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not is_configured():
        logger.error("DATABASE_URL / OPERATIONAL_DATABASE_URL ausente. Nada a migrar.")
        return 2
    dialect = apply_schema()
    ping()
    logger.info("Migration %s applied (%s) on %s", MIGRATION_NAME, dialect, redact_database_url(database_url()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
