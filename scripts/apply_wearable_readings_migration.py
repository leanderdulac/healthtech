#!/usr/bin/env python3
"""Aplica migrations/001_wearable_readings.sql no Postgres operacional.

Reusa DATABASE_URL / OPERATIONAL_DATABASE_URL (mesmo Cloud SQL de enrollments).
Não imprime o valor da URL.

    python scripts/apply_wearable_readings_migration.py
    cd saude_responsiva_secure && PYTHONPATH=. python -m app.services.durable_readings
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
for candidate in (SECURE, ROOT):
    path = str(candidate)
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.durable_readings import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
