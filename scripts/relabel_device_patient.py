#!/usr/bin/env python3
"""Relabel opcional de leituras antigas de um aparelho para o patient_id canônico.

Dry-run por padrão (não grava). Só escreve com --apply, depois de um backup
das linhas afetadas (sem sinais vitais / sem frame clínico).

Não imprime DATABASE_URL, senhas, chaves nem o conteúdo clínico das leituras.

    python scripts/relabel_device_patient.py \
        --device-id 'AA:BB:CC:11:22:33' \
        --from-patient-id PAT-TESTE-AAAA \
        --to-patient-id PAT-TESTE-BBBB

    python scripts/relabel_device_patient.py ... --apply

Rollback (manual, com o backup_id impresso):

    UPDATE wearable_readings AS r
    SET patient_id = b.patient_id,
        reported_patient_id = b.reported_patient_id,
        natural_patient_id = b.natural_patient_id
    FROM wearable_readings_relabel_backup AS b
    WHERE b.backup_id = '<backup_id>'
      AND b.reading_id = r.reading_id;
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
for candidate in (SECURE, ROOT):
    path = str(candidate)
    if path not in sys.path:
        sys.path.insert(0, path)

from sqlalchemy import text  # noqa: E402

logger = logging.getLogger("relabel_device_patient")


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device-id", required=True, help="Identificador do aparelho (MAC).")
    parser.add_argument("--to-patient-id", required=True, help="patient_id canônico de destino.")
    parser.add_argument(
        "--from-patient-id",
        default=None,
        help="Se informado, só relabel das linhas com esse patient_id atual.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Opcional, ISO-8601 (UTC). Só linhas com measured_at/received_at >= este instante.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava de fato. Sem esta flag, apenas lista o que seria alterado (dry-run).",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()

    from src.ops.device_patient_overrides import (
        normalize_device_id,
        validate_patient_id,
    )
    from app.services import durable_readings

    device_id = normalize_device_id(args.device_id)
    to_pid = validate_patient_id(args.to_patient_id)
    from_pid = validate_patient_id(args.from_patient_id) if args.from_patient_id else None
    if not device_id:
        logger.error("device_id inválido.")
        return 2
    if not to_pid:
        logger.error("to-patient-id inválido.")
        return 2
    if args.from_patient_id and not from_pid:
        logger.error("from-patient-id inválido.")
        return 2

    since = None
    if args.since:
        raw = args.since.strip()
        try:
            since = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            logger.error("since inválido (use ISO-8601).")
            return 2

    if not durable_readings.is_configured():
        logger.error("DATABASE_URL / OPERATIONAL_DATABASE_URL ausente. Nada a fazer.")
        return 2

    try:
        engine = durable_readings.get_engine()
        durable_readings.apply_schema(engine)
    except Exception as exc:
        logger.error("Não foi possível conectar ao store durável (%s).", exc)
        return 2

    dialect = durable_readings._dialect_name(engine)
    params: Dict[str, Any] = {"device_id": device_id, "to_pid": to_pid}
    where = ["(device_id = :device_id OR lower(device_id) = lower(:device_id))"]
    if from_pid:
        params["from_pid"] = from_pid
        where.append("patient_id = :from_pid")
    if since is not None:
        params["since"] = since
        where.append("COALESCE(measured_at, received_at) >= :since")
    where.append("patient_id <> :to_pid")
    where_sql = " AND ".join(where)

    select_sql = f"""
        SELECT reading_id, patient_id, device_id, reported_patient_id,
               natural_patient_id, client_reading_id, idempotency_key,
               measured_at, received_at
        FROM wearable_readings
        WHERE {where_sql}
        ORDER BY COALESCE(measured_at, received_at) ASC
    """

    with engine.connect() as conn:
        rows = [dict(r._mapping) if hasattr(r, "_mapping") else dict(r) for r in conn.execute(text(select_sql), params)]

    logger.info(
        "Candidatas: %s leitura(s). device_id=%s from=%s to=%s since=%s mode=%s",
        len(rows),
        device_id,
        from_pid or "*",
        to_pid,
        _iso(since) or "*",
        "APPLY" if args.apply else "DRY-RUN",
    )
    # Só identidade — sem vitais.
    current_ids = {}
    for row in rows:
        pid = row.get("patient_id")
        current_ids[pid] = current_ids.get(pid, 0) + 1
    logger.info("Distribuição atual de patient_id: %s", current_ids)

    if not rows:
        return 0
    if not args.apply:
        logger.info("Dry-run. Nenhuma linha foi alterada. Rode de novo com --apply para gravar.")
        return 0

    backup_id = uuid.uuid4().hex
    backed_up_at = datetime.now(timezone.utc)
    conflicts = 0
    updated = 0

    backup_ddl_pg = """
        CREATE TABLE IF NOT EXISTS wearable_readings_relabel_backup (
            backup_id TEXT NOT NULL,
            backed_up_at TIMESTAMPTZ NOT NULL,
            reading_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            reported_patient_id TEXT,
            natural_patient_id TEXT,
            client_reading_id TEXT,
            idempotency_key TEXT,
            measured_at TIMESTAMPTZ,
            received_at TIMESTAMPTZ,
            PRIMARY KEY (backup_id, reading_id)
        )
    """
    backup_ddl_sqlite = backup_ddl_pg.replace("TIMESTAMPTZ", "DATETIME")

    with engine.begin() as conn:
        conn.execute(text(backup_ddl_sqlite if dialect == "sqlite" else backup_ddl_pg))
        for row in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO wearable_readings_relabel_backup (
                        backup_id, backed_up_at, reading_id, patient_id, device_id,
                        reported_patient_id, natural_patient_id, client_reading_id,
                        idempotency_key, measured_at, received_at
                    ) VALUES (
                        :backup_id, :backed_up_at, :reading_id, :patient_id, :device_id,
                        :reported_patient_id, :natural_patient_id, :client_reading_id,
                        :idempotency_key, :measured_at, :received_at
                    )
                    """
                ),
                {
                    "backup_id": backup_id,
                    "backed_up_at": backed_up_at,
                    "reading_id": row["reading_id"],
                    "patient_id": row["patient_id"],
                    "device_id": row["device_id"],
                    "reported_patient_id": row.get("reported_patient_id"),
                    "natural_patient_id": row.get("natural_patient_id"),
                    "client_reading_id": row.get("client_reading_id"),
                    "idempotency_key": row.get("idempotency_key"),
                    "measured_at": row.get("measured_at"),
                    "received_at": row.get("received_at"),
                },
            )

        for row in rows:
            cid = row.get("client_reading_id")
            if cid:
                clash = conn.execute(
                    text(
                        """
                        SELECT reading_id FROM wearable_readings
                        WHERE patient_id = :to_pid
                          AND client_reading_id = :cid
                          AND reading_id <> :reading_id
                        LIMIT 1
                        """
                    ),
                    {"to_pid": to_pid, "cid": cid, "reading_id": row["reading_id"]},
                ).fetchone()
                if clash is not None:
                    conflicts += 1
                    logger.warning(
                        "Conflito de dedup (client_reading_id) — linha %s não alterada.",
                        row["reading_id"],
                    )
                    continue
            if dialect == "sqlite":
                frame_sql = (
                    "json_set(COALESCE(frame, '{}'), '$.patient_id', :to_pid, "
                    "'$.reported_patient_id', COALESCE(reported_patient_id, patient_id))"
                )
            else:
                frame_sql = (
                    "jsonb_set("
                    "jsonb_set(COALESCE(frame, '{}'::jsonb), '{patient_id}', to_jsonb(:to_pid), true), "
                    "'{reported_patient_id}', to_jsonb(COALESCE(reported_patient_id, patient_id)), true)"
                )
            conn.execute(
                text(
                    f"""
                    UPDATE wearable_readings
                    SET patient_id = :to_pid,
                        reported_patient_id = COALESCE(reported_patient_id, patient_id),
                        natural_patient_id = CASE
                            WHEN natural_patient_id IS NULL THEN natural_patient_id
                            WHEN natural_patient_id = patient_id THEN :to_pid
                            ELSE natural_patient_id
                        END,
                        frame = {frame_sql}
                    WHERE reading_id = :reading_id
                    """
                ),
                {"to_pid": to_pid, "reading_id": row["reading_id"]},
            )
            updated += 1

    logger.info(
        "Aplicado: %s atualizada(s), %s conflito(s) preservado(s). backup_id=%s",
        updated,
        conflicts,
        backup_id,
    )
    return 0 if conflicts == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
