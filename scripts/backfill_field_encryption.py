#!/usr/bin/env python3
"""Backfill idempotente da criptografia de campos (R8).

Não roda no boot e não é chamado pelo deploy. Recusa executar sem
``BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes``.

Exemplos (valores de chave só no ambiente, nunca neste arquivo):

    # conta o que mudaria, sem gravar
    BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \\
    FIELD_ENCRYPTION_KEY="$DEK" FIELD_BLIND_INDEX_KEY="$BIK" \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/backfill_field_encryption.py --dry-run

    # aplica colunas 005 e reescreve linhas ainda em claro
    BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \\
    FIELD_ENCRYPTION_KEY="$DEK" FIELD_BLIND_INDEX_KEY="$BIK" \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/backfill_field_encryption.py --apply-schema

    # rollback: volta ao claro enquanto a chave ainda está no ambiente
    BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \\
    FIELD_ENCRYPTION_KEY="$DEK" FIELD_BLIND_INDEX_KEY="$BIK" \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/backfill_field_encryption.py --decrypt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
for path in (SECURE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SCHEMA = SECURE / "migrations" / "005_field_encryption.sql"


def _confirm_or_exit() -> None:
    if os.getenv("BACKFILL_FIELD_ENCRYPTION_CONFIRM") != "yes":
        print(
            "Recusado: defina BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes "
            "depois do OK do Leandro. Nenhuma linha foi alterada.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _apply_schema(engine) -> None:
    from sqlalchemy import text

    from app.services.durable_readings import _split_sql

    sql = SCHEMA.read_text(encoding="utf-8")
    with engine.begin() as conn:
        for statement in _split_sql(sql):
            conn.execute(text(statement))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill da criptografia R8 (não roda sozinho).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Conta o que seria reescrito, sem UPDATE.",
    )
    parser.add_argument(
        "--decrypt",
        action="store_true",
        help="Rollback: restaura colunas em claro. A chave precisa continuar definida.",
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="Aplica migrations/005_field_encryption.sql antes do backfill.",
    )
    args = parser.parse_args(argv)
    _confirm_or_exit()

    from app.security.field_backfill import (
        backfill_enrollments,
        backfill_last_vitals,
        backfill_wearable_readings,
    )
    from app.security.field_crypto import FieldCryptoError, describe_status
    from app.services.durable_readings import database_url, get_engine, redact_database_url

    if not database_url():
        print("DATABASE_URL / OPERATIONAL_DATABASE_URL ausente. Nada feito.", file=sys.stderr)
        return 2
    try:
        print(describe_status())
    except FieldCryptoError as exc:
        print(f"Chave inválida: {exc}", file=sys.stderr)
        return 2

    engine = get_engine()
    if engine is None:
        print("Engine indisponível. Nada feito.", file=sys.stderr)
        return 2
    print(f"Banco: {redact_database_url(database_url())}")
    if args.dry_run and args.apply_schema:
        print("--dry-run não aplica o schema 005.", file=sys.stderr)

    try:
        if args.apply_schema and not args.dry_run:
            _apply_schema(engine)
            print(f"Schema aplicado: {SCHEMA.name}")
        readings = backfill_wearable_readings(
            engine, decrypt=args.decrypt, dry_run=args.dry_run
        )
        enrollments = backfill_enrollments(
            engine, decrypt=args.decrypt, dry_run=args.dry_run
        )
        vitals = backfill_last_vitals(engine, decrypt=args.decrypt, dry_run=args.dry_run)
    except FieldCryptoError as exc:
        print(f"Backfill interrompido: {exc}", file=sys.stderr)
        return 1
    mode = "dry-run" if args.dry_run else ("decrypt" if args.decrypt else "encrypt")
    print(f"modo={mode}")
    print(f"wearable_readings: {readings}")
    print(f"enrollments: {enrollments}")
    print(f"last_vitals: {vitals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
