"""
Matriz de cruzamentos clínicos → alertas com prioridade.

Fonte clínica: PA, SpO2, temperatura, glicemia, FC, passos/sono,
infecção, desidratação e queda — com linhas de cuidado (enfermeira/ACS).

O motor de regras é a **fonte de verdade** para rótulos de treino e para
suprimir falsos positivos (sinais anômalos isolados que NÃO batem em nenhuma
regra multi-critério não geram alerta verdadeiro).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


SEVERITY_RANK = {"none": 0, "leve": 1, "moderado": 2, "critico": 3}
SEVERITY_STARS = {"leve": 1, "moderado": 2, "critico": 3}
SEVERITY_STAR_LABEL = {"leve": "★", "moderado": "★★", "critico": "★★★"}

# §12 — linhas de cuidado conforme classificação do alerta
CARE_LINES: Dict[str, Dict[str, Any]] = {
    "leve": {
        "priority_stars": 1,
        "priority_label": "★",
        "severity": "leve",
        "nurse": (
            "Manter o paciente sob vigilância ampliada na plataforma, "
            "acompanhando mais de perto as próximas medições e a evolução dos dados."
        ),
        "acs": (
            "Sem acionamento programado do ACS nesta classificação. "
            "Realizar visita domiciliar no prazo máximo de 1 semana."
        ),
        "acs_dispatch": False,
        "acs_deadline_hours": 168,
        "acs_deadline_label": "1 semana",
    },
    "moderado": {
        "priority_stars": 2,
        "priority_label": "★★",
        "severity": "moderado",
        "nurse": (
            "Enviar mensagem ao paciente e ao cuidador, perguntando se o paciente "
            "apresenta algum tipo de sintoma ou se está se sentindo bem. "
            "Ordenar ao ACS que realize visita domiciliar em até 48 horas."
        ),
        "acs": "Realizar a visita domiciliar no prazo máximo de 48 horas.",
        "acs_dispatch": True,
        "acs_deadline_hours": 48,
        "acs_deadline_label": "48 horas",
    },
    "critico": {
        "priority_stars": 3,
        "priority_label": "★★★",
        "severity": "critico",
        "nurse": (
            "Contatar o paciente e o cuidador, perguntando se o paciente "
            "apresenta algum tipo de sintoma ou se está se sentindo bem. "
            "Ordenar ao ACS que vá até a residência do paciente, confira os dados "
            "vitais e conclua a visita em até 4 horas."
        ),
        "acs": (
            "Ir até a residência do paciente, conferir os dados vitais e "
            "concluir a visita no mesmo dia do alerta."
        ),
        "acs_dispatch": True,
        "acs_deadline_hours": 4,
        "acs_deadline_label": "4 horas / mesmo dia",
    },
}

CATEGORY_NOTES: Dict[str, str] = {
    "infeccao": (
        "Os dados do device sinalizam possível deterioração, mas não confirmam "
        "nem diferenciam pneumonia, ITU ou sepse; correlacionar com sintomas, "
        "avaliação clínica e exames quando indicados."
    ),
    "desidratacao": (
        "O device não mede hidratação diretamente; os cruzamentos indicam "
        "possível desidratação ou hipovolemia e exigem confirmação clínica."
    ),
    "queda": (
        "Sem detecção validada de impacto, a matriz indica possível queda ou "
        "evento agudo pela mudança de atividade e dos sinais fisiológicos; "
        "confirmar com o paciente, cuidador ou ACS. Regras com interrupção "
        "abrupta aplicam-se quando houver dado horário de passos."
    ),
}


CLINICAL_DECISION_SUPPORT: Dict[str, Any] = {
    "kind": "decision_support",
    "not_a_diagnosis": True,
    "not_a_mandatory_protocol": True,
    "disclaimer": (
        "Apoio à decisão clínica. Cruzamentos de wearable não confirmam "
        "diagnóstico (infecção, desidratação, queda ou outro). Linhas de "
        "enfermeira/ACS são orientação operacional — não substituem protocolo "
        "institucional, avaliação presencial nem conduta médica."
    ),
}


def care_line_for(severity: str) -> Optional[Dict[str, Any]]:
    """Linha de cuidado da enfermeira e do ACS para a classificação.

    Sempre marcada como orientação (não protocolo mandatório).
    """
    line = CARE_LINES.get(severity)
    if not line:
        return None
    out = dict(line)
    out["mandatory"] = False
    out["protocol_binding"] = False
    out["kind"] = "operational_guidance"
    return out


def with_decision_support(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Anexa o aviso de apoio à decisão a um dict de alerta."""
    out = dict(payload)
    out["decision_support"] = dict(CLINICAL_DECISION_SUPPORT)
    care = out.get("care_line")
    if isinstance(care, dict) and care.get("mandatory") is None:
        care = dict(care)
        care["mandatory"] = False
        care["protocol_binding"] = False
        care["kind"] = care.get("kind") or "operational_guidance"
        out["care_line"] = care
    return out


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
    hr_baseline_rise: Optional[float] = None  # Δ bpm vs FC basal (positivo = alta)
    spo2_drop_points: Optional[float] = None  # queda absoluta de SpO2 vs baseline
    consciousness_altered: bool = False  # hipoglicemia grave
    # Deltas vs basal / medida anterior
    pas_rise_mmhg: Optional[float] = None
    pad_rise_mmhg: Optional[float] = None
    pas_drop_mmhg: Optional[float] = None
    glucose_rise_mgdl: Optional[float] = None
    glucose_drop_mgdl: Optional[float] = None
    temp_rise_c: Optional[float] = None
    temp_drop_c: Optional[float] = None
    hr_drop_from_baseline: Optional[float] = None
    # Contexto de leitura
    at_rest: Optional[bool] = None
    technically_valid: bool = True
    reading_isolated: bool = True
    fasting_or_preprandial: bool = False
    consecutive_count: int = 1
    glucose_falling_trend: bool = False
    glucose_persistent_after_remeasure: bool = False
    sleep_hours: Optional[float] = None
    steps_drop_consecutive_days: int = 0
    poor_sleep_nights: int = 0
    hourly_steps_available: bool = False
    abrupt_steps_stop: bool = False
    inactivity_rest_of_active_period: bool = False
    altered_vitals_count: Optional[int] = None

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
    priority_stars: int = 1

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priority_label"] = SEVERITY_STAR_LABEL.get(self.severity, "")
        return d


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
    care_line: Optional[Dict[str, Any]] = None
    clinical_notes: List[str] = field(default_factory=list)

    SEVERITY_RANK = SEVERITY_RANK

    def to_dict(self) -> Dict[str, Any]:
        return with_decision_support(
            {
                "hits": [h.to_dict() for h in self.hits],
                "max_severity": self.max_severity,
                "is_true_alert": self.is_true_alert,
                "is_false_positive_candidate": self.is_false_positive_candidate,
                "primary_alert_name": self.primary_alert_name,
                "primary_rule_id": self.primary_rule_id,
                "explanation": self.explanation,
                "care_line": self.care_line,
                "clinical_notes": list(self.clinical_notes),
            }
        )


def _in(v: Optional[float], lo: float, hi: float) -> bool:
    return v is not None and lo <= v <= hi


def _ge(v: Optional[float], thr: float) -> bool:
    return v is not None and v >= thr


def _le(v: Optional[float], thr: float) -> bool:
    return v is not None and v <= thr


def _lt(v: Optional[float], thr: float) -> bool:
    return v is not None and v < thr


def _valid(v: VitalSnapshot) -> bool:
    return bool(v.technically_valid)


def _resting(v: VitalSnapshot) -> bool:
    return v.at_rest is True


def _consecutive(v: VitalSnapshot, n: int = 2) -> bool:
    return int(v.consecutive_count or 0) >= n


def _hourly_steps(v: VitalSnapshot) -> bool:
    return bool(v.hourly_steps_available) and bool(v.abrupt_steps_stop)


def _hr_elevated_any(v: VitalSnapshot) -> bool:
    return _ge(v.hr, 91)


def _temp_altered(v: VitalSnapshot) -> bool:
    return _ge(v.temp_c, 38.1) or _le(v.temp_c, 36.0)


def _pa_or_spo2_or_temp_abnormal(v: VitalSnapshot) -> bool:
    return (
        _ge(v.pas, 140)
        or _ge(v.pad, 90)
        or _le(v.pas, 100)
        or _le(v.spo2, 96)
        or _ge(v.temp_c, 38.1)
        or _le(v.temp_c, 35.0)
    )


def _count_altered_vitals(v: VitalSnapshot) -> int:
    if v.altered_vitals_count is not None:
        return int(v.altered_vitals_count)
    n = 0
    if _ge(v.pas, 140) or _ge(v.pad, 90) or _le(v.pas, 100):
        n += 1
    if _ge(v.hr, 91) or _le(v.hr, 50):
        n += 1
    if _le(v.spo2, 96):
        n += 1
    if _temp_altered(v):
        n += 1
    if v.glucose_mgdl is not None and (v.glucose_mgdl < 70 or v.glucose_mgdl >= 181):
        n += 1
    return n


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
                "priority_stars": SEVERITY_STARS[sev],
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
    add(
        "pa_elev_7",
        "pa_alta",
        "leve",
        "Possível elevação pressórica persistente",
        lambda v: _in(v.pas, 140, 159) and _in(v.pad, 90, 99),
    )
    add(
        "pa_elev_8",
        "pa_alta",
        "moderado",
        "Possível hipertensão importante sem outros sinais associados",
        lambda v: _in(v.pas, 160, 179) and _in(v.pad, 100, 109),
    )
    add(
        "pa_elev_9",
        "pa_alta",
        "moderado",
        "Possível sobrecarga cardiovascular associada a dessaturação",
        lambda v: _in(v.pas, 160, 179) and _in(v.pad, 100, 109) and _in(v.spo2, 93, 94),
    )
    add(
        "pa_elev_10",
        "pa_alta",
        "moderado",
        "Possível alteração pressórica aguda com resposta cardíaca",
        lambda v: (_ge(v.pas_rise_mmhg, 30) or _ge(v.pad_rise_mmhg, 20))
        and _in(v.hr, 91, 110),
    )
    add(
        "pa_elev_11",
        "pa_alta",
        "leve",
        "Possível elevação pressórica leve em medida isolada",
        lambda v: _valid(v) and (_in(v.pas, 130, 139) or _in(v.pad, 80, 89)),
    )
    add(
        "pa_elev_12",
        "pa_alta",
        "leve",
        "Possível elevação sistólica isolada",
        lambda v: _valid(v) and _in(v.pas, 140, 159) and _lt(v.pad, 90),
    )
    add(
        "pa_elev_13",
        "pa_alta",
        "leve",
        "Possível elevação diastólica isolada",
        lambda v: _valid(v) and _in(v.pad, 90, 99) and _lt(v.pas, 140),
    )
    add(
        "pa_elev_14",
        "pa_alta",
        "moderado",
        "Possível elevação sistólica importante",
        lambda v: _valid(v) and _in(v.pas, 160, 179) and _lt(v.pad, 100),
    )
    add(
        "pa_elev_15",
        "pa_alta",
        "moderado",
        "Possível elevação diastólica importante",
        lambda v: _valid(v) and _in(v.pad, 100, 109) and _lt(v.pas, 160),
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
    add(
        "pa_baixa_7",
        "pa_baixa",
        "leve",
        "Possível tendência à hipotensão",
        lambda v: _in(v.pas, 101, 110),
    )
    add(
        "pa_baixa_8",
        "pa_baixa",
        "moderado",
        "Possível hipotensão",
        lambda v: _in(v.pas, 91, 100),
    )
    add(
        "pa_baixa_9",
        "pa_baixa",
        "moderado",
        "Possível hipovolemia inicial ou estresse circulatório",
        lambda v: _in(v.pas, 91, 100) and _in(v.hr, 91, 110),
    )
    add(
        "pa_baixa_10",
        "pa_baixa",
        "moderado",
        "Possível comprometimento hemodinâmico e respiratório inicial",
        lambda v: _in(v.pas, 91, 100) and _in(v.spo2, 93, 94),
    )
    add(
        "pa_baixa_11",
        "pa_baixa",
        "leve",
        "Possível queda pressórica aguda relativa ao basal",
        lambda v: _ge(v.pas_drop_mmhg, 20) and _in(v.pas, 101, 110),
    )
    add(
        "pa_baixa_12",
        "pa_baixa",
        "moderado",
        "Possível redução pressórica importante em relação ao basal",
        lambda v: _ge(v.pas_drop_mmhg, 30) and _in(v.pas, 91, 110),
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
    add(
        "spo2_8",
        "spo2",
        "leve",
        "Possível estresse cardiorrespiratório leve",
        lambda v: _in(v.spo2, 95, 96) and _in(v.hr, 91, 110),
    )
    add(
        "spo2_9",
        "spo2",
        "leve",
        "Possível tendência de queda da oxigenação",
        lambda v: _ge(v.spo2_drop_points, 2)
        and (v.spo2_drop_points is not None and v.spo2_drop_points < 3)
        and _ge(v.spo2, 95),
    )
    add(
        "spo2_10",
        "spo2",
        "moderado",
        "Possível infecção respiratória com dessaturação moderada",
        lambda v: _in(v.spo2, 93, 94) and _in(v.temp_c, 38.1, 39.0),
    )
    add(
        "spo2_11",
        "spo2",
        "moderado",
        "Possível limitação respiratória com impacto funcional",
        lambda v: _in(v.spo2, 93, 94) and _ge(v.steps_drop_pct, 40),
    )
    add(
        "spo2_12",
        "spo2",
        "moderado",
        "Possível deterioração da oxigenação",
        lambda v: _ge(v.spo2_drop_points, 3),
    )
    add(
        "spo2_13",
        "spo2",
        "moderado",
        "Possível dessaturação relevante em medida isolada",
        lambda v: _valid(v) and v.spo2 is not None and abs(v.spo2 - 92.0) < 0.51,
    )
    add(
        "spo2_14",
        "spo2",
        "moderado",
        "Possível dessaturação leve persistente",
        lambda v: _in(v.spo2, 95, 96) and _consecutive(v, 2) and _valid(v),
    )
    add(
        "spo2_15",
        "spo2",
        "moderado",
        "Possível queda aguda da oxigenação",
        lambda v: _ge(v.spo2_drop_points, 3) and _in(v.spo2, 93, 94),
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
    add(
        "temp_8",
        "temperatura",
        "leve",
        "Possível estado febril",
        lambda v: _in(v.temp_c, 38.1, 39.0),
    )
    add(
        "temp_9",
        "temperatura",
        "leve",
        "Possível redução leve da temperatura corporal",
        lambda v: _in(v.temp_c, 35.1, 36.0),
    )
    add(
        "temp_10",
        "temperatura",
        "moderado",
        "Possível hipotermia leve com repercussão fisiológica",
        lambda v: _in(v.temp_c, 35.1, 36.0)
        and (_in(v.hr, 41, 50) or _in(v.pas, 101, 110)),
    )
    add(
        "temp_11",
        "temperatura",
        "moderado",
        "Possível infecção respiratória em fase inicial",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.spo2, 93, 94),
    )
    add(
        "temp_12",
        "temperatura",
        "moderado",
        "Possível processo febril ou inflamatório agudo",
        lambda v: _ge(v.temp_rise_c, 1.0) and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "temp_13",
        "temperatura",
        "moderado",
        "Possível febre alta em medida isolada",
        lambda v: _valid(v) and _ge(v.temp_c, 39.1),
    )
    add(
        "temp_14",
        "temperatura",
        "moderado",
        "Possível redução térmica aguda",
        lambda v: _ge(v.temp_drop_c, 1.0) and _in(v.temp_c, 35.1, 36.0),
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
    add(
        "hypo_6",
        "hipoglicemia",
        "leve",
        "Possível tendência à hipoglicemia",
        lambda v: _in(v.glucose_mgdl, 70, 79) and bool(v.glucose_falling_trend),
    )
    add(
        "hypo_7",
        "hipoglicemia",
        "moderado",
        "Possível queda glicêmica com resposta adrenérgica inicial",
        lambda v: _in(v.glucose_mgdl, 70, 79) and _in(v.hr, 91, 110),
    )
    add(
        "hypo_8",
        "hipoglicemia",
        "moderado",
        "Possível queda glicêmica rápida",
        lambda v: _ge(v.glucose_drop_mgdl, 30) and _in(v.glucose_mgdl, 70, 89),
    )
    add(
        "hypo_9",
        "hipoglicemia",
        "moderado",
        "Possível hipoglicemia persistente",
        lambda v: _in(v.glucose_mgdl, 54, 69)
        and bool(v.glucose_persistent_after_remeasure),
    )
    add(
        "hypo_10",
        "hipoglicemia",
        "leve",
        "Possível glicemia abaixo da faixa habitual",
        lambda v: _valid(v) and _in(v.glucose_mgdl, 70, 79),
    )
    add(
        "hypo_11",
        "hipoglicemia",
        "moderado",
        "Possível glicemia baixa persistente",
        lambda v: _in(v.glucose_mgdl, 70, 79) and _consecutive(v, 2),
    )
    add(
        "hypo_12",
        "hipoglicemia",
        "leve",
        "Possível tendência de queda glicêmica",
        lambda v: v.glucose_drop_mgdl is not None
        and 20 <= v.glucose_drop_mgdl <= 29
        and _in(v.glucose_mgdl, 70, 89),
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
        "Possível hiperglicemia",
        lambda v: _ge(v.glucose_mgdl, 400)
        and (v.glucose_mgdl is not None and v.glucose_mgdl < 600),
    )
    add(
        "hyper_7",
        "hiperglicemia",
        "critico",
        "Possível estado hiperglicêmico hiperosmolar",
        lambda v: _ge(v.glucose_mgdl, 600),
    )
    add(
        "hyper_8",
        "hiperglicemia",
        "leve",
        "Possível elevação glicêmica aguda",
        lambda v: _ge(v.glucose_rise_mgdl, 50) and _in(v.glucose_mgdl, 181, 249),
    )
    add(
        "hyper_9",
        "hiperglicemia",
        "moderado",
        "Possível hiperglicemia persistente",
        lambda v: _in(v.glucose_mgdl, 181, 249) and _consecutive(v, 2),
    )
    add(
        "hyper_10",
        "hiperglicemia",
        "moderado",
        "Possível estresse metabólico associado a taquicardia leve",
        lambda v: _in(v.glucose_mgdl, 181, 249) and _in(v.hr, 91, 110),
    )
    add(
        "hyper_11",
        "hiperglicemia",
        "moderado",
        "Possível hiperglicemia associada a estado febril",
        lambda v: _in(v.glucose_mgdl, 181, 249) and _in(v.temp_c, 38.1, 39.0),
    )
    add(
        "hyper_12",
        "hiperglicemia",
        "moderado",
        "Possível alteração metabólica com repercussão funcional",
        lambda v: _in(v.glucose_mgdl, 181, 249) and _ge(v.steps_drop_pct, 40),
    )
    add(
        "hyper_13",
        "hiperglicemia",
        "leve",
        "Possível elevação glicêmica leve",
        lambda v: bool(v.fasting_or_preprandial) and _in(v.glucose_mgdl, 140, 180),
    )
    add(
        "hyper_14",
        "hiperglicemia",
        "leve",
        "Possível tendência de elevação glicêmica",
        lambda v: v.glucose_rise_mgdl is not None
        and 30 <= v.glucose_rise_mgdl <= 49
        and _in(v.glucose_mgdl, 181, 249),
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
    add(
        "fc_8",
        "fc",
        "leve",
        "Possível taquicardia leve",
        lambda v: _resting(v) and _in(v.hr, 91, 110) and not _consecutive(v, 2),
    )
    add(
        "fc_9",
        "fc",
        "leve",
        "Possível estresse fisiológico inicial",
        lambda v: _resting(v) and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "fc_10",
        "fc",
        "moderado",
        "Possível taquicardia persistente com necessidade de avaliação",
        lambda v: _resting(v) and _in(v.hr, 111, 130),
    )
    add(
        "fc_11",
        "fc",
        "moderado",
        "Possível resposta cardíaca a estado febril",
        lambda v: _in(v.hr, 91, 110) and _in(v.temp_c, 38.1, 39.0),
    )
    add(
        "fc_12",
        "fc",
        "moderado",
        "Possível estresse cardiorrespiratório",
        lambda v: _in(v.hr, 91, 110) and _in(v.spo2, 93, 94),
    )
    add(
        "fc_13",
        "fc",
        "leve",
        "Possível redução leve da frequência cardíaca",
        lambda v: _resting(v)
        and _in(v.hr, 51, 60)
        and _ge(v.hr_drop_from_baseline, 10),
    )
    add(
        "fc_14",
        "fc",
        "moderado",
        "Possível taquicardia leve persistente",
        lambda v: _resting(v) and _in(v.hr, 91, 110) and _consecutive(v, 2),
    )
    add(
        "fc_15",
        "fc",
        "leve",
        "Possível resposta fisiológica aguda",
        lambda v: _ge(v.hr_baseline_rise, 20) and _in(v.hr, 91, 110),
    )
    add(
        "fc_16",
        "fc",
        "moderado",
        "Possível taquicardia aguda relativa ao basal",
        lambda v: _ge(v.hr_baseline_rise, 30) and _in(v.hr, 111, 130),
    )

    # --- 8. Sinais de deterioração clínica (passos / sono) ---
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
    add(
        "func_7",
        "funcional",
        "leve",
        "Possível alteração funcional inicial",
        lambda v: v.steps_drop_pct is not None
        and 20 <= v.steps_drop_pct <= 39
        and v.sleep_worsen_pct is not None
        and 20 <= v.sleep_worsen_pct <= 29
        and int(v.steps_drop_consecutive_days or 0) >= 2,
    )
    add(
        "func_8",
        "funcional",
        "leve",
        "Possível redução funcional persistente",
        lambda v: _ge(v.steps_drop_pct, 30)
        and int(v.steps_drop_consecutive_days or 0) >= 3,
    )
    add(
        "func_9",
        "funcional",
        "leve",
        "Possível sono insuficiente ou não reparador",
        lambda v: (
            (v.sleep_hours is not None and v.sleep_hours < 6 and v.poor_sleep_nights >= 2)
            or _ge(v.sleep_worsen_pct, 30)
        ),
    )
    add(
        "func_10",
        "funcional",
        "leve",
        "Possível estresse fisiológico associado à piora do sono",
        lambda v: _ge(v.sleep_worsen_pct, 30)
        and v.hr_baseline_rise is not None
        and 10 <= v.hr_baseline_rise <= 14,
    )
    add(
        "func_11",
        "funcional",
        "moderado",
        "Possível privação de sono com repercussão fisiológica",
        lambda v: v.sleep_hours is not None
        and v.sleep_hours < 5
        and v.poor_sleep_nights >= 2
        and _ge(v.hr_baseline_rise, 10),
    )
    add(
        "func_12",
        "funcional",
        "moderado",
        "Possível alteração respiratória associada ao sono",
        lambda v: _ge(v.sleep_worsen_pct, 40) and _ge(v.spo2_drop_points, 2),
    )
    add(
        "func_13",
        "funcional",
        "moderado",
        "Possível redução funcional associada a hipotensão",
        lambda v: _ge(v.steps_drop_pct, 40) and _in(v.pas, 91, 100),
    )
    add(
        "func_14",
        "funcional",
        "moderado",
        "Possível doença aguda com repercussão funcional",
        lambda v: _ge(v.steps_drop_pct, 40) and _in(v.temp_c, 38.1, 39.0),
    )

    # --- 9. Possíveis infecções (pneumonia, ITU, sepse) ---
    add(
        "inf_1",
        "infeccao",
        "leve",
        "Possível infecção sem repercussão respiratória, incluindo ITU",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.spo2, 95) and _in(v.hr, 91, 110),
    )
    add(
        "inf_2",
        "infeccao",
        "leve",
        "Possível processo infeccioso com alteração funcional inicial",
        lambda v: _in(v.temp_c, 38.1, 39.0)
        and v.steps_drop_pct is not None
        and 20 <= v.steps_drop_pct <= 39,
    )
    add(
        "inf_3",
        "infeccao",
        "moderado",
        "Possível processo infeccioso ou inflamatório agudo",
        lambda v: _ge(v.temp_rise_c, 1.0) and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "inf_4",
        "infeccao",
        "moderado",
        "Possível infecção, incluindo ITU, com resposta sistêmica",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.spo2, 95) and _in(v.hr, 111, 130),
    )
    add(
        "inf_5",
        "infeccao",
        "moderado",
        "Possível infecção respiratória ou pneumonia com dessaturação moderada",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.spo2, 93, 94),
    )
    add(
        "inf_6",
        "infeccao",
        "moderado",
        "Possível pneumonia com repercussão respiratória e funcional",
        lambda v: _in(v.spo2, 93, 94)
        and _in(v.hr, 111, 130)
        and _ge(v.steps_drop_pct, 40),
    )
    add(
        "inf_7",
        "infeccao",
        "moderado",
        "Possível infecção associada a descompensação metabólica",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.glucose_mgdl, 250, 399),
    )
    add(
        "inf_8",
        "infeccao",
        "moderado",
        "Possível infecção com resposta sistêmica importante",
        lambda v: _ge(v.temp_c, 39.1) and _in(v.hr, 111, 130),
    )
    add(
        "inf_9",
        "infeccao",
        "moderado",
        "Possível apresentação atípica de infecção com deterioração funcional",
        lambda v: _in(v.temp_c, 35.1, 36.0)
        and _in(v.hr, 91, 130)
        and _ge(v.steps_drop_pct, 40),
    )
    add(
        "inf_10",
        "infeccao",
        "critico",
        "Possível sepse com repercussão hemodinâmica",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.hr, 131) and _in(v.pas, 91, 100),
    )
    add(
        "inf_11",
        "infeccao",
        "critico",
        "Possível pneumonia grave ou infecção com hipoxemia",
        lambda v: _in(v.temp_c, 38.1, 39.0) and _le(v.spo2, 91) and _ge(v.hr, 111),
    )
    add(
        "inf_12",
        "infeccao",
        "critico",
        "Possível sepse com hipotermia e instabilidade fisiológica",
        lambda v: _le(v.temp_c, 35.0) and (_ge(v.hr, 111) or _le(v.pas, 100)),
    )
    add(
        "inf_13",
        "infeccao",
        "critico",
        "Possível sepse ou choque associado a infecção",
        lambda v: _le(v.pas, 90)
        and _ge(v.hr, 111)
        and (_ge(v.temp_c, 38.1) or _le(v.temp_c, 36.0)),
    )
    add(
        "inf_14",
        "infeccao",
        "critico",
        "Possível infecção grave com deterioração cardiorrespiratória e hemodinâmica",
        lambda v: _le(v.spo2, 91)
        and _le(v.pas, 100)
        and _ge(v.hr, 111)
        and _temp_altered(v),
    )

    # --- 10. Possível desidratação ---
    add(
        "desid_1",
        "desidratacao",
        "leve",
        "Possível desidratação leve ou estresse fisiológico inicial",
        lambda v: _in(v.hr, 91, 110) and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "desid_2",
        "desidratacao",
        "leve",
        "Possível redução leve do volume circulante",
        lambda v: _in(v.pas, 101, 110) and _in(v.hr, 91, 110),
    )
    add(
        "desid_3",
        "desidratacao",
        "leve",
        "Possível hipovolemia inicial em relação ao basal",
        lambda v: _ge(v.pas_drop_mmhg, 20)
        and _in(v.pas, 101, 110)
        and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "desid_4",
        "desidratacao",
        "leve",
        "Possível tendência persistente compatível com desidratação leve",
        lambda v: _in(v.pas, 101, 110) and _in(v.hr, 91, 110) and _consecutive(v, 2),
    )
    add(
        "desid_5",
        "desidratacao",
        "moderado",
        "Possível desidratação ou hipovolemia",
        lambda v: _in(v.pas, 91, 100) and _in(v.hr, 91, 110),
    )
    add(
        "desid_6",
        "desidratacao",
        "moderado",
        "Possível desidratação com taquicardia compensatória",
        lambda v: _in(v.pas, 91, 100) and _in(v.hr, 111, 130),
    )
    add(
        "desid_7",
        "desidratacao",
        "moderado",
        "Possível redução importante do volume circulante",
        lambda v: _ge(v.pas_drop_mmhg, 30) and _ge(v.hr_baseline_rise, 20),
    )
    add(
        "desid_8",
        "desidratacao",
        "moderado",
        "Possível desidratação com repercussão funcional",
        lambda v: _ge(v.steps_drop_pct, 40) and _in(v.pas, 91, 100),
    )
    add(
        "desid_9",
        "desidratacao",
        "moderado",
        "Possível desidratação osmótica associada à hiperglicemia",
        lambda v: _in(v.glucose_mgdl, 250, 399)
        and _in(v.hr, 111, 130)
        and _ge(v.steps_drop_pct, 40),
    )
    add(
        "desid_10",
        "desidratacao",
        "moderado",
        "Possível desidratação associada a febre alta",
        lambda v: _ge(v.temp_c, 39.1) and _in(v.hr, 111, 130),
    )
    add(
        "desid_11",
        "desidratacao",
        "critico",
        "Possível desidratação grave ou hipovolemia com instabilidade hemodinâmica",
        lambda v: _le(v.pas, 90) and _ge(v.hr, 111),
    )
    add(
        "desid_12",
        "desidratacao",
        "critico",
        "Possível desidratação grave com repercussão circulatória e funcional",
        lambda v: _le(v.pas, 90) and _ge(v.steps_drop_pct, 50),
    )
    add(
        "desid_13",
        "desidratacao",
        "critico",
        "Possível desidratação grave em descompensação hiperglicêmica",
        lambda v: _ge(v.glucose_mgdl, 400) and _ge(v.hr, 111) and _le(v.pas, 100),
    )
    add(
        "desid_14",
        "desidratacao",
        "critico",
        "Possível desidratação grave ou infecção com instabilidade clínica",
        lambda v: _ge(v.temp_c, 39.1) and _ge(v.hr, 131) and _le(v.pas, 100),
    )

    # --- 11. Possível queda ---
    add(
        "queda_1",
        "queda",
        "leve",
        "Possível alteração funcional ou evento com redução da mobilidade",
        lambda v: v.steps_drop_pct is not None and 40 <= v.steps_drop_pct <= 49,
    )
    add(
        "queda_2",
        "queda",
        "leve",
        "Possível evento de inatividade com necessidade de checagem",
        lambda v: _hourly_steps(v),
    )
    add(
        "queda_3",
        "queda",
        "leve",
        "Possível alteração funcional após evento não relatado",
        lambda v: _ge(v.steps_drop_pct, 40) and _ge(v.sleep_worsen_pct, 30),
    )
    add(
        "queda_4",
        "queda",
        "moderado",
        "Possível queda ou evento agudo com resposta fisiológica",
        lambda v: _hourly_steps(v) and _ge(v.hr_baseline_rise, 15),
    )
    add(
        "queda_5",
        "queda",
        "moderado",
        "Possível queda ou pré-síncope associada a redução pressórica",
        lambda v: _hourly_steps(v) and _ge(v.pas_drop_mmhg, 20),
    )
    add(
        "queda_6",
        "queda",
        "moderado",
        "Possível queda ou incapacidade funcional associada à hipotensão",
        lambda v: _ge(v.steps_drop_pct, 50) and _in(v.pas, 91, 100),
    )
    add(
        "queda_7",
        "queda",
        "moderado",
        "Possível dor ou estresse fisiológico após queda",
        lambda v: _hourly_steps(v) and _in(v.hr, 111, 130),
    )
    add(
        "queda_8",
        "queda",
        "moderado",
        "Possível evento cardiorrespiratório associado a queda",
        lambda v: _hourly_steps(v)
        and _ge(v.spo2_drop_points, 3)
        and _in(v.spo2, 93, 94),
    )
    add(
        "queda_9",
        "queda",
        "critico",
        "Possível queda com imobilidade ou deterioração clínica",
        lambda v: bool(v.inactivity_rest_of_active_period)
        and bool(v.hourly_steps_available)
        and _count_altered_vitals(v) >= 2,
    )
    add(
        "queda_10",
        "queda",
        "critico",
        "Possível síncope ou queda com instabilidade hemodinâmica",
        lambda v: _le(v.pas, 90) and _hourly_steps(v),
    )
    add(
        "queda_11",
        "queda",
        "critico",
        "Possível evento agudo ou queda com taquicardia importante",
        lambda v: _ge(v.hr, 131) and _hourly_steps(v),
    )
    add(
        "queda_12",
        "queda",
        "critico",
        "Possível evento cardiorrespiratório com queda ou imobilidade",
        lambda v: _le(v.spo2, 91) and _hourly_steps(v),
    )
    add(
        "queda_13",
        "queda",
        "critico",
        "Possível síncope ou queda associada a bradicardia",
        lambda v: _le(v.hr, 50) and _le(v.pas, 100) and _hourly_steps(v),
    )
    add(
        "queda_14",
        "queda",
        "critico",
        "Possível queda associada a hipoglicemia clinicamente significativa",
        lambda v: _lt(v.glucose_mgdl, 54) and _hourly_steps(v),
    )

    return R


ALERT_RULES: List[Dict[str, Any]] = _build_rules()


def rules_catalog() -> List[Dict[str, Any]]:
    """Catálogo serializável (sem predicates)."""
    return [
        {
            "rule_id": r["rule_id"],
            "category": r["category"],
            "severity": r["severity"],
            "name": r["name"],
            "priority_stars": r.get("priority_stars", SEVERITY_STARS.get(r["severity"], 1)),
            "priority_label": SEVERITY_STAR_LABEL.get(r["severity"], ""),
            "clinical_note": CATEGORY_NOTES.get(r["category"]),
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
                            priority_stars=rule.get(
                                "priority_stars", SEVERITY_STARS.get(rule["severity"], 1)
                            ),
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
                care_line=None,
                clinical_notes=[],
            )

        rank = AlertMatrixResult.SEVERITY_RANK
        best = max(hits, key=lambda h: rank.get(h.severity, 0))
        notes = []
        for cat in {h.category for h in hits}:
            note = CATEGORY_NOTES.get(cat)
            if note and note not in notes:
                notes.append(note)
        return AlertMatrixResult(
            hits=hits,
            max_severity=best.severity,
            is_true_alert=True,
            is_false_positive_candidate=False,
            primary_alert_name=best.name,
            primary_rule_id=best.rule_id,
            explanation=f"{len(hits)} regra(s); principal={best.rule_id} ({best.severity})",
            care_line=care_line_for(best.severity),
            clinical_notes=notes,
        )

    @staticmethod
    def _looks_anomalous_but_unmatched(v: VitalSnapshot) -> bool:
        """Sinais limítrofes/isolados que gerariam ruído mas não batem na matriz."""
        return any(
            [
                v.hr is not None and (100 <= v.hr <= 110 or 51 <= v.hr <= 55) and v.at_rest is not True,
                v.spo2 is not None and 96.1 <= v.spo2 <= 97.0,
                v.temp_c is not None and 37.5 <= v.temp_c < 38.1,
                v.glucose_mgdl is not None
                and 140 <= v.glucose_mgdl < 181
                and not v.fasting_or_preprandial,
                v.steps_drop_pct is not None
                and 20 <= v.steps_drop_pct < 40
                and int(v.steps_drop_consecutive_days or 0) < 2,
            ]
        )
