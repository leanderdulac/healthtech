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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

MIGRATION_NAME = "001_wearable_readings.sql"


class DurableStoreUnavailable(RuntimeError):
    """DATABASE_URL configurada mas o Postgres está inacessível / schema ausente."""


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


def migration_sql_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "migrations" / MIGRATION_NAME,
        here.parents[1] / "migrations" / MIGRATION_NAME,
        Path.cwd() / "migrations" / MIGRATION_NAME,
        Path.cwd() / "saude_responsiva_secure" / "migrations" / MIGRATION_NAME,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"{MIGRATION_NAME} não encontrado. Procurado em: "
        + ", ".join(str(p) for p in candidates)
    )


def _sqlite_ddl() -> List[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS wearable_readings (
            reading_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
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
    ]


def apply_schema(engine: Optional[Engine] = None) -> str:
    """Aplica ``001_wearable_readings`` (CREATE IF NOT EXISTS). Retorna o dialeto."""
    engine = engine or _require_engine()
    dialect = _dialect_name(engine)
    try:
        with engine.begin() as conn:
            if dialect == "sqlite":
                for stmt in _sqlite_ddl():
                    conn.execute(text(stmt))
            else:
                sql = migration_sql_path().read_text(encoding="utf-8")
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
    frame = _load_json(mapping.get("frame"))
    if not isinstance(frame, dict):
        frame = {}
    out = dict(frame)
    out.setdefault("reading_id", mapping.get("reading_id"))
    out.setdefault("patient_id", mapping.get("patient_id"))
    out.setdefault("device_id", mapping.get("device_id"))
    if mapping.get("client_reading_id"):
        out.setdefault("client_reading_id", mapping.get("client_reading_id"))
    if mapping.get("metric_type"):
        out.setdefault("metric_type", mapping.get("metric_type"))
    extra = _load_json(mapping.get("extra"))
    if extra and "extra" not in out:
        out["extra"] = extra
    return out


def _natural_parts(dedup_keys: List[str]) -> Tuple[Optional[str], Optional[str], Optional[datetime], Optional[str]]:
    for key in dedup_keys:
        if not key.startswith("nat:"):
            continue
        parts = key.split(":", 4)
        if len(parts) < 5:
            continue
        return parts[1], parts[2], _parse_dt(parts[3]), parts[4]
    return None, None, None, None


def _client_id_from_keys(dedup_keys: List[str]) -> Optional[str]:
    for key in dedup_keys:
        if key.startswith("cid:"):
            return key.split(":", 2)[-1]
    return None


def _idem_from_keys(dedup_keys: List[str]) -> Optional[str]:
    for key in dedup_keys:
        if key.startswith("hdr:"):
            return key.split(":", 2)[-1]
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
    params: Dict[str, Any] = {
        "patient_id": patient_id,
        "client_reading_id": client_reading_id,
        "idempotency_key": idempotency_key,
        "natural_patient_id": natural_patient_id,
        "natural_device_id": natural_device_id,
        "natural_measured_at": natural_measured_at,
        "natural_metric_type": natural_metric_type,
    }
    where = []
    if client_reading_id:
        where.append(
            "(patient_id = :patient_id AND client_reading_id = :client_reading_id)"
        )
    if idempotency_key:
        where.append(
            "(patient_id = :patient_id AND idempotency_key = :idempotency_key)"
        )
    if natural_measured_at and natural_patient_id and natural_device_id and natural_metric_type:
        where.append(
            "("
            "natural_patient_id = :natural_patient_id "
            "AND natural_device_id = :natural_device_id "
            "AND natural_measured_at = :natural_measured_at "
            "AND natural_metric_type = :natural_metric_type"
            ")"
        )
    if not where:
        return None
    sql = (
        "SELECT reading_id, patient_id, device_id, metric_type, "
        "client_reading_id, extra, frame FROM wearable_readings WHERE "
        + " OR ".join(where)
        + " LIMIT 1"
    )
    row = conn.execute(text(sql), params).fetchone()
    return _row_frame(row) if row else None


def find_duplicate(patient_id: str, dedup_keys: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    keys = [k for k in (dedup_keys or []) if k]
    if not keys:
        return None
    nat_p, nat_d, nat_ts, nat_m = _natural_parts(keys)
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            return _select_by_keys(
                conn,
                patient_id,
                client_reading_id=_client_id_from_keys(keys),
                idempotency_key=_idem_from_keys(keys),
                natural_patient_id=nat_p,
                natural_device_id=nat_d,
                natural_measured_at=nat_ts,
                natural_metric_type=nat_m,
            )
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def upsert_reading(
    patient_id: str,
    frame: Dict[str, Any],
    *,
    dedup_keys: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
    client_reading_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    measured_at: Optional[str] = None,
    metric_type: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """INSERT ... ON CONFLICT DO NOTHING; duplicate devolve o registro original."""
    keys = [k for k in (dedup_keys or []) if k]
    extra = dict(extra or {})
    stored = dict(frame)
    stored.setdefault("reading_id", uuid4().hex)
    stored["patient_id"] = patient_id
    cid = client_reading_id or stored.get("client_reading_id") or _client_id_from_keys(keys)
    hid = idempotency_key or _idem_from_keys(keys)
    nat_p, nat_d, nat_ts, nat_m = _natural_parts(keys)
    metric = (metric_type or stored.get("metric_type") or nat_m or "heart_rate")
    measured = _parse_dt(measured_at) or nat_ts
    received = _parse_dt(stored.get("received_at")) or datetime.now(timezone.utc)
    device_id = str(stored.get("device_id") or nat_d or "wrist_wearable")
    if cid:
        stored["client_reading_id"] = cid
    stored["metric_type"] = metric
    value, unit = _value_and_unit(stored, extra, metric)
    now = datetime.now(timezone.utc)
    params = {
        "reading_id": stored["reading_id"],
        "patient_id": patient_id,
        "device_id": device_id,
        "metric_type": metric,
        "value": value,
        "unit": unit,
        "measured_at": measured,
        "received_at": received,
        "client_reading_id": cid,
        "idempotency_key": hid,
        "natural_patient_id": nat_p or (patient_id if measured else None),
        "natural_device_id": nat_d or (device_id if measured else None),
        "natural_measured_at": measured,
        "natural_metric_type": nat_m or (metric if measured else None),
        "extra": json.dumps(extra, default=str),
        "frame": json.dumps(stored, default=str),
        "created_at": now,
    }
    try:
        engine = _require_engine()
        dialect = _dialect_name(engine)
        extra_sql = ":extra::jsonb" if dialect == "postgresql" else ":extra"
        frame_sql = ":frame::jsonb" if dialect == "postgresql" else ":frame"
        insert_sql = f"""
            INSERT INTO wearable_readings (
                reading_id, patient_id, device_id, metric_type, value, unit,
                measured_at, received_at, client_reading_id, idempotency_key,
                natural_patient_id, natural_device_id, natural_measured_at,
                natural_metric_type, extra, frame, created_at
            ) VALUES (
                :reading_id, :patient_id, :device_id, :metric_type, :value, :unit,
                :measured_at, :received_at, :client_reading_id, :idempotency_key,
                :natural_patient_id, :natural_device_id, :natural_measured_at,
                :natural_metric_type, {extra_sql}, {frame_sql}, :created_at
            )
            ON CONFLICT DO NOTHING
            RETURNING reading_id
        """
        with engine.begin() as conn:
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
        return stored, "accepted"
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def get_latest(patient_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT reading_id, patient_id, device_id, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        WHERE patient_id = :patient_id
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC, created_at DESC
        LIMIT 1
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            row = conn.execute(text(sql), {"patient_id": patient_id}).fetchone()
        return _row_frame(row) if row else None
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def get_history(patient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    sql = """
        SELECT reading_id, patient_id, device_id, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        WHERE patient_id = :patient_id
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC, created_at DESC
        LIMIT :limit
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(sql), {"patient_id": patient_id, "limit": int(limit)}
            ).fetchall()
        frames = [_row_frame(row) for row in rows]
        frames.reverse()
        return frames
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def latest_frames_by_device() -> List[Dict[str, Any]]:
    sql = """
        SELECT reading_id, patient_id, device_id, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        ORDER BY COALESCE(measured_at, received_at) DESC, received_at DESC
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        latest: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            frame = _row_frame(row)
            device_id = str(frame.get("device_id") or "unknown")
            if device_id not in latest:
                latest[device_id] = frame
        return list(latest.values())
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def iter_patients(limit_per_patient: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    sql = """
        SELECT reading_id, patient_id, device_id, metric_type, client_reading_id, extra, frame
        FROM wearable_readings
        ORDER BY patient_id ASC, COALESCE(measured_at, received_at) ASC, received_at ASC
    """
    try:
        engine = _require_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).fetchall()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            pid = str(mapping.get("patient_id") or "")
            if not pid:
                continue
            grouped.setdefault(pid, []).append(_row_frame(row))
        for pid, frames in list(grouped.items()):
            if len(frames) > limit_per_patient:
                grouped[pid] = frames[-limit_per_patient:]
        return grouped
    except DurableStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise DurableStoreUnavailable(str(exc)) from exc


def anonymize_patient(patient_id: str) -> bool:
    try:
        engine = _require_engine()
        with engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM wearable_readings WHERE patient_id = :patient_id"),
                {"patient_id": patient_id},
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
