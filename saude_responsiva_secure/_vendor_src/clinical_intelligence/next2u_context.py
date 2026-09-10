"""
Contexto clínico Next2U: escore de risco de internação, perfis 1–12
e concordância doença/medicamento.

Fonte: DOCUMENTO TÉCNICO · NEXT2U SAÚDE · 16/08/2026
Trava: escore, doença ou medicamento isolados NÃO criam alerta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------

DISEASE_ALIASES: Dict[str, str] = {
    "has": "hypertension",
    "hipertensao": "hypertension",
    "hipertensão": "hypertension",
    "hipertensão arterial sistêmica": "hypertension",
    "dac": "cad",
    "doenca coronariana": "cad",
    "doença coronariana": "cad",
    "icc": "hf",
    "insuficiencia cardiaca": "hf",
    "insuficiência cardíaca": "hf",
    "drc": "ckd",
    "doenca renal cronica": "ckd",
    "doença renal crônica": "ckd",
    "dm": "diabetes",
    "diabetes": "diabetes",
    "diabetes descompensado": "diabetes_decompensated",
    "dpoc": "copd",
    "doenca pulmonar obstrutiva cronica": "copd",
    "doença pulmonar obstrutiva crônica": "copd",
    "hepatopatia": "liver_failure",
    "hepatopatias": "liver_failure",
    "cirrose": "liver_failure",
    "insuficiencia hepatica": "liver_failure",
    "insuficiência hepática": "liver_failure",
    "gestacao": "pregnancy",
    "gestação": "pregnancy",
    "gravidez": "pregnancy",
    "obstetrica": "pregnancy",
    "obstétrica": "pregnancy",
    "prenhez": "pregnancy",
    "neoplasia": "neoplasm",
    "cancer": "neoplasm",
    "demencia": "dementia",
    "demência": "dementia",
    "alzheimer": "alzheimer",
    "depressao": "depression",
    "depressão": "depression",
    "infeccao": "infection",
    "infecção": "infection",
    "infecção respiratória": "infection",
}

MED_ALIASES: Dict[str, str] = {
    "aine": "nsaid",
    "anti-inflamatorio": "nsaid",
    "corticoide": "systemic_corticosteroid",
    "corticoide sistemico": "systemic_corticosteroid",
    "descongestionante": "decongestant",
    "simpaticomimetico": "decongestant",
    "diuretico": "diuretic",
    "ieca": "acei",
    "bra": "arb",
    "arni": "arni",
    "nitrato": "nitrate",
    "betabloqueador": "betablocker",
    "verapamil": "ndhp_ccb",
    "diltiazem": "ndhp_ccb",
    "iSGLT2": "sglt2i",
    "sglt2": "sglt2i",
    "opioide": "opioid",
    "benzodiazepinico": "benzo",
    "gabapentinoide": "gabapentinoid",
    "insulina": "insulin",
    "sulfonilureia": "sulfonylurea",
    "quimioterapia": "chemo",
    "imunossupressor": "immunosuppressant",
    "antitermico": "antipyretic",
    "anticoagulante": "anticoagulant",
    "antiagregante": "antiplatelet",
}


def _norm_token(value: str) -> str:
    v = (value or "").strip().lower()
    v = (
        v.replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
    return v


def canonicalize_disease(name: str) -> str:
    raw = name.strip().lower()
    if raw in DISEASE_ALIASES:
        return DISEASE_ALIASES[raw]
    key = _norm_token(raw)
    return DISEASE_ALIASES.get(key, key.replace(" ", "_"))


def canonicalize_med(name: str) -> str:
    raw = name.strip().lower()
    if raw in MED_ALIASES:
        return MED_ALIASES[raw]
    key = _norm_token(raw)
    return MED_ALIASES.get(key, key.replace(" ", "_"))


# Perfil → doenças / medicamentos concordantes (documento §6)
PROFILE_CONCORDANCE: Dict[int, Dict[str, Set[str]]] = {
    1: {
        "diseases": {
            "hypertension", "cad", "hf", "ckd", "diabetes", "diabetes_decompensated",
        },
        "meds": {
            "nsaid", "systemic_corticosteroid", "decongestant", "stimulant", "psychotropic",
        },
    },
    2: {
        "diseases": {
            "hf", "ckd", "liver_failure", "diabetes", "neoplasm", "reduced_mobility",
        },
        "meds": {
            "diuretic", "acei", "arb", "arni", "nitrate", "alphablocker", "betablocker",
            "ndhp_ccb", "sglt2i", "opioid", "tca",
        },
    },
    3: {
        "diseases": {"copd", "hf", "neoplasm", "infection"},
        "meds": {"opioid", "benzo", "gabapentinoid", "cns_depressant"},
    },
    4: {
        "diseases": {
            "neoplasm", "diabetes", "copd", "ckd", "liver_failure",
        },
        "meds": {"chemo", "immunosuppressant", "systemic_corticosteroid", "antipyretic"},
    },
    5: {
        "diseases": {
            "diabetes", "ckd", "liver_failure", "dementia", "alzheimer", "depression",
            "reduced_mobility",
        },
        "meds": {"insulin", "sulfonylurea", "meglitinide", "betablocker", "clonidine"},
    },
    6: {
        "diseases": {"diabetes", "diabetes_decompensated", "infection", "neoplasm", "ckd"},
        "meds": {
            "systemic_corticosteroid", "atypical_antipsychotic", "decongestant",
            "beta2_agonist", "diuretic", "thyroid_hormone",
        },
    },
    7: {
        "diseases": {"cad", "hf", "ckd", "liver_failure"},
        "meds": {
            "betablocker", "ndhp_ccb", "digoxin", "amiodarone", "antiarrhythmic", "clonidine",
        },
    },
    8: {
        "diseases": {"copd", "hf", "cad", "infection", "neoplasm"},
        "meds": {
            "beta2_agonist", "decongestant", "stimulant", "thyroid_hormone", "psychotropic",
        },
    },
    9: {
        "diseases": {
            "dementia", "alzheimer", "depression", "neoplasm", "copd", "hf",
            "reduced_mobility",
        },
        "meds": {
            "benzo", "z_drug", "opioid", "gabapentinoid", "antipsychotic", "antidepressant",
            "antiepileptic", "anticholinergic", "systemic_corticosteroid", "stimulant",
        },
    },
    10: {
        "diseases": {
            "neoplasm", "diabetes", "copd", "ckd", "liver_failure",
        },
        "meds": {"chemo", "immunosuppressant", "systemic_corticosteroid", "antipyretic"},
    },
    11: {
        "diseases": {
            "diabetes", "hf", "ckd", "liver_failure", "neoplasm", "reduced_mobility",
            "dementia", "alzheimer", "depression",
        },
        "meds": {
            "diuretic", "sglt2i", "acei", "arb", "arni", "nitrate", "laxative",
        },
    },
    12: {
        "diseases": {
            "dementia", "alzheimer", "depression", "reduced_mobility", "cad", "hf",
            "diabetes", "ckd", "neoplasm",
        },
        "meds": {
            "benzo", "z_drug", "opioid", "gabapentinoid", "antipsychotic", "antidepressant",
            "antiepileptic", "diuretic", "acei", "arb", "insulin", "sulfonylurea",
            "anticoagulant", "antiplatelet",
        },
    },
}

def _profile_for_base(base_id: int) -> int:
    ranges = (
        (15, 1), (29, 2), (44, 3), (60, 4), (72, 5), (86, 6),
        (90, 7), (102, 8), (116, 9), (130, 10), (144, 11), (158, 12),
    )
    for hi, prof in ranges:
        if base_id <= hi:
            return prof
    return 1


def _build_rule_map() -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    for i in range(1, 159):
        out[f"n2u_{i:03d}"] = (_profile_for_base(i), i)
    legacy = {
        "pa_elev_1": 1, "pa_elev_2": 2, "pa_elev_3": 3, "pa_elev_4": 4,
        "pa_elev_5": 5, "pa_elev_6": 6,
        "pa_baixa_1": 16, "pa_baixa_2": 17, "pa_baixa_3": 18, "pa_baixa_4": 19,
        "pa_baixa_5": 20, "pa_baixa_6": 21,
        "spo2_1": 30, "spo2_2": 31, "spo2_3": 32, "spo2_4": 33, "spo2_5": 34,
        "spo2_6": 35, "spo2_7": 36,
        "temp_1": 45, "temp_2": 46, "temp_3": 47, "temp_4": 48, "temp_5": 49,
        "temp_6": 50, "temp_7": 51,
        "hypo_1": 61, "hypo_2": 62, "hypo_3": 63, "hypo_4": 64, "hypo_5": 65,
        "hyper_1": 73, "hyper_2": 74, "hyper_3": 75, "hyper_4": 76,
        "hyper_5": 77, "hyper_6": 78, "hyper_7": 79,
        "fc_1": 87, "fc_2": 88, "fc_3": 89, "fc_4": 90, "fc_5": 91,
        "fc_6": 92, "fc_7": 93,
        "func_1": 103, "func_2": 104, "func_3": 105, "func_4": 106,
        "func_5": 107, "func_6": 108,
    }
    for rid, base in legacy.items():
        out[rid] = out[f"n2u_{base:03d}"]
    return out


RULE_TO_NEXT2U: Dict[str, Tuple[int, int]] = _build_rule_map()


@dataclass
class PatientContext:
    """Contexto de prontuário / operação para ramificar a matriz."""

    diseases: List[str] = field(default_factory=list)
    medications: List[str] = field(default_factory=list)
    n_continuous_meds: int = 0
    reduced_mobility: bool = False
    hospitalized_last_6_months: bool = False
    lives_alone: bool = False
    no_capable_caregiver: bool = False
    data_valid: bool = True
    confirmation_or_persistence: bool = False
    clinical_progression: bool = False
    symptoms: bool = False

    def __post_init__(self) -> None:
        self.diseases = [canonicalize_disease(d) for d in self.diseases]
        self.medications = [canonicalize_med(m) for m in self.medications]
        if self.reduced_mobility and "reduced_mobility" not in self.diseases:
            self.diseases.append("reduced_mobility")

    @property
    def disease_set(self) -> Set[str]:
        return set(self.diseases)

    @property
    def med_set(self) -> Set[str]:
        return set(self.medications)

    @property
    def social_isolation(self) -> bool:
        return self.lives_alone or self.no_capable_caregiver

    @property
    def polypharmacy(self) -> bool:
        return self.n_continuous_meds > 5

    @property
    def n_active_diseases(self) -> int:
        return len(self.disease_set)

    @classmethod
    def from_payload(cls, raw: Optional[Dict] = None) -> "PatientContext":
        data = raw or {}
        ctx = data.get("clinical_context") or data.get("patient_context") or data
        if not isinstance(ctx, dict):
            ctx = {}
        diseases = ctx.get("diseases") or ctx.get("conditions") or []
        meds = ctx.get("medications") or ctx.get("meds") or []
        if isinstance(diseases, str):
            diseases = [diseases]
        if isinstance(meds, str):
            meds = [meds]
        n_meds = ctx.get("n_continuous_meds")
        if n_meds is None:
            n_meds = len(meds)
        return cls(
            diseases=list(diseases),
            medications=list(meds),
            n_continuous_meds=int(n_meds or 0),
            reduced_mobility=bool(ctx.get("reduced_mobility")),
            hospitalized_last_6_months=bool(
                ctx.get("hospitalized_last_6_months") or ctx.get("recent_admission")
            ),
            lives_alone=bool(ctx.get("lives_alone") or ctx.get("social_isolation")),
            no_capable_caregiver=bool(ctx.get("no_capable_caregiver")),
            data_valid=ctx.get("data_valid", True) is not False,
            confirmation_or_persistence=bool(
                ctx.get("confirmation_or_persistence") or ctx.get("confirmed")
            ),
            clinical_progression=bool(
                ctx.get("clinical_progression") or ctx.get("progression")
            ),
            symptoms=bool(
                ctx.get("symptoms")
                or ctx.get("sintomatico")
                or ctx.get("sintomas")
                or ctx.get("symptomatic")
            ),
        )


def hospitalization_score(ctx: PatientContext) -> int:
    """Pontuação de risco de internação (documento §2). Medicamento específico não pontua."""
    d = ctx.disease_set
    score = 0
    if len(d) >= 3:
        score += 5  # multimorbidade
    if d & {"dementia", "alzheimer", "depression"}:
        score += 4
    if d & {"hf", "liver_failure"}:
        score += 4
    if "neoplasm" in d:
        score += 3
    if d & {"copd", "ckd"}:
        score += 3
    if "diabetes_decompensated" in d or "cad" in d:
        score += 2
    elif "diabetes" in d and "cad" not in d:
        # diabetes simples: o documento pontua "descompensado" com 2;
        # CAD também 2. Diabetes compensado não duplica se já contou descompensado.
        pass
    if ctx.reduced_mobility or "reduced_mobility" in d:
        score += 1
    if ctx.polypharmacy:
        score += 2
    if ctx.hospitalized_last_6_months:
        score += 3
    if ctx.social_isolation:
        score += 3
    return score


def risk_band(score: int) -> str:
    if score <= 5:
        return "baixo"
    if score <= 10:
        return "moderado"
    if score <= 15:
        return "alto"
    return "critico"


def concordance(ctx: PatientContext, profile_id: int) -> Tuple[bool, bool]:
    spec = PROFILE_CONCORDANCE.get(profile_id, {"diseases": set(), "meds": set()})
    disease_ok = bool(ctx.disease_set & spec["diseases"]) or (
        len(ctx.disease_set) >= 3 and "multimorbidity" in {
            "multimorbidity",
        }
    )
    # multimorbidade é fator de todos os perfis
    if len(ctx.disease_set) >= 3:
        disease_ok = True
    med_ok = bool(ctx.med_set & spec["meds"])
    return disease_ok, med_ok


def context_features(ctx: Optional[PatientContext], profile_id: int = 1) -> Dict[str, float]:
    if ctx is None:
        return {
            "hosp_score": 0.0,
            "risk_band_code": 0.0,
            "disease_concordant": 0.0,
            "med_concordant": 0.0,
            "confirmation": 0.0,
            "clinical_progression": 0.0,
            "social_isolation": 0.0,
            "polypharmacy": 0.0,
            "n_active_diseases": 0.0,
            "n_continuous_meds": 0.0,
            "data_valid": 1.0,
        }
    score = hospitalization_score(ctx)
    band = risk_band(score)
    band_code = {"baixo": 0.0, "moderado": 1.0, "alto": 2.0, "critico": 3.0}[band]
    d_ok, m_ok = concordance(ctx, profile_id)
    return {
        "hosp_score": float(score),
        "risk_band_code": band_code,
        "disease_concordant": 1.0 if d_ok else 0.0,
        "med_concordant": 1.0 if m_ok else 0.0,
        "confirmation": 1.0 if ctx.confirmation_or_persistence else 0.0,
        "clinical_progression": 1.0 if ctx.clinical_progression else 0.0,
        "social_isolation": 1.0 if ctx.social_isolation else 0.0,
        "polypharmacy": 1.0 if ctx.polypharmacy else 0.0,
        "n_active_diseases": float(ctx.n_active_diseases),
        "n_continuous_meds": float(ctx.n_continuous_meds),
        "data_valid": 1.0 if ctx.data_valid else 0.0,
    }


NEXT2U_CONTEXT_FEATURES: Sequence[str] = (
    "hosp_score",
    "risk_band_code",
    "disease_concordant",
    "med_concordant",
    "confirmation",
    "clinical_progression",
    "social_isolation",
    "polypharmacy",
    "n_active_diseases",
    "n_continuous_meds",
    "data_valid",
)
