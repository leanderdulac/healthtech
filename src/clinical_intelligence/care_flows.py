"""
Linhas de cuidado por programa (fluxogramas da central de telemetria).

Fontes (ago/2026):
  FLUXO HAS FINAL.pdf
  FLUXO DM FINAL.pdf
  FLUXO DRC FINAL.pdf
  FLUXO DOENCAS RESP FINAL.pdf
  FLUXO HEPATOPATIAS FINAL.pdf
  fluxo obstetrico final.pdf

Overlay da matriz Next2U: só dispara com padrão fisiológico válido.
Doença isolada não cria alerta. "Outros sinais" = ≥2 ramos anormais no mesmo fluxo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.clinical_intelligence.alert_matrix_rules import VitalSnapshot
from src.clinical_intelligence.next2u_context import PatientContext

CATALOG_VERSION = "care-flows-2026-08-24"
SEVERITY_RANK = {"none": 0, "leve": 1, "moderado": 2, "critico": 3}

PROGRAM_DISEASES: Dict[str, Set[str]] = {
    "has": {"hypertension"},
    "dm": {"diabetes", "diabetes_decompensated"},
    "drc": {"ckd"},
    "dpoc": {"copd"},
    "hepatopatia": {"liver_failure"},
    "obstetrico": {"pregnancy"},
}

SOURCES = {
    "has": "FLUXO HAS FINAL.pdf",
    "dm": "FLUXO DM FINAL.pdf",
    "drc": "FLUXO DRC FINAL.pdf",
    "dpoc": "FLUXO DOENCAS RESP FINAL.pdf",
    "hepatopatia": "FLUXO HEPATOPATIAS FINAL.pdf",
    "obstetrico": "fluxo obstetrico final.pdf",
}

# Aferições padrão do ACS (tabela 2 do fluxo de hepatopatias).
ACS_CHECKS_HEPATOPATIA = (
    "pa",
    "spo2",
    "glicemia",
    "temp",
    "fc",
    "ecg_wearable",
    "peso",
    "circunferencia_abdominal",
)


@dataclass
class CareFlowHit:
    program: str
    branch: str
    severity: str
    alert_name: str
    action: str  # central | acs | ubs | samu
    instruction: str
    other_signs: bool = False
    pending_confirmation: bool = False
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CareFlowResult:
    matched: bool = False
    program: Optional[str] = None
    severity: str = "none"
    stars: int = 0
    action: Optional[str] = None
    alert_name: Optional[str] = None
    instruction: Optional[str] = None
    other_signs: bool = False
    pending_confirmation: bool = False
    hits: List[CareFlowHit] = field(default_factory=list)
    enrolled: List[str] = field(default_factory=list)
    catalog_version: str = CATALOG_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched": self.matched,
            "program": self.program,
            "severity": self.severity,
            "stars": self.stars,
            "action": self.action,
            "alert_name": self.alert_name,
            "instruction": self.instruction,
            "other_signs": self.other_signs,
            "pending_confirmation": self.pending_confirmation,
            "hits": [h.to_dict() for h in self.hits],
            "enrolled": self.enrolled,
            "catalog_version": self.catalog_version,
        }


def enrolled_programs(ctx: Optional[PatientContext]) -> List[str]:
    if ctx is None:
        return []
    d = ctx.disease_set
    return [p for p, diseases in PROGRAM_DISEASES.items() if d & diseases]


def _hr_out_of_60_100(v: VitalSnapshot) -> bool:
    return v.hr is not None and (v.hr > 100 or v.hr < 60)


def _confirmed(ctx: PatientContext, v: VitalSnapshot) -> bool:
    return bool(ctx.confirmation_or_persistence or (v.consecutive_valid or 1) >= 2)


def _gate(abnormal: bool, other_signs: bool) -> Optional[str]:
    """Ramos com losango 'OUTROS SINAIS': SIM=crítico, NÃO=moderado."""
    if not abnormal:
        return None
    return "critico" if other_signs else "moderado"


def _eval_has(v: VitalSnapshot, ctx: PatientContext) -> List[CareFlowHit]:
    hits: List[CareFlowHit] = []
    src = SOURCES["has"]
    if (v.pas is not None and v.pas < 90) or (v.pad is not None and v.pad < 60):
        hits.append(
            CareFlowHit(
                program="has",
                branch="pa_lt_90_60",
                severity="critico",
                alert_name="Possível hipotensão no programa HAS",
                action="samu",
                instruction="PA < 90×60 mmHg — alerta crítico na central de monitoramento.",
                source=src,
            )
        )
    if (v.pas is not None and v.pas > 180) or (v.pad is not None and v.pad > 120):
        hits.append(
            CareFlowHit(
                program="has",
                branch="pa_gt_180_120",
                severity="critico",
                alert_name="Possível crise hipertensiva (fluxo HAS)",
                action="samu",
                instruction="PA > 180/120 mmHg — alerta crítico.",
                source=src,
            )
        )
    elif (v.pas is not None and v.pas > 140) and (v.pad is not None and v.pad > 100):
        hits.append(
            CareFlowHit(
                program="has",
                branch="pa_gt_140_100",
                severity="moderado",
                alert_name="Possível descontrole pressórico (fluxo HAS)",
                action="acs",
                instruction="PA > 140/100 mmHg — alerta moderado; ACS conferir medição.",
                source=src,
            )
        )
    return hits


def _eval_dm(v: VitalSnapshot, ctx: PatientContext) -> List[CareFlowHit]:
    hits: List[CareFlowHit] = []
    src = SOURCES["dm"]
    g = v.glucose_mgdl
    if g is None:
        return hits

    if g < 54 or v.consciousness_altered:
        hits.append(
            CareFlowHit(
                program="dm",
                branch="hipo_grave",
                severity="critico",
                alert_name="Possível hipoglicemia grave (fluxo DM)",
                action="samu",
                instruction="<54 mg/dL ou alteração de consciência — acionar SAMU.",
                source=src,
            )
        )
        return hits

    if g < 70:
        confirmed = _confirmed(ctx, v)
        if confirmed and ctx.symptoms:
            hits.append(
                CareFlowHit(
                    program="dm",
                    branch="hipo_confirmada_sintomatica",
                    severity="critico",
                    alert_name="Possível hipoglicemia sintomática confirmada (fluxo DM)",
                    action="samu",
                    instruction="Duas medidas <70 mg/dL em 15 min com sintomas — alerta crítico.",
                    source=src,
                )
            )
        elif confirmed:
            hits.append(
                CareFlowHit(
                    program="dm",
                    branch="hipo_confirmada_assintomatica",
                    severity="moderado",
                    alert_name="Possível hipoglicemia confirmada (fluxo DM)",
                    action="ubs",
                    instruction="Duas medidas <70 mg/dL sem sintomas — alerta moderado (UBS).",
                    source=src,
                )
            )
        else:
            hits.append(
                CareFlowHit(
                    program="dm",
                    branch="hipo_acs_aferir",
                    severity="moderado",
                    alert_name="Possível hipoglicemia — ACS aferir (fluxo DM)",
                    action="acs",
                    instruction="Wearable <70 mg/dL — ACS confirmar com glicosímetro (2 medidas / 15 min).",
                    pending_confirmation=True,
                    source=src,
                )
            )
        return hits

    if g > 250:
        confirmed = _confirmed(ctx, v)
        if ctx.symptoms and ((v.pas is not None and v.pas > 180) or (v.pad is not None and v.pad > 120)):
            hits.append(
                CareFlowHit(
                    program="dm",
                    branch="hiper_sintomatica_pa_crise",
                    severity="critico",
                    alert_name="Possível hiperglicemia com crise pressórica (fluxo DM)",
                    action="samu",
                    instruction="Hiperglicemia sintomática e PA > 180×120 — alerta crítico.",
                    source=src,
                )
            )
        elif ctx.symptoms:
            hits.append(
                CareFlowHit(
                    program="dm",
                    branch="hiper_sintomatica",
                    severity="moderado",
                    alert_name="Possível hiperglicemia sintomática (fluxo DM)",
                    action="acs",
                    instruction="Aferir 2×/15 min; hidratar, verificar cetonúria e PA.",
                    pending_confirmation=not confirmed,
                    source=src,
                )
            )
        else:
            hits.append(
                CareFlowHit(
                    program="dm",
                    branch="hiper_assintomatica",
                    severity="moderado",
                    alert_name="Possível hiperglicemia (fluxo DM)",
                    action="acs",
                    instruction=">250 mg/dL sem sintomas — manter aferição e ACS confirmar.",
                    pending_confirmation=not confirmed,
                    source=src,
                )
            )
    return hits


def _eval_drc(v: VitalSnapshot, ctx: PatientContext) -> List[CareFlowHit]:
    src = SOURCES["drc"]
    flags = {
        "fc": _hr_out_of_60_100(v),
        "pa_persistente": (
            ((v.pas is not None and v.pas > 140) or (v.pad is not None and v.pad > 90))
            and _confirmed(ctx, v)
        ),
        "spo2": v.spo2 is not None and v.spo2 < 92,
    }
    crise = (v.pas is not None and v.pas > 180) or (v.pad is not None and v.pad > 120)
    other = sum(1 for x in flags.values() if x) >= 2
    hits: List[CareFlowHit] = []
    if crise:
        hits.append(
            CareFlowHit(
                program="drc",
                branch="pa_gt_180_120",
                severity="critico",
                alert_name="Possível crise pressórica na DRC",
                action="samu",
                instruction="PA > 180×120 — alerta crítico (fluxo DRC).",
                source=src,
            )
        )
    for branch, abnormal in flags.items():
        sev = _gate(abnormal, other)
        if sev is None:
            continue
        hits.append(
            CareFlowHit(
                program="drc",
                branch=branch,
                severity=sev,
                alert_name=f"Possível descompensação DRC ({branch})",
                action="samu" if sev == "critico" else "acs",
                instruction=(
                    "Dois ou mais sinais no fluxo DRC — alerta crítico."
                    if sev == "critico"
                    else "Sinal isolado no fluxo DRC — alerta moderado; ACS conferir."
                ),
                other_signs=other,
                source=src,
            )
        )
    return hits


def _eval_dpoc(v: VitalSnapshot, ctx: PatientContext) -> List[CareFlowHit]:
    src = SOURCES["dpoc"]
    hits: List[CareFlowHit] = []
    if v.spo2 is not None and v.spo2 < 92:
        hits.append(
            CareFlowHit(
                program="dpoc",
                branch="spo2_lt_92",
                severity="critico",
                alert_name="Possível hipoxemia no programa DPOC",
                action="samu",
                instruction="SpO2 < 92% — alerta crítico.",
                source=src,
            )
        )
    if v.temp_c is not None and v.temp_c > 37.5:
        hits.append(
            CareFlowHit(
                program="dpoc",
                branch="temp_gt_37_5",
                severity="critico",
                alert_name="Possível febre no programa DPOC",
                action="acs",
                instruction="Temperatura > 37,5 °C — alerta crítico (fluxo respiratório).",
                source=src,
            )
        )
    pa_delta = False
    rise = v.pas_rise()
    drop = v.pas_drop()
    if rise is not None and abs(rise) > 20:
        pa_delta = True
    if drop is not None and abs(drop) > 20:
        pa_delta = True
    gated = {
        "fc": _hr_out_of_60_100(v),
        "pa_delta": pa_delta,
    }
    other = sum(1 for x in gated.values() if x) >= 2 or bool(hits)
    for branch, abnormal in gated.items():
        sev = _gate(abnormal, other)
        if sev is None:
            continue
        hits.append(
            CareFlowHit(
                program="dpoc",
                branch=branch,
                severity=sev,
                alert_name=f"Possível descompensação respiratória ({branch})",
                action="samu" if sev == "critico" else "acs",
                instruction=(
                    "FC ou ΔPA com outros sinais — alerta crítico."
                    if sev == "critico"
                    else "FC ou ΔPA isolada — alerta moderado."
                ),
                other_signs=other,
                source=src,
            )
        )
    return hits


def _eval_hepatopatia(v: VitalSnapshot, ctx: PatientContext) -> List[CareFlowHit]:
    src = SOURCES["hepatopatia"]
    hits: List[CareFlowHit] = []
    if (v.pas is not None and v.pas < 100) or (v.pad is not None and v.pad < 60):
        hits.append(
            CareFlowHit(
                program="hepatopatia",
                branch="pa_baixa",
                severity="critico",
                alert_name="Possível hipotensão na hepatopatia",
                action="samu",
                instruction="PAS < 100 ou PAD < 60 mmHg — alerta crítico.",
                source=src,
            )
        )
    if v.temp_c is not None and v.temp_c > 37.8:
        hits.append(
            CareFlowHit(
                program="hepatopatia",
                branch="temp_gt_37_8",
                severity="critico",
                alert_name="Possível febre na hepatopatia",
                action="acs",
                instruction="Temperatura > 37,8 °C — alerta crítico; ACS aferir tabela 2.",
                source=src,
            )
        )
    gated = {
        "fc": _hr_out_of_60_100(v),
        "spo2": v.spo2 is not None and v.spo2 < 95,
        "glicemia": v.glucose_mgdl is not None and (v.glucose_mgdl > 200 or v.glucose_mgdl < 70),
    }
    other = sum(1 for x in gated.values() if x) >= 2
    for branch, abnormal in gated.items():
        sev = _gate(abnormal, other)
        if sev is None:
            continue
        hits.append(
            CareFlowHit(
                program="hepatopatia",
                branch=branch,
                severity=sev,
                alert_name=f"Possível descompensação hepática ({branch})",
                action="samu" if sev == "critico" else "acs",
                instruction=(
                    "Dois ou mais sinais (FC/SpO2/glicemia) — alerta crítico."
                    if sev == "critico"
                    else "Sinal isolado — alerta moderado; ACS conferir PA, SpO2, glicemia, temp, FC, ECG, peso e circunferência abdominal."
                ),
                other_signs=other,
                source=src,
            )
        )
    return hits


def _eval_obstetrico(v: VitalSnapshot, ctx: PatientContext) -> List[CareFlowHit]:
    src = SOURCES["obstetrico"]
    hits: List[CareFlowHit] = []
    if _hr_out_of_60_100(v):
        hits.append(
            CareFlowHit(
                program="obstetrico",
                branch="fc",
                severity="critico",
                alert_name="Possível instabilidade hemodinâmica na gestação",
                action="samu",
                instruction="FC > 100 ou < 60 bpm — alerta crítico (fluxo obstétrico).",
                source=src,
            )
        )
    if (v.pas is not None and v.pas > 140) or (v.pad is not None and v.pad > 90):
        hits.append(
            CareFlowHit(
                program="obstetrico",
                branch="pa_gt_140_90",
                severity="critico",
                alert_name="Possível hipertensão na gestação",
                action="samu",
                instruction="PAS > 140 ou PAD > 90 mmHg — alerta crítico.",
                source=src,
            )
        )
    if v.glucose_mgdl is not None and v.glucose_mgdl < 70:
        hits.append(
            CareFlowHit(
                program="obstetrico",
                branch="hipoglicemia",
                severity="critico",
                alert_name="Possível hipoglicemia na gestação",
                action="samu",
                instruction="Glicemia < 70 mg/dL — alerta crítico.",
                source=src,
            )
        )
    if v.glucose_mgdl is not None and v.glucose_mgdl > 200:
        hits.append(
            CareFlowHit(
                program="obstetrico",
                branch="hiperglicemia",
                severity="moderado",
                alert_name="Possível hiperglicemia na gestação",
                action="acs",
                instruction="Glicemia > 200 mg/dL — alerta moderado.",
                source=src,
            )
        )
    if v.temp_c is not None and v.temp_c > 37.8:
        hits.append(
            CareFlowHit(
                program="obstetrico",
                branch="temp_gt_37_8",
                severity="critico",
                alert_name="Possível febre na gestação",
                action="acs",
                instruction="Temperatura > 37,8 °C — alerta crítico.",
                source=src,
            )
        )
    if v.spo2 is not None and v.spo2 < 95:
        other = bool(hits)
        sev = "critico" if other else "moderado"
        hits.append(
            CareFlowHit(
                program="obstetrico",
                branch="spo2_lt_95",
                severity=sev,
                alert_name="Possível hipoxemia na gestação",
                action="samu" if sev == "critico" else "acs",
                instruction=(
                    "SpO2 < 95% com outros sinais — alerta crítico."
                    if sev == "critico"
                    else "SpO2 < 95% isolada — alerta moderado."
                ),
                other_signs=other,
                source=src,
            )
        )
    return hits


_EVALUATORS = {
    "has": _eval_has,
    "dm": _eval_dm,
    "drc": _eval_drc,
    "dpoc": _eval_dpoc,
    "hepatopatia": _eval_hepatopatia,
    "obstetrico": _eval_obstetrico,
}


def evaluate_care_flows(
    vitals: VitalSnapshot,
    context: Optional[PatientContext] = None,
) -> CareFlowResult:
    ctx = context or PatientContext()
    enrolled = enrolled_programs(ctx)
    result = CareFlowResult(enrolled=enrolled)
    if not enrolled:
        return result

    hits: List[CareFlowHit] = []
    for program in enrolled:
        hits.extend(_EVALUATORS[program](vitals, ctx))

    if not hits:
        return result

    best = max(hits, key=lambda h: (SEVERITY_RANK.get(h.severity, 0), h.action == "samu"))
    stars = {"leve": 1, "moderado": 2, "critico": 3}.get(best.severity, 0)
    result.matched = True
    result.program = best.program
    result.severity = best.severity
    result.stars = stars
    result.action = best.action
    result.alert_name = best.alert_name
    result.instruction = best.instruction
    result.other_signs = any(h.other_signs for h in hits)
    result.pending_confirmation = any(h.pending_confirmation for h in hits)
    result.hits = hits
    return result


def apply_care_flow_overlay(full: Dict[str, Any], flow: CareFlowResult) -> Dict[str, Any]:
    """Anexa o fluxo ao payload e escala severidade se o programa for mais grave."""
    out = dict(full)
    payload = flow.to_dict()
    if flow.program == "hepatopatia":
        payload["acs_checks"] = list(ACS_CHECKS_HEPATOPATIA)
    out["care_flow"] = payload
    if not flow.matched:
        return out

    current = SEVERITY_RANK.get(str(out.get("severity") or "none"), 0)
    incoming = SEVERITY_RANK.get(flow.severity, 0)
    if incoming > current:
        out["severity"] = flow.severity
        out["stars"] = max(int(out.get("stars") or 0), flow.stars)
        out["is_true_alert"] = True
        out["is_false_positive"] = False
        if not out.get("primary_alert_name"):
            out["primary_alert_name"] = flow.alert_name
        out["decision"] = "care_flow_overlay"
        extra = f" | FLUXO {flow.program}: {flow.instruction}"
        out["rule_explanation"] = (out.get("rule_explanation") or "") + extra
    elif out.get("is_true_alert"):
        expl = out.get("rule_explanation") or ""
        if flow.instruction and flow.instruction not in expl:
            out["rule_explanation"] = expl + f" | FLUXO {flow.program}: {flow.instruction}"
    return out


def catalog() -> Dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "principle": "Doença isolada não cria alerta. Padrão fisiológico obrigatório.",
        "programs": [
            {
                "id": pid,
                "diseases": sorted(diseases),
                "source": SOURCES[pid],
            }
            for pid, diseases in PROGRAM_DISEASES.items()
        ],
    }
