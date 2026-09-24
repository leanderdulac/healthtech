"""Engines de teste para o store durável (SQLite e PostgreSQL real)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

POSTGRES_URL = os.environ.get(
    "WEARABLE_TEST_POSTGRES_URL",
    "postgresql://wearable_test:wearable_test@127.0.0.1:5432/wearable_test",
)


def postgres_available(url: str = POSTGRES_URL) -> bool:
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def make_sqlite_engine(path: Path) -> Engine:
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def make_postgres_engine(url: str = POSTGRES_URL) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=4)


def peek_engine() -> Optional[Engine]:
    """Lê o engine injetado sem criar um novo a partir de DATABASE_URL."""
    from src.ops import operational_patients

    return getattr(operational_patients, "_engine", None)


def unset_engine(*, restore: Optional[Engine] = None) -> None:
    """Troca o engine global sem dispose do anterior (evita matar a suíte)."""
    from src.ops import operational_patients

    operational_patients.set_engine(restore)


def activate_engine(engine: Engine) -> Optional[Engine]:
    from app.services import durable_readings, telemetry_store
    from src.ops import operational_patients

    previous = peek_engine()
    operational_patients.set_engine(engine)
    durable_readings.apply_schema(engine)
    telemetry_store.clear_all()
    return previous


def deactivate_engine(
    engine: Optional[Engine] = None,
    restore: Optional[Engine] = None,
) -> None:
    from app.services import telemetry_store

    try:
        telemetry_store.clear_all()
    except Exception:
        pass
    unset_engine(restore=restore)
    if engine is not None and engine is not restore:
        try:
            engine.dispose()
        except Exception:
            pass
