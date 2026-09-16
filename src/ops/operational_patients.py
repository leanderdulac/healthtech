"""Leitura do cadastro operacional no PostgreSQL (Cloud SQL).

Não substitui BigQuery. Sem DATABASE_URL, as rotas respondem 503.

Listagem autorizada (Next2U gate #30 / Core #6): a restrição de
autorização (allow-list e/ou escopos territoriais) entra no WHERE
**antes** de LIMIT/OFFSET. `total` é o COUNT do conjunto já filtrado,
nunca o COUNT(*) global de enrollments.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import AbstractSet, Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_engine = None

_WILDCARD_ALLOW = frozenset({"*", "ALL", "all"})
_SELECT_COLUMNS = (
    "patient_id, display_name, phone, caregiver_phone, programs, diseases, "
    "isolation_social, is_demo, municipality_id, ubs_id, created_at, updated_at"
)
_TERRITORY_DEFINED_SQL = (
    "municipality_id IS NOT NULL AND TRIM(municipality_id) <> '' "
    "AND ubs_id IS NOT NULL AND TRIM(ubs_id) <> ''"
)
_ORDER_SQL = "ORDER BY updated_at DESC, patient_id ASC"


class OperationalDbUnavailable(RuntimeError):
    """DATABASE_URL ausente ou Postgres inalcançável."""


class InvalidTerritoryScope(ValueError):
    """Token de território malformado (municipality_id vazio)."""


@dataclass(frozen=True)
class TerritoryScope:
    """Escopo territorial solicitado pelo BFF (não é identidade profissional).

    - `ubs_id` presente → escopo de UBS (`municipality_id` + `ubs_id`).
    - `ubs_id` ausente → escopo municipal (todas as UBS daquele município).
    """

    municipality_id: str
    ubs_id: Optional[str] = None

    def __post_init__(self) -> None:
        municipality = (self.municipality_id or "").strip()
        ubs = (self.ubs_id or "").strip() or None
        if not municipality:
            raise InvalidTerritoryScope("municipality_id vazio")
        object.__setattr__(self, "municipality_id", municipality)
        object.__setattr__(self, "ubs_id", ubs)


def _database_url() -> str:
    return (os.getenv("DATABASE_URL") or os.getenv("OPERATIONAL_DATABASE_URL") or "").strip()


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    url = _database_url()
    if not url:
        return None
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


def set_engine(engine) -> None:
    """Injeta engine (testes). Sobrevive a DATABASE_URL ausente."""
    global _engine
    _engine = engine


def reset_engine() -> None:
    """Uso em testes."""
    global _engine
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None


def parse_allowed_patient_ids(raw: Optional[str]) -> Tuple[Optional[frozenset[str]], bool]:
    """Interpreta ALLOWED_PATIENT_IDS.

    Retorna `(ids, is_wildcard)`:
    - wildcard (`*` / `ALL`) → `(None, True)` — sem restrição por ID
    - lista finita → `(frozenset, False)`
    - ausente/vazio → `(frozenset(), False)` — fail-closed (nenhum ID)
    """
    text = (raw or "").strip()
    if not text:
        return frozenset(), False
    tokens = {p.strip() for p in text.split(",") if p.strip()}
    if tokens & _WILDCARD_ALLOW:
        return None, True
    return frozenset(tokens), False


def parse_territory_scopes(
    territory: Optional[Sequence[str]] = None,
    municipality_id: Optional[Sequence[str]] = None,
    ubs_id: Optional[Sequence[str]] = None,
) -> List[TerritoryScope]:
    """Converte query params em escopos territoriais (união, sem duplicata)."""
    scopes: List[TerritoryScope] = []
    seen: set[Tuple[str, Optional[str]]] = set()

    def _add(scope: TerritoryScope) -> None:
        key = (scope.municipality_id, scope.ubs_id)
        if key not in seen:
            seen.add(key)
            scopes.append(scope)

    for token in territory or ():
        raw = (token or "").strip()
        if not raw:
            continue
        if ":" in raw:
            mun, _, ubs = raw.partition(":")
            _add(TerritoryScope(mun, ubs))
        else:
            _add(TerritoryScope(raw, None))

    mun_list = [(m or "").strip() for m in (municipality_id or ()) if (m or "").strip()]
    ubs_list = [(u or "").strip() for u in (ubs_id or ())]
    if len(ubs_list) > len(mun_list):
        raise InvalidTerritoryScope(
            "ubs_id sem municipality_id correspondente (parear por índice)"
        )
    for idx, mun in enumerate(mun_list):
        ubs = ubs_list[idx] if idx < len(ubs_list) else ""
        _add(TerritoryScope(mun, ubs or None))
    return scopes


def has_authorized_constraint(
    allowed_patient_ids: Optional[AbstractSet[str]],
    territories: Optional[Sequence[TerritoryScope]],
) -> bool:
    """True se há restrição server-side (allow-list finita e/ou território)."""
    if territories:
        return True
    return allowed_patient_ids is not None and len(allowed_patient_ids) > 0


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [value] if value else []
    try:
        return list(value)
    except TypeError:
        return []


def _row_to_patient(row: Any) -> Dict[str, Any]:
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    created = mapping.get("created_at")
    updated = mapping.get("updated_at")
    return {
        "patient_id": mapping.get("patient_id"),
        "display_name": mapping.get("display_name"),
        "phone": mapping.get("phone"),
        "caregiver_phone": mapping.get("caregiver_phone"),
        "programs": _as_list(mapping.get("programs")),
        "diseases": _as_list(mapping.get("diseases")),
        "isolation_social": bool(mapping.get("isolation_social")),
        "is_demo": bool(mapping.get("is_demo")),
        "municipality_id": mapping.get("municipality_id"),
        "ubs_id": mapping.get("ubs_id"),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else updated,
    }


def _build_authorized_where(
    *,
    allowed_patient_ids: Optional[AbstractSet[str]],
    territories: Sequence[TerritoryScope],
    require_defined_territory: bool,
) -> Tuple[str, Dict[str, Any], List[str]]:
    """Monta WHERE parametrizado. Nunca interpola valores do cliente no SQL."""
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    expanding: List[str] = []

    if require_defined_territory:
        clauses.append(f"({_TERRITORY_DEFINED_SQL})")

    if allowed_patient_ids is not None:
        clauses.append("patient_id IN :allowed_ids")
        params["allowed_ids"] = list(allowed_patient_ids)
        expanding.append("allowed_ids")

    if territories:
        territory_parts: List[str] = []
        for idx, scope in enumerate(territories):
            mun_key = f"territory_mun_{idx}"
            params[mun_key] = scope.municipality_id
            if scope.ubs_id is None:
                territory_parts.append(f"municipality_id = :{mun_key}")
            else:
                ubs_key = f"territory_ubs_{idx}"
                params[ubs_key] = scope.ubs_id
                territory_parts.append(
                    f"(municipality_id = :{mun_key} AND ubs_id = :{ubs_key})"
                )
        clauses.append("(" + " OR ".join(territory_parts) + ")")

    if not clauses:
        return "", params, expanding
    return " WHERE " + " AND ".join(clauses), params, expanding


def _execute(sql: str, params: Dict[str, Any], expanding: Iterable[str]):
    from sqlalchemy import bindparam, text

    stmt = text(sql)
    expanding_names = list(expanding)
    if expanding_names:
        stmt = stmt.bindparams(
            *(bindparam(name, expanding=True) for name in expanding_names)
        )
    engine = get_engine()
    if engine is None:
        raise OperationalDbUnavailable("DATABASE_URL não configurada")
    with engine.connect() as conn:
        return conn.execute(stmt, params)


def list_patients(
    limit: int = 50,
    offset: int = 0,
    *,
    allowed_patient_ids: Optional[AbstractSet[str]] = None,
    territories: Optional[Sequence[TerritoryScope]] = None,
    require_defined_territory: bool = False,
    fail_closed_without_constraint: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """Lista enrollments.

    Quando `fail_closed_without_constraint` é True e não há allow-list finita
    nem território, devolve `([], 0)` sem COUNT(*) global.

    Allow-list vazia (`frozenset()`) também é fail-closed.
    `allowed_patient_ids is None` significa “sem filtro de ID”.
    """
    scopes = list(territories or ())
    if allowed_patient_ids is not None and len(allowed_patient_ids) == 0:
        return [], 0
    if fail_closed_without_constraint and not has_authorized_constraint(
        allowed_patient_ids, scopes
    ):
        return [], 0

    engine = get_engine()
    if engine is None:
        raise OperationalDbUnavailable("DATABASE_URL não configurada")

    where_sql, params, expanding = _build_authorized_where(
        allowed_patient_ids=allowed_patient_ids,
        territories=scopes,
        require_defined_territory=require_defined_territory,
    )
    page_params = dict(params)
    page_params["limit"] = int(limit)
    page_params["offset"] = int(offset)

    count_sql = f"SELECT COUNT(*) AS n FROM enrollments{where_sql}"
    list_sql = (
        f"SELECT {_SELECT_COLUMNS} FROM enrollments{where_sql} "
        f"{_ORDER_SQL} LIMIT :limit OFFSET :offset"
    )

    try:
        total = int(_execute(count_sql, params, expanding).scalar_one())
        rows = _execute(list_sql, page_params, expanding).fetchall()
        return [_row_to_patient(r) for r in rows], total
    except OperationalDbUnavailable:
        raise
    except Exception as exc:
        logger.warning("Falha ao listar pacientes operacionais: %s", exc)
        raise OperationalDbUnavailable(str(exc)) from exc


_GET_SQL = f"""
SELECT {_SELECT_COLUMNS}
FROM enrollments
WHERE patient_id = :patient_id
"""


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
