#!/usr/bin/env python3
"""Cria o índice da última leitura por aparelho, fora do boot.

``CREATE INDEX CONCURRENTLY`` não entra na transação das migrações 001–004.
Não lê ``frame`` nem ``extra``. Recusa rodar sem
``CREATE_DEVICE_LATEST_INDEX_CONFIRM=yes``.

    CREATE_DEVICE_LATEST_INDEX_CONFIRM=yes \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/create_device_latest_index.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
for path in (SECURE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SCHEMA = SECURE / "migrations" / "006_wearable_device_latest_index.sql"


def _confirm_or_exit() -> None:
    if os.getenv("CREATE_DEVICE_LATEST_INDEX_CONFIRM") != "yes":
        print(
            "Recusado: defina CREATE_DEVICE_LATEST_INDEX_CONFIRM=yes. "
            "Nenhum índice foi criado.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    del argv
    _confirm_or_exit()

    from sqlalchemy import text

    from app.services.durable_readings import (
        _split_sql,
        database_url,
        get_engine,
        redact_database_url,
    )

    if not database_url():
        print("DATABASE_URL / OPERATIONAL_DATABASE_URL ausente. Nada feito.", file=sys.stderr)
        return 2
    engine = get_engine()
    if engine is None:
        print("Engine indisponível. Nada feito.", file=sys.stderr)
        return 2
    print(f"Banco: {redact_database_url(database_url())}")
    statements = _split_sql(SCHEMA.read_text(encoding="utf-8"))
    if not statements:
        print(f"SQL vazio: {SCHEMA.name}", file=sys.stderr)
        return 2
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET lock_timeout = '15s'"))
        for statement in statements:
            if "CONCURRENTLY" not in statement.upper():
                print(
                    "Recusado: a migração 006 só roda com CREATE INDEX CONCURRENTLY.",
                    file=sys.stderr,
                )
                return 2
            conn.execute(text(statement))
            print("Índice aplicado (ou já existia): ix_wearable_readings_device_latest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
