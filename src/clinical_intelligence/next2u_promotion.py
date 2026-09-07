"""
Promoção por estrelas e lookup na matriz expandida Next2U (971 padrões).

Regras (documento §4):
  ★  baixo: mantém ★
     moderado: sem confirmação/persistência mantém ★;
               com doença OU medicamento + confirmação/persistência → ★★
     alto/crítico: confirmação/persistência → ★★;
                   doença OU medicamento + progressão clínica → ★★★
  ★★ baixo: mantém ★★
     moderado: mantém ★★; doença OU medicamento + progressão → ★★★
     alto/crítico: sem confirmação mantém ★★;
                   doença OU medicamento + (confirmação OU persistência OU progressão) → ★★★
  ★★★ sempre ★★★; confirmação técnica não atrasa ação.

Isolamento social NÃO promove estrela (só rota operacional).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.clinical_intelligence.next2u_context import (
    RULE_TO_NEXT2U,
    PatientContext,
    concordance,
    hospitalization_score,
    risk_band,
)

STAR_TO_SEVERITY = {1: "leve", 2: "moderado", 3: "critico"}
SEVERITY_TO_STAR = {"leve": 1, "moderado": 2, "critico": 3, "none": 0}

CARE_PATHWAY = {
    1: {
        "nurse": "Vigilância ampliada na plataforma e acompanhamento das próximas medições.",
        "acs": "Visita domiciliar em até 1 semana.",
        "acs_hours": 168,
    },
    2: {
        "nurse": "Contatar paciente/cuidador, perguntar por sintomas e ordenar visita.",
        "acs": "Visita domiciliar e conferência dos dados em até 48 horas.",
        "acs_hours": 48,
    },
    3: {
        "nurse": (
            "Contato imediato com paciente/cuidador e acionamento prioritário "
            "do agente comunitário de saúde."
        ),
        "acs": "Conferência domiciliar em até 4 horas, no mesmo dia do alerta.",
        "acs_hours": 4,
    },
}

DEFAULT_CATALOG = Path("data/models/next2u_expanded_matrix.json")


@lru_cache(maxsize=1)
def load_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path) if path else DEFAULT_CATALOG
    if not p.exists():
        return {"patterns": [], "n_expanded_patterns": 0}
    return json.loads(p.read_text(encoding="utf-8"))


def promote_stars(
    base_stars: int,
    band: str,
    *,
    disease_or_med: bool,
    confirmation: bool,
    progression: bool,
) -> int:
    """Devolve 1, 2 ou 3. Isolamento social não entra aqui."""
    if base_stars >= 3:
        return 3

    if base_stars == 1:
        if band == "baixo":
            return 1
        if band == "moderado":
            if disease_or_med and confirmation:
                return 2
            return 1
        # alto / critico
        if disease_or_med and progression:
            return 3
        if confirmation:
            return 2
        return 1

    # base ★★
    if band == "baixo":
        return 2
    if band == "moderado":
        if disease_or_med and progression:
            return 3
        return 2
    # alto / critico
    if disease_or_med and (confirmation or progression):
        return 3
    return 2


def lookup_pattern(
    base_id: int,
    band: str,
    stars: int,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    cat = catalog or load_catalog()
    cands = [
        p
        for p in cat.get("patterns", [])
        if p.get("base_id") == base_id
        and p.get("risk_band") == band
        and int(p.get("stars") or 0) == stars
    ]
    if cands:
        return cands[0]
    # fallback: mesmo base_id e mesmas estrelas
    cands = [
        p
        for p in cat.get("patterns", [])
        if p.get("base_id") == base_id and int(p.get("stars") or 0) == stars
    ]
    return cands[0] if cands else None


def apply_next2u(
    result: Any,
    ctx: PatientContext,
    primary_rule_id: Optional[str] = None,
) -> Any:
    """Enriquece AlertMatrixResult com ramificação Next2U. Não cria alerta novo."""
    if not getattr(result, "is_true_alert", False):
        result.hospitalization_score = hospitalization_score(ctx)
        result.risk_band = risk_band(result.hospitalization_score)
        result.stars = 0
        result.next2u_id = None
        return result

    rid = primary_rule_id or getattr(result, "primary_rule_id", None)
    profile_id, base_id = RULE_TO_NEXT2U.get(rid or "", (1, 1))
    base_stars = SEVERITY_TO_STAR.get(getattr(result, "max_severity", "leve"), 1)
    d_ok, m_ok = concordance(ctx, profile_id)
    disease_or_med = d_ok or m_ok
    score = hospitalization_score(ctx)
    band = risk_band(score)
    stars = promote_stars(
        base_stars,
        band,
        disease_or_med=disease_or_med,
        confirmation=bool(ctx.confirmation_or_persistence),
        progression=bool(ctx.clinical_progression),
    )
    pattern = lookup_pattern(base_id, band, stars)
    result.hospitalization_score = score
    result.risk_band = band
    result.stars = stars
    result.max_severity = STAR_TO_SEVERITY[stars]
    result.disease_concordant = d_ok
    result.med_concordant = m_ok
    result.care_pathway = dict(CARE_PATHWAY[stars])
    if ctx.social_isolation:
        result.care_pathway["social_note"] = (
            "Isolamento social altera a urgência de busca ativa, "
            "sem promover estrela nem simular segundo sinal fisiológico."
        )
    if pattern:
        result.next2u_id = pattern["id"]
        result.primary_alert_name = pattern["suggested_name"]
        extra = (
            f" | Next2U {pattern['id']} ★{stars} risco={band} "
            f"escore={score} {pattern['contextual_rule']}"
        )
        result.explanation = (getattr(result, "explanation", "") or "") + extra
    else:
        result.next2u_id = f"{base_id:03d}.x"
        result.explanation = (
            (getattr(result, "explanation", "") or "")
            + f" | Next2U base={base_id} ★{stars} risco={band} escore={score}"
        )
    return result
