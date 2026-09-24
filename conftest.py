"""Backend opcional para a suíte: WEARABLE_TEST_DB=sqlite|postgres|memory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent
_SECURE = _ROOT / "saude_responsiva_secure"
for _path in (_SECURE, _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tests.support_wearable_db import (
    POSTGRES_URL,
    activate_engine,
    make_postgres_engine,
    make_sqlite_engine,
    postgres_available,
    unset_engine,
)


@pytest.fixture(scope="session")
def _wearable_suite_engine(tmp_path_factory):
    kind = (os.environ.get("WEARABLE_TEST_DB") or "").strip().lower()
    if kind in {"", "memory", "none"}:
        yield None
        return
    if kind in {"postgres", "postgresql"}:
        if not postgres_available():
            pytest.fail(
                f"WEARABLE_TEST_DB=postgres mas {POSTGRES_URL} está inacessível"
            )
        engine = make_postgres_engine()
    elif kind == "sqlite":
        path = tmp_path_factory.mktemp("suite") / "suite.db"
        engine = make_sqlite_engine(path)
    else:
        pytest.fail(f"WEARABLE_TEST_DB inválido: {kind}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _wearable_suite_backend(_wearable_suite_engine):
    """Reinjeta o engine da suíte em cada teste (sobrevive a reset_engine)."""
    if _wearable_suite_engine is None:
        yield None
        return
    activate_engine(_wearable_suite_engine)
    try:
        yield _wearable_suite_engine
    finally:
        unset_engine(restore=_wearable_suite_engine)
