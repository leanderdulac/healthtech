#!/usr/bin/env python3
"""Backfill idempotente da criptografia de campos (R8).

Não roda no boot e não é chamado pelo deploy. Recusa executar sem
``BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes``.

Exemplos (valores de chave só no ambiente, nunca neste arquivo):

    # conta o que mudaria, sem gravar e sem aplicar schema
    BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \\
    FIELD_ENCRYPTION_KEY="$DEK" FIELD_BLIND_INDEX_KEY="$BIK" \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/backfill_field_encryption.py --dry-run

    # só as colunas da 005. Não reescreve linhas.
    BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/backfill_field_encryption.py --apply-schema

    # reescreve em lotes (padrão 500, um commit por lote). Não mexe no schema.
    BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \\
    FIELD_ENCRYPTION_KEY="$DEK" FIELD_BLIND_INDEX_KEY="$BIK" \\
    FIELD_ENCRYPTION_KEY_ID=v1 \\
    DATABASE_URL="$DATABASE_URL" \\
    python scripts/backfill_field_encryption.py --backfill --batch-size 500

    # rollback das leituras: volta ao claro enquanto a chave ainda está no ambiente
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


def selected_actions(args) -> tuple[bool, bool]:
    """(aplicar 005, reescrever linhas). As duas coisas não compartilham transação.

    ``--apply-schema`` sozinho não cifra. ``--backfill`` / ``--decrypt`` /
    ``--dry-run`` não aplicam schema. Sem nenhum dos dois, o padrão é o
    backfill (retomável). ``--dry-run`` nunca aplica schema.
    """
    schema = bool(args.apply_schema) and not bool(args.dry_run)
    explicit_data = bool(args.backfill or args.decrypt or args.dry_run)
    if args.apply_schema and not explicit_data:
        return schema, False
    return schema, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill da criptografia R8 (não roda sozinho).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Conta o que seria reescrito, sem UPDATE e sem aplicar schema.",
    )
    parser.add_argument(
        "--decrypt",
        action="store_true",
        help="Rollback: restaura colunas em claro. A chave precisa continuar definida.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Reescreve linhas em lotes. Não aplica o schema 005.",
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="Aplica migrations/005_field_encryption.sql e para. Não reescreve linhas.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Linhas por commit (padrão 500).",
    )
    args = parser.parse_args(argv)
    _confirm_or_exit()
    apply_schema, run_backfill = selected_actions(args)

    from app.security.field_backfill import (
        backfill_enrollments,
        backfill_last_vitals,
        backfill_overrides,
        backfill_wearable_readings,
    )
    from app.security.field_crypto import FieldCryptoError, describe_status
    from app.services.durable_readings import database_url, get_engine, redact_database_url

    if not database_url():
        print("DATABASE_URL / OPERATIONAL_DATABASE_URL ausente. Nada feito.", file=sys.stderr)
        return 2
    if run_backfill:
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
        if apply_schema:
            _apply_schema(engine)
            print(f"Schema aplicado: {SCHEMA.name}")
        if not run_backfill:
            return 0
        common = {
            "decrypt": args.decrypt,
            "dry_run": args.dry_run,
            "batch_size": args.batch_size,
        }
        readings = backfill_wearable_readings(engine, **common)
        enrollments = backfill_enrollments(engine, **common)
        vitals = backfill_last_vitals(engine, **common)
        overrides = backfill_overrides(engine, **common)
    except FieldCryptoError as exc:
        print(f"Backfill interrompido: {exc}", file=sys.stderr)
        return 1
    mode = "dry-run" if args.dry_run else ("decrypt" if args.decrypt else "encrypt")
    print(f"modo={mode} batch_size={args.batch_size}")
    print(f"wearable_readings: {readings}")
    print(f"enrollments: {enrollments}")
    print(f"last_vitals: {vitals}")
    print(f"device_patient_overrides: {overrides}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
