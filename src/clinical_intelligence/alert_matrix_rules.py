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
            # Derived
            "map_approx": (f(self.pas, 120) + 2 * f(self.pad, 80)) / 3.0,
            "pulse_pressure": f(self.pas, 120) - f(self.pad, 80),
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
    """Retorna lista ordenada de regras (críticas primeiro por prioridade de match)."""
    R: List[Dict[str, Any]] = []

    def add(rid, cat, sev, name, pred):
        R.append(
            {
                "rule_id": rid,
                "category": cat,
                "severity": sev,
                "name": name,
                "predicate": pred,
            }
        )

    # --- 1. PA elevada ---
    add(
        "pa_elev_1",
        "pa_alta",
        "leve",
        "Possível elevação pressórica associada a taquicardia leve",
        lambda v: _in(v.pas, 140, 159) and _in(v.pad, 90, 99) and _in(v.hr, 91, 110),
    )
    add(
        "pa_elev_2",
        "pa_alta",
        "moderado",
        "Possível descompensação hipertensiva com taquicardia",
        lambda v: _in(v.pas, 160, 179) and _in(v.pad, 100, 109) and _in(v.hr, 111, 130),
    )
    add(
        "pa_elev_3",
        "pa_alta",
        "critico",
        "Possível crise hipertensiva associada a taquicardia",
        lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _ge(v.hr, 111),
    )
    add(
        "pa_elev_4",
        "pa_alta",
        "critico",
        "Possível crise hipertensiva com comprometimento cardiorrespiratório",
        lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _le(v.spo2, 93),
    )
    add(
        "pa_elev_5",
        "pa_alta",
        "critico",
        "Possível descompensação hipertensiva associada a quadro febril agudo",
        lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _ge(v.temp_c, 38.1),
    )
    add(
        "pa_elev_6",
        "pa_alta",
        "critico",
        "Possível descompensação cardiovascular e metabólica",
        lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _ge(v.glucose_mgdl, 250),
    )

    # --- 2. PA baixa ---
    add(
        "pa_baixa_1",
        "pa_baixa",
        "leve",
        "Possível hipotensão associada a taquicardia leve",
        lambda v: _in(v.pas, 101, 110) and _in(v.hr, 91, 110),
    )
    add(
        "pa_baixa_2",
        "pa_baixa",
        "moderado",
        "Possível hipovolemia ou instabilidade circulatória",
        lambda v: _in(v.pas, 91, 100) and _in(v.hr, 111, 130),
    )
    add(
        "pa_baixa_3",
        "pa_baixa",
        "critico",
        "Possível infecção com repercussão hemodinâmica",
        lambda v: _in(v.pas, 91, 100) and _ge(v.hr, 111) and _ge(v.temp_c, 38.1),
    )
    add(
        "pa_baixa_4",
        "pa_baixa",
        "critico",
        "Possível deterioração cardiorrespiratória",
        lambda v: _in(v.pas, 91, 100) and _ge(v.hr, 111) and _le(v.spo2, 93),
    )
    add(
        "pa_baixa_5",
        "pa_baixa",
        "critico",
        "Possível instabilidade hemodinâmica",
        lambda v: _le(v.pas, 90) and _ge(v.hr, 111),
    )
    add(
        "pa_baixa_6",
        "pa_baixa",
        "critico",
        "Possível hipotensão associada a hipoxemia",
        lambda v: _le(v.pas, 90) and _le(v.spo2, 91),
    )

    # --- 3. SpO2 ---
    add(
        "spo2_1",
        "spo2",
        "leve",
        "Possível dessaturação leve",
        lambda v: _in(v.spo2, 95, 96),
    )
    add(
        "spo2_2",
        "spo2",
        "moderado",
        "Possível dessaturação moderada",
        lambda v: _in(v.spo2, 93, 94),
    )
    add(
        "spo2_3",
        "spo2",
        "moderado",
        "Possível comprometimento respiratório com resposta cardíaca compensatória",
        lambda v: _in(v.spo2, 93, 94) and _in(v.hr, 111, 130),
    )
    add(
        "spo2_4",
        "spo2",
        "critico",
        "Possível infecção com repercussão sistêmica",
        lambda v: _in(v.spo2, 92, 93) and _ge(v.hr, 111) and _ge(v.temp_c, 38.1),
    )
    add(
        "spo2_5",
        "spo2",
        "critico",
        "Possível hipoxemia importante",
        lambda v: _le(v.spo2, 91),
    )
    add(
        "spo2_6",
        "spo2",
        "critico",
        "Possível comprometimento cardiorrespiratório agudo",
        lambda v: _le(v.spo2, 91) and _ge(v.hr, 111),
    )
    add(
        "spo2_7",
        "spo2",
        "critico",
        "Possível infecção aguda com hipoxemia",
        lambda v: _le(v.spo2, 91) and _ge(v.temp_c, 38.1),
    )

    # --- 4. Temperatura ---
    add(
        "temp_1",
        "temperatura",
        "leve",
        "Possível estado febril com resposta cardíaca leve",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.hr, 91, 110),
    )
    add(
        "temp_2",
        "temperatura",
        "moderado",
        "Possível estado febril associado a taquicardia",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.hr, 111, 130),
    )
    add(
        "temp_3",
        "temperatura",
        "critico",
        "Possível infecção com deterioração clínica",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.hr, 111) and _le(v.spo2, 93),
    )
    add(
        "temp_4",
        "temperatura",
        "critico",
        "Possível infecção com instabilidade hemodinâmica",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.hr, 111) and _le(v.pas, 100),
    )
    add(
        "temp_5",
        "temperatura",
        "critico",
        "Possível febre alta com repercussão cardiovascular",
        lambda v: _ge(v.temp_c, 39.1) and _ge(v.hr, 111),
    )
    add(
        "temp_6",
        "temperatura",
        "critico",
        "Possível infecção grave ou desidratação com instabilidade clínica",
        lambda v: _ge(v.temp_c, 39.1)
        and _ge(v.hr, 111)
        and (_le(v.pas, 100) or _le(v.spo2, 93)),
    )
    add(
        "temp_7",
        "temperatura",
        "critico",
        "Possível hipotermia com instabilidade fisiológica",
        lambda v: _le(v.temp_c, 35.0) and (_le(v.hr, 50) or _le(v.pas, 100)),
    )

    # --- 5. Hipoglicemia ---
    add(
        "hypo_1",
        "hipoglicemia",
        "moderado",
        "Possível hipoglicemia",
        lambda v: _in(v.glucose_mgdl, 54, 69),
    )
    add(
        "hypo_2",
        "hipoglicemia",
        "moderado",
        "Possível hipoglicemia com resposta adrenérgica",
        lambda v: _in(v.glucose_mgdl, 54, 69) and _ge(v.hr, 111),
    )
    add(
        "hypo_3",
        "hipoglicemia",
        "critico",
        "Possível hipoglicemia associada a instabilidade hemodinâmica",
        lambda v: _in(v.glucose_mgdl, 54, 69) and _le(v.pas, 100),
    )
    add(
        "hypo_4",
        "hipoglicemia",
        "critico",
        "Possível hipoglicemia clinicamente significativa",
        lambda v: _le(v.glucose_mgdl, 53.999) if v.glucose_mgdl is not None else False,
    )
    add(
        "hypo_5",
        "hipoglicemia",
        "critico",
        "Possível hipoglicemia grave",
        lambda v: (v.glucose_mgdl is not None and v.glucose_mgdl < 54)
        and (
            v.consciousness_altered
            or _hr_elevated_any(v)
            or _le(v.hr, 50)
            or _le(v.pas, 100)
            or _ge(v.pas, 140)
        ),
    )

    # --- 6. Hiperglicemia ---
    add(
        "hyper_1",
        "hiperglicemia",
        "leve",
        "Possível hiperglicemia acima da meta",
        lambda v: _in(v.glucose_mgdl, 181, 249),
    )
    add(
        "hyper_2",
        "hiperglicemia",
        "moderado",
        "Possível hiperglicemia importante",
        lambda v: _in(v.glucose_mgdl, 250, 399),
    )
    add(
        "hyper_3",
        "hiperglicemia",
        "moderado",
        "Possível hiperglicemia associada a quadro infeccioso",
        lambda v: _in(v.glucose_mgdl, 250, 399) and _ge(v.temp_c, 38.1),
    )
    add(
        "hyper_4",
        "hiperglicemia",
        "critico",
        "Possível descompensação metabólica associada a infecção",
        lambda v: _in(v.glucose_mgdl, 250, 399)
        and _ge(v.temp_c, 38.1)
        and _ge(v.hr, 111),
    )
    add(
        "hyper_5",
        "hiperglicemia",
        "critico",
        "Possível crise hiperglicêmica com desidratação ou instabilidade circulatória",
        lambda v: _in(v.glucose_mgdl, 250, 399) and _ge(v.hr, 111) and _le(v.pas, 100),
    )
    add(
        "hyper_6",
        "hiperglicemia",
        "critico",
        "Possível hiperglicemia severa",
        lambda v: _ge(v.glucose_mgdl, 400) and (v.glucose_mgdl is not None and v.glucose_mgdl < 600),
    )
    add(
        "hyper_7",
        "hiperglicemia",
        "critico",
        "Possível estado hiperglicêmico hiperosmolar",
        lambda v: _ge(v.glucose_mgdl, 600),
    )

    # --- 7. FC ---
    add(
        "fc_1",
        "fc",
        "moderado",
        "Possível bradicardia relativa",
        lambda v: _in(v.hr, 41, 50),
    )
    add(
        "fc_2",
        "fc",
        "critico",
        "Possível bradicardia com repercussão hemodinâmica",
        lambda v: _in(v.hr, 41, 50) and _le(v.pas, 100),
    )
    add(
        "fc_3",
        "fc",
        "critico",
        "Possível bradicardia associada a dessaturação",
        lambda v: _in(v.hr, 41, 50) and _le(v.spo2, 93),
    )
    add(
        "fc_4",
        "fc",
        "critico",
        "Possível bradicardia importante",
        lambda v: _le(v.hr, 40),
    )
    add(
        "fc_5",
        "fc",
        "leve",
        "Possível taquicardia persistente",
        lambda v: _in(v.hr, 111, 130),
    )
    add(
        "fc_6",
        "fc",
        "critico",
        "Possível taquicardia importante",
        lambda v: _ge(v.hr, 131),
    )
    add(
        "fc_7",
        "fc",
        "critico",
        "Possível deterioração sistêmica ou cardiovascular",
        lambda v: _ge(v.hr, 131) and _pa_or_spo2_or_temp_abnormal(v),
    )

    # --- 8. Passos / sono ---
    add(
        "func_1",
        "funcional",
        "leve",
        "Possível redução funcional associada à piora do sono",
        lambda v: _ge(v.steps_drop_pct, 40) and _ge(v.sleep_worsen_pct, 30),
    )
    add(
        "func_2",
        "funcional",
        "moderado",
        "Possível estresse fisiológico com redução funcional",
        lambda v: _ge(v.steps_drop_pct, 40)
        and _ge(v.sleep_worsen_pct, 30)
        and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "func_3",
        "funcional",
        "moderado",
        "Possível comprometimento respiratório associado à redução funcional",
        lambda v: _ge(v.steps_drop_pct, 50) and _ge(v.spo2_drop_points, 3),
    )
    add(
        "func_4",
        "funcional",
        "critico",
        "Possível deterioração clínica aguda",
        lambda v: (
            _ge(v.steps_drop_pct, 40) or _ge(v.sleep_worsen_pct, 30)
        )
        and (
            _ge(v.temp_c, 38.1)
            or _le(v.spo2, 93)
            or _le(v.pas, 100)
            or _ge(v.hr, 111)
        ),
    )
    add(
        "func_5",
        "funcional",
        "moderado",
        "Possível estresse cardiovascular associado à piora do sono",
        lambda v: _ge(v.sleep_worsen_pct, 30)
        and _in(v.pas, 140, 159)
        and _in(v.pad, 90, 99)
        and _in(v.hr, 91, 110),
    )
    add(
        "func_6",
        "funcional",
        "moderado",
        "Possível descompensação cardiovascular associada à piora do sono",
        lambda v: _ge(v.sleep_worsen_pct, 30)
        and (
            (_in(v.pas, 160, 179) and _in(v.pad, 100, 109))
            or _in(v.hr, 111, 130)
        ),
    )

    return R


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

    def evaluate(self, vitals: VitalSnapshot) -> AlertMatrixResult:
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
            return AlertMatrixResult(
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
                ),
            )

        rank = AlertMatrixResult.SEVERITY_RANK
        best = max(hits, key=lambda h: rank.get(h.severity, 0))
        return AlertMatrixResult(
            hits=hits,
            max_severity=best.severity,
            is_true_alert=True,
            is_false_positive_candidate=False,
            primary_alert_name=best.name,
            primary_rule_id=best.rule_id,
            explanation=f"{len(hits)} regra(s); principal={best.rule_id} ({best.severity})",
        )

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
