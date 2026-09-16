"""Leitura do cadastro operacional no PostgreSQL (Cloud SQL).

Não substitui BigQuery. Sem DATABASE_URL, as rotas respondem 503.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_engine = None


class OperationalDbUnavailable(RuntimeError):
    """DATABASE_URL ausente ou Postgres inalcançável."""


def _database_url() -> str:
    return (os.getenv("DATABASE_URL") or os.getenv("OPERATIONAL_DATABASE_URL") or "").strip()


def get_engine():
    global _engine
    url = _database_url()
    if not url:
        return None
    if _engine is None:
        from sqlalchemy import create_engine

        connect_args: Dict[str, Any] = {}
        if (
            url.startswith("postgresql")
            and "sslmode=" not in url
            and "/cloudsql/" not in url
            and "localhost" not in url
            and "127.0.0.1" not in url
        ):
            connect_args["sslmode"] = "require"
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            connect_args=connect_args,
        )
    return _engine


def reset_engine() -> None:
    """Uso em testes."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def _row_to_patient(row: Any) -> Dict[str, Any]:
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    programs = mapping.get("programs") or []
    diseases = mapping.get("diseases") or []
    if not isinstance(programs, list):
        programs = list(programs)
    if not isinstance(diseases, list):
        diseases = list(diseases)
    return {
        "patient_id": mapping.get("patient_id"),
        "display_name": mapping.get("display_name"),
        "phone": mapping.get("phone"),
        "caregiver_phone": mapping.get("caregiver_phone"),
        "programs": programs,
        "diseases": diseases,
        "isolation_social": bool(mapping.get("isolation_social")),
        "is_demo": bool(mapping.get("is_demo")),
        "municipality_id": mapping.get("municipality_id"),
        "ubs_id": mapping.get("ubs_id"),
        "created_at": mapping.get("created_at").isoformat() if mapping.get("created_at") else None,
        "updated_at": mapping.get("updated_at").isoformat() if mapping.get("updated_at") else None,
    }


_LIST_SQL = """
SELECT patient_id, display_name, phone, caregiver_phone, programs, diseases,
       isolation_social, is_demo, municipality_id, ubs_id, created_at, updated_at
FROM enrollments
ORDER BY updated_at DESC
LIMIT :limit OFFSET :offset
"""

_COUNT_SQL = "SELECT COUNT(*) AS n FROM enrollments"

_GET_SQL = """
SELECT patient_id, display_name, phone, caregiver_phone, programs, diseases,
       isolation_social, is_demo, municipality_id, ubs_id, created_at, updated_at
FROM enrollments
WHERE patient_id = :patient_id
"""


def list_patients(limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    engine = get_engine()
    if engine is None:
        raise OperationalDbUnavailable("DATABASE_URL não configurada")
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            total = int(conn.execute(text(_COUNT_SQL)).scalar_one())
            rows = conn.execute(
                text(_LIST_SQL),
                {"limit": int(limit), "offset": int(offset)},
            ).fetchall()
        return [_row_to_patient(r) for r in rows], total
    except OperationalDbUnavailable:
        raise
    except Exception as exc:
        logger.warning("Falha ao listar pacientes operacionais: %s", exc)
        raise OperationalDbUnavailable(str(exc)) from exc


def get_patient(patient_id: str) -> Optional[Dict[str, Any]]:
    engine = get_engine()
    if engine is None:
        raise OperationalDbUnavailable("DATABASE_URL não configurada")
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            row = conn.execute(text(_GET_SQL), {"patient_id": patient_id}).fetchone()
        return _row_to_patient(row) if row else None
    except OperationalDbUnavailable:
        raise
    except Exception as exc:
        logger.warning("Falha ao buscar paciente operacional %s: %s", patient_id, exc)
        raise OperationalDbUnavailable(str(exc)) from exc
