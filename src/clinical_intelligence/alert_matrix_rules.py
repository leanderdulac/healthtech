"""
Matriz de cruzamentos clínicos → alertas com prioridade.

Fonte: regras clínicas Leve | Moderado | Crítico para PA, SpO2, temp,
glicemia, FC, passos e sono.

O motor de regras é a **fonte de verdade** para rótulos de treino e para
suprimir falsos positivos (sinais anômalos isolados que NÃO batem em nenhuma
regra multi-critério não geram alerta verdadeiro).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class VitalSnapshot:
    """Estado fisiológico pontual (unidades clínicas usuais)."""

    # Pressão
    pas: Optional[float] = None  # sistólica mmHg
    pad: Optional[float] = None  # diastólica mmHg
    # Cardio / resp
    hr: Optional[float] = None  # bpm
    spo2: Optional[float] = None  # %
    temp_c: Optional[float] = None  # °C
    glucose_mgdl: Optional[float] = None
    # Funcional / baseline relativo
    steps_drop_pct: Optional[float] = None  # redução % vs baseline (≥0)
    sleep_worsen_pct: Optional[float] = None  # piora % do sono (≥0)
    hr_baseline_rise: Optional[float] = None  # Δ bpm vs FC basal
    spo2_drop_points: Optional[float] = None  # queda absoluta de SpO2 vs baseline
    consciousness_altered: bool = False  # hipoglicemia grave
    # Basal / persistência / contexto de medida (Next2U)
    pas_basal: Optional[float] = None
    pad_basal: Optional[float] = None
    spo2_basal: Optional[float] = None
    temp_basal: Optional[float] = None
    glucose_basal: Optional[float] = None
    glucose_prev: Optional[float] = None
    consecutive_valid: int = 1
    rest: bool = False
    fasting: bool = False
    sleep_hours: Optional[float] = None
    steps_drop_days: int = 0
    steps_interrupted: bool = False
    no_steps_rest_of_active: bool = False

    def pas_rise(self) -> Optional[float]:
        if self.pas is None or self.pas_basal is None:
            return None
        return self.pas - self.pas_basal

    def pad_rise(self) -> Optional[float]:
        if self.pad is None or self.pad_basal is None:
            return None
        return self.pad - self.pad_basal

    def pas_drop(self) -> Optional[float]:
        r = self.pas_rise()
        return None if r is None else -r

    def temp_rise(self) -> Optional[float]:
        if self.temp_c is None or self.temp_basal is None:
            return None
        return self.temp_c - self.temp_basal

    def temp_drop(self) -> Optional[float]:
        r = self.temp_rise()
        return None if r is None else -r

    def glucose_delta(self) -> Optional[float]:
        if self.glucose_mgdl is None or self.glucose_prev is None:
            return None
        return self.glucose_mgdl - self.glucose_prev

    def glucose_vs_basal(self) -> Optional[float]:
        if self.glucose_mgdl is None or self.glucose_basal is None:
            return None
        return self.glucose_mgdl - self.glucose_basal

    def to_feature_dict(self) -> Dict[str, float]:
        def f(v: Optional[float], default: float = 0.0) -> float:
            return float(v) if v is not None else default

        return {
            "pas": f(self.pas, 120.0),
            "pad": f(self.pad, 80.0),
            "hr": f(self.hr, 70.0),
            "spo2": f(self.spo2, 98.0),
            "temp_c": f(self.temp_c, 36.5),
            "glucose_mgdl": f(self.glucose_mgdl, 100.0),
            "steps_drop_pct": f(self.steps_drop_pct, 0.0),
            "sleep_worsen_pct": f(self.sleep_worsen_pct, 0.0),
            "hr_baseline_rise": f(self.hr_baseline_rise, 0.0),
            "spo2_drop_points": f(self.spo2_drop_points, 0.0),
            "consciousness_altered": 1.0 if self.consciousness_altered else 0.0,
            "map_approx": (f(self.pas, 120) + 2 * f(self.pad, 80)) / 3.0,
            "pulse_pressure": f(self.pas, 120) - f(self.pad, 80),
            "consecutive_valid": float(self.consecutive_valid or 1),
            "rest": 1.0 if self.rest else 0.0,
            "fasting": 1.0 if self.fasting else 0.0,
            "steps_interrupted": 1.0 if self.steps_interrupted else 0.0,
            "sleep_hours": f(self.sleep_hours, 8.0),
            "steps_drop_days": float(self.steps_drop_days or 0),
            "pas_rise_vs_basal": f(self.pas_rise(), 0.0),
            "pas_drop_vs_basal": f(self.pas_drop(), 0.0),
            "glucose_delta": f(self.glucose_delta(), 0.0),
        }


@dataclass
class AlertHit:
    rule_id: str
    category: str
    severity: str  # leve | moderado | critico
    name: str
    matched: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AlertMatrixResult:
    """Resultado da avaliação da matriz."""

    hits: List[AlertHit] = field(default_factory=list)
    max_severity: str = "none"  # none | leve | moderado | critico
    is_true_alert: bool = False
    is_false_positive_candidate: bool = False
    primary_alert_name: Optional[str] = None
    primary_rule_id: Optional[str] = None
    explanation: str = ""
    hospitalization_score: int = 0
    risk_band: str = "baixo"
    stars: int = 0
    next2u_id: Optional[str] = None
    care_pathway: Optional[Dict[str, Any]] = None
    disease_concordant: bool = False
    med_concordant: bool = False

    SEVERITY_RANK = {"none": 0, "leve": 1, "moderado": 2, "critico": 3}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": [h.to_dict() for h in self.hits],
            "max_severity": self.max_severity,
            "is_true_alert": self.is_true_alert,
            "is_false_positive_candidate": self.is_false_positive_candidate,
            "primary_alert_name": self.primary_alert_name,
            "primary_rule_id": self.primary_rule_id,
            "explanation": self.explanation,
            "hospitalization_score": self.hospitalization_score,
            "risk_band": self.risk_band,
            "stars": self.stars,
            "next2u_id": self.next2u_id,
            "care_pathway": self.care_pathway,
            "disease_concordant": self.disease_concordant,
            "med_concordant": self.med_concordant,
        }


def _in(v: Optional[float], lo: float, hi: float) -> bool:
    return v is not None and lo <= v <= hi


def _ge(v: Optional[float], thr: float) -> bool:
    return v is not None and v >= thr


def _le(v: Optional[float], thr: float) -> bool:
    return v is not None and v <= thr


def _hr_elevated_any(v: VitalSnapshot) -> bool:
    return _ge(v.hr, 91)


def _pa_or_spo2_or_temp_abnormal(v: VitalSnapshot) -> bool:
    return (
        _ge(v.pas, 140)
        or _ge(v.pad, 90)
        or _le(v.pas, 100)
        or _le(v.spo2, 96)
        or _ge(v.temp_c, 38.1)
        or _le(v.temp_c, 35.0)
    )


# ---------------------------------------------------------------------------
# Regras — cada predicado (VitalSnapshot) -> bool
# ---------------------------------------------------------------------------

def _build_rules() -> List[Dict[str, Any]]:
    """158 alertas-base Next2U (predicados fisiológicos)."""
    from src.clinical_intelligence.next2u_bases import build_rules as _next2u_rules

    return _next2u_rules()




ALERT_RULES: List[Dict[str, Any]] = _build_rules()


def rules_catalog() -> List[Dict[str, str]]:
    """Catálogo serializável (sem predicates)."""
    return [
        {
            "rule_id": r["rule_id"],
            "category": r["category"],
            "severity": r["severity"],
            "name": r["name"],
        }
        for r in ALERT_RULES
    ]


class AlertMatrixEngine:
    """Avalia um VitalSnapshot contra toda a matriz de cruzamentos."""

    def evaluate(self, vitals: VitalSnapshot, context: Any = None) -> AlertMatrixResult:
        hits: List[AlertHit] = []
        for rule in ALERT_RULES:
            try:
                if rule["predicate"](vitals):
                    hits.append(
                        AlertHit(
                            rule_id=rule["rule_id"],
                            category=rule["category"],
                            severity=rule["severity"],
                            name=rule["name"],
                        )
                    )
            except Exception:
                continue

        if not hits:
            fp_candidate = self._looks_anomalous_but_unmatched(vitals)
            empty = AlertMatrixResult(
                hits=[],
                max_severity="none",
                is_true_alert=False,
                is_false_positive_candidate=fp_candidate,
                explanation=(
                    "Nenhuma regra da matriz acionada"
                    + (
                        "; padrões isolados tratados como falso positivo potencial"
                        if fp_candidate
                        else "; vitais dentro de faixa de estabilidade"
                    )
                    + (
                        "; escore/doença/medicamento isolados não geram alerta"
                        if context is not None
                        else ""
                    )
                ),
            )
            if context is not None:
                from src.clinical_intelligence.next2u_promotion import apply_next2u

                apply_next2u(empty, context, primary_rule_id=None)
            return empty

        rank = AlertMatrixResult.SEVERITY_RANK
        best = max(hits, key=lambda h: rank.get(h.severity, 0))
        result = AlertMatrixResult(
            hits=hits,
            max_severity=best.severity,
            is_true_alert=True,
            is_false_positive_candidate=False,
            primary_alert_name=best.name,
            primary_rule_id=best.rule_id,
            explanation=f"{len(hits)} regra(s); principal={best.rule_id} ({best.severity})",
            stars=rank.get(best.severity, 0),
        )
        if context is not None:
            from src.clinical_intelligence.next2u_promotion import apply_next2u

            apply_next2u(result, context, primary_rule_id=best.rule_id)
        return result

    @staticmethod
    def _looks_anomalous_but_unmatched(v: VitalSnapshot) -> bool:
        """Sinais limítrofes/isolados que gerariam ruído mas não batem na matriz."""
        return any(
            [
                v.hr is not None and (100 <= v.hr <= 110 or 51 <= v.hr <= 55),
                v.spo2 is not None and 96.1 <= v.spo2 <= 97.0,
                v.pas is not None and 130 <= v.pas < 140,
                v.temp_c is not None and 37.5 <= v.temp_c < 38.1,
                v.glucose_mgdl is not None and 140 <= v.glucose_mgdl < 181,
                v.steps_drop_pct is not None and 20 <= v.steps_drop_pct < 40,
            ]
        )
