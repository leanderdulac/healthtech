"""
Geração de dataset sintético a partir da matriz de alertas.

Classes:
  - true_alert + severity {leve, moderado, critico}
  - false_positive: anomalia isolada / limítrofe SEM match de regra
  - normal: vitais estáveis

O classificador aprende a separar FPs (não alertar) de verdadeiros positivos
com a severidade correta.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.clinical_intelligence.alert_discrepancy import (
    discrepancy_feature_flags,
    evaluate_discrepancy,
)
from src.clinical_intelligence.alert_matrix_rules import (
    ALERT_RULES,
    AlertMatrixEngine,
    VitalSnapshot,
)
from src.clinical_intelligence.next2u_context import (
    NEXT2U_CONTEXT_FEATURES,
    PatientContext,
    RULE_TO_NEXT2U,
    context_features,
)

FEATURE_COLUMNS = [
    "pas",
    "pad",
    "hr",
    "spo2",
    "temp_c",
    "glucose_mgdl",
    "steps_drop_pct",
    "sleep_worsen_pct",
    "hr_baseline_rise",
    "spo2_drop_points",
    "consciousness_altered",
    "map_approx",
    "pulse_pressure",
    # Discrepância amostra↔alerta (UI FP: crise + vitais estáveis)
    "disc_stable_core",
    "disc_hr_mid_stable",
    "disc_bp_phantom",
    "disc_glucose_phantom",
    "disc_ui_fp_pattern",
    "consecutive_valid",
    "rest",
    "fasting",
    "steps_interrupted",
    "sleep_hours",
    "steps_drop_days",
    "pas_rise_vs_basal",
    "pas_drop_vs_basal",
    "glucose_delta",
    # Next2U — risco de internação + concordância + confirmação
    *NEXT2U_CONTEXT_FEATURES,
]

SEVERITY_LABELS = ["none", "leve", "moderado", "critico"]
# is_false_positive: 1 = FP (não deve alertar), 0 = normal ou true alert


def _rng(seed: Optional[int] = None) -> random.Random:
    return random.Random(seed)


def _uniform(r: random.Random, lo: float, hi: float) -> float:
    return r.uniform(lo, hi)


def _sample_for_rule(rule_id: str, r: random.Random) -> VitalSnapshot:
    """Amostra vitais no interior das faixas da regra (com jitter seguro)."""
    if str(rule_id).startswith("n2u_"):
        from src.clinical_intelligence.next2u_bases import sample_for_base

        try:
            return sample_for_base(int(str(rule_id).split("_")[1]), r)
        except Exception:
            pass
    # Defaults normais; sobrescritos conforme regra
    v = VitalSnapshot(
        pas=120.0,
        pad=80.0,
        hr=72.0,
        spo2=98.0,
        temp_c=36.6,
        glucose_mgdl=100.0,
        steps_drop_pct=0.0,
        sleep_worsen_pct=0.0,
        hr_baseline_rise=0.0,
        spo2_drop_points=0.0,
        consciousness_altered=False,
    )

    samplers = {
        "pa_elev_1": lambda: VitalSnapshot(
            pas=_uniform(r, 140, 159),
            pad=_uniform(r, 90, 99),
            hr=_uniform(r, 91, 110),
            spo2=_uniform(r, 96, 99),
            temp_c=_uniform(r, 36.2, 37.2),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_elev_2": lambda: VitalSnapshot(
            pas=_uniform(r, 160, 179),
            pad=_uniform(r, 100, 109),
            hr=_uniform(r, 111, 130),
            spo2=_uniform(r, 95, 99),
            temp_c=_uniform(r, 36.2, 37.2),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_elev_3": lambda: VitalSnapshot(
            pas=_uniform(r, 180, 210),
            pad=_uniform(r, 110, 130),
            hr=_uniform(r, 111, 150),
            spo2=_uniform(r, 94, 99),
            temp_c=_uniform(r, 36.2, 37.5),
            glucose_mgdl=_uniform(r, 90, 180),
        ),
        "pa_elev_4": lambda: VitalSnapshot(
            pas=_uniform(r, 180, 210),
            pad=_uniform(r, 110, 130),
            hr=_uniform(r, 80, 110),
            spo2=_uniform(r, 85, 93),
            temp_c=_uniform(r, 36.2, 37.5),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_elev_5": lambda: VitalSnapshot(
            pas=_uniform(r, 180, 210),
            pad=_uniform(r, 110, 130),
            hr=_uniform(r, 80, 120),
            spo2=_uniform(r, 95, 99),
            temp_c=_uniform(r, 38.1, 40.0),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_elev_6": lambda: VitalSnapshot(
            pas=_uniform(r, 180, 210),
            pad=_uniform(r, 110, 130),
            hr=_uniform(r, 80, 120),
            spo2=_uniform(r, 95, 99),
            temp_c=_uniform(r, 36.2, 37.5),
            glucose_mgdl=_uniform(r, 250, 400),
        ),
        "pa_baixa_1": lambda: VitalSnapshot(
            pas=_uniform(r, 101, 110),
            pad=_uniform(r, 60, 75),
            hr=_uniform(r, 91, 110),
            spo2=_uniform(r, 96, 99),
            temp_c=_uniform(r, 36.2, 37.2),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_baixa_2": lambda: VitalSnapshot(
            pas=_uniform(r, 91, 100),
            pad=_uniform(r, 55, 70),
            hr=_uniform(r, 111, 130),
            spo2=_uniform(r, 95, 99),
            temp_c=_uniform(r, 36.2, 37.2),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_baixa_3": lambda: VitalSnapshot(
            pas=_uniform(r, 91, 100),
            pad=_uniform(r, 55, 70),
            hr=_uniform(r, 111, 150),
            spo2=_uniform(r, 95, 99),
            temp_c=_uniform(r, 38.1, 39.5),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_baixa_4": lambda: VitalSnapshot(
            pas=_uniform(r, 91, 100),
            pad=_uniform(r, 55, 70),
            hr=_uniform(r, 111, 150),
            spo2=_uniform(r, 85, 93),
            temp_c=_uniform(r, 36.2, 37.5),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_baixa_5": lambda: VitalSnapshot(
            pas=_uniform(r, 70, 90),
            pad=_uniform(r, 40, 60),
            hr=_uniform(r, 111, 160),
            spo2=_uniform(r, 94, 99),
            temp_c=_uniform(r, 36.2, 37.5),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "pa_baixa_6": lambda: VitalSnapshot(
            pas=_uniform(r, 70, 90),
            pad=_uniform(r, 40, 60),
            hr=_uniform(r, 70, 100),
            spo2=_uniform(r, 80, 91),
            temp_c=_uniform(r, 36.2, 37.5),
            glucose_mgdl=_uniform(r, 90, 140),
        ),
        "spo2_1": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 70, 90), spo2=_uniform(r, 95, 96), temp_c=36.6, glucose_mgdl=100
        ),
        "spo2_2": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 70, 90), spo2=_uniform(r, 93, 94), temp_c=36.6, glucose_mgdl=100
        ),
        "spo2_3": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 130), spo2=_uniform(r, 93, 94), temp_c=36.6, glucose_mgdl=100
        ),
        "spo2_4": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 140), spo2=_uniform(r, 92, 93), temp_c=_uniform(r, 38.1, 39.5), glucose_mgdl=100
        ),
        "spo2_5": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 70, 100), spo2=_uniform(r, 80, 91), temp_c=36.6, glucose_mgdl=100
        ),
        "spo2_6": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 150), spo2=_uniform(r, 80, 91), temp_c=36.6, glucose_mgdl=100
        ),
        "spo2_7": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 70, 100), spo2=_uniform(r, 80, 91), temp_c=_uniform(r, 38.1, 40), glucose_mgdl=100
        ),
        "temp_1": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 91, 110), spo2=98, temp_c=_uniform(r, 38.1, 39.0), glucose_mgdl=100
        ),
        "temp_2": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 130), spo2=98, temp_c=_uniform(r, 38.1, 39.0), glucose_mgdl=100
        ),
        "temp_3": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 140), spo2=_uniform(r, 88, 93), temp_c=_uniform(r, 38.1, 39.0), glucose_mgdl=100
        ),
        "temp_4": lambda: VitalSnapshot(
            pas=_uniform(r, 80, 100), pad=60, hr=_uniform(r, 111, 140), spo2=97, temp_c=_uniform(r, 38.1, 39.0), glucose_mgdl=100
        ),
        "temp_5": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 150), spo2=97, temp_c=_uniform(r, 39.1, 41.0), glucose_mgdl=100
        ),
        "temp_6": lambda: VitalSnapshot(
            pas=_uniform(r, 80, 100), pad=60, hr=_uniform(r, 111, 150), spo2=_uniform(r, 88, 93), temp_c=_uniform(r, 39.1, 41.0), glucose_mgdl=100
        ),
        "temp_7": lambda: VitalSnapshot(
            pas=_uniform(r, 80, 100), pad=55, hr=_uniform(r, 35, 50), spo2=97, temp_c=_uniform(r, 32.0, 35.0), glucose_mgdl=100
        ),
        "hypo_1": lambda: VitalSnapshot(
            pas=120, pad=80, hr=80, spo2=98, temp_c=36.6, glucose_mgdl=_uniform(r, 54, 69)
        ),
        "hypo_2": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 140), spo2=98, temp_c=36.6, glucose_mgdl=_uniform(r, 54, 69)
        ),
        "hypo_3": lambda: VitalSnapshot(
            pas=_uniform(r, 80, 100), pad=60, hr=90, spo2=98, temp_c=36.6, glucose_mgdl=_uniform(r, 54, 69)
        ),
        "hypo_4": lambda: VitalSnapshot(
            pas=120, pad=80, hr=85, spo2=98, temp_c=36.6, glucose_mgdl=_uniform(r, 30, 53.5)
        ),
        "hypo_5": lambda: VitalSnapshot(
            pas=_uniform(r, 85, 100),
            pad=60,
            hr=_uniform(r, 111, 140),
            spo2=98,
            temp_c=36.6,
            glucose_mgdl=_uniform(r, 30, 53.5),
            consciousness_altered=r.random() < 0.5,
        ),
        "hyper_1": lambda: VitalSnapshot(
            pas=120, pad=80, hr=80, spo2=98, temp_c=36.6, glucose_mgdl=_uniform(r, 181, 249)
        ),
        "hyper_2": lambda: VitalSnapshot(
            pas=120, pad=80, hr=80, spo2=98, temp_c=36.6, glucose_mgdl=_uniform(r, 250, 399)
        ),
        "hyper_3": lambda: VitalSnapshot(
            pas=120, pad=80, hr=85, spo2=98, temp_c=_uniform(r, 38.1, 39.5), glucose_mgdl=_uniform(r, 250, 399)
        ),
        "hyper_4": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 140), spo2=97, temp_c=_uniform(r, 38.1, 39.5), glucose_mgdl=_uniform(r, 250, 399)
        ),
        "hyper_5": lambda: VitalSnapshot(
            pas=_uniform(r, 80, 100), pad=60, hr=_uniform(r, 111, 140), spo2=97, temp_c=36.8, glucose_mgdl=_uniform(r, 250, 399)
        ),
        "hyper_6": lambda: VitalSnapshot(
            pas=120, pad=80, hr=90, spo2=97, temp_c=36.8, glucose_mgdl=_uniform(r, 400, 599)
        ),
        "hyper_7": lambda: VitalSnapshot(
            pas=120, pad=80, hr=95, spo2=96, temp_c=36.8, glucose_mgdl=_uniform(r, 600, 900)
        ),
        "fc_1": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 41, 50), spo2=98, temp_c=36.6, glucose_mgdl=100
        ),
        "fc_2": lambda: VitalSnapshot(
            pas=_uniform(r, 80, 100), pad=60, hr=_uniform(r, 41, 50), spo2=98, temp_c=36.6, glucose_mgdl=100
        ),
        "fc_3": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 41, 50), spo2=_uniform(r, 85, 93), temp_c=36.6, glucose_mgdl=100
        ),
        "fc_4": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 28, 40), spo2=98, temp_c=36.6, glucose_mgdl=100
        ),
        "fc_5": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 111, 130), spo2=98, temp_c=36.6, glucose_mgdl=100
        ),
        "fc_6": lambda: VitalSnapshot(
            pas=120, pad=80, hr=_uniform(r, 131, 180), spo2=98, temp_c=36.6, glucose_mgdl=100
        ),
        "fc_7": lambda: VitalSnapshot(
            pas=_uniform(r, 140, 170),
            pad=_uniform(r, 90, 105),
            hr=_uniform(r, 131, 180),
            spo2=_uniform(r, 90, 96),
            temp_c=_uniform(r, 38.0, 39.5),
            glucose_mgdl=100,
        ),
        "func_1": lambda: VitalSnapshot(
            pas=120,
            pad=80,
            hr=75,
            spo2=98,
            temp_c=36.6,
            glucose_mgdl=100,
            steps_drop_pct=_uniform(r, 40, 70),
            sleep_worsen_pct=_uniform(r, 30, 60),
        ),
        "func_2": lambda: VitalSnapshot(
            pas=120,
            pad=80,
            hr=85,
            spo2=98,
            temp_c=36.6,
            glucose_mgdl=100,
            steps_drop_pct=_uniform(r, 40, 70),
            sleep_worsen_pct=_uniform(r, 30, 60),
            hr_baseline_rise=_uniform(r, 15, 30),
        ),
        "func_3": lambda: VitalSnapshot(
            pas=120,
            pad=80,
            hr=80,
            spo2=96,
            temp_c=36.6,
            glucose_mgdl=100,
            steps_drop_pct=_uniform(r, 50, 80),
            spo2_drop_points=_uniform(r, 3, 8),
        ),
        "func_4": lambda: VitalSnapshot(
            pas=_uniform(r, 85, 100),
            pad=60,
            hr=_uniform(r, 111, 140),
            spo2=_uniform(r, 88, 93),
            temp_c=_uniform(r, 38.1, 39.5),
            glucose_mgdl=100,
            steps_drop_pct=_uniform(r, 40, 70),
            sleep_worsen_pct=_uniform(r, 30, 50),
        ),
        "func_5": lambda: VitalSnapshot(
            pas=_uniform(r, 140, 159),
            pad=_uniform(r, 90, 99),
            hr=_uniform(r, 91, 110),
            spo2=98,
            temp_c=36.6,
            glucose_mgdl=100,
            sleep_worsen_pct=_uniform(r, 30, 60),
        ),
        "func_6": lambda: VitalSnapshot(
            pas=_uniform(r, 160, 179),
            pad=_uniform(r, 100, 109),
            hr=_uniform(r, 111, 130),
            spo2=97,
            temp_c=36.6,
            glucose_mgdl=100,
            sleep_worsen_pct=_uniform(r, 30, 60),
        ),
    }

    if rule_id in samplers:
        return samplers[rule_id]()
    return v


def _fill_baseline_context(v: VitalSnapshot, r: random.Random) -> VitalSnapshot:
    """
    Preenche campos contextuais ausentes com valores estáveis realistas.

    Evita que zeros exatos em steps/sono (comuns em samples de regras PA/SpO2)
    se tornem proxy espúrio de true_alert no classificador.
    """
    if v.steps_drop_pct is None:
        v.steps_drop_pct = _uniform(r, 0, 12)
    if v.sleep_worsen_pct is None:
        v.sleep_worsen_pct = _uniform(r, 0, 12)
    if v.hr_baseline_rise is None:
        v.hr_baseline_rise = _uniform(r, 0, 6)
    if v.spo2_drop_points is None:
        v.spo2_drop_points = _uniform(r, 0, 1.2)
    if v.pas is None:
        v.pas = _uniform(r, 110, 125)
    if v.pad is None:
        v.pad = _uniform(r, 70, 82)
    if v.hr is None:
        v.hr = _uniform(r, 65, 85)
    if v.spo2 is None:
        v.spo2 = _uniform(r, 97, 99)
    if v.temp_c is None:
        v.temp_c = _uniform(r, 36.3, 37.0)
    if v.glucose_mgdl is None:
        v.glucose_mgdl = _uniform(r, 85, 120)
    return v


def _sample_normal(r: random.Random) -> VitalSnapshot:
    return VitalSnapshot(
        pas=_uniform(r, 105, 129),
        pad=_uniform(r, 65, 84),
        hr=_uniform(r, 60, 90),
        spo2=_uniform(r, 97, 100),
        temp_c=_uniform(r, 36.2, 37.2),
        glucose_mgdl=_uniform(r, 80, 139),
        steps_drop_pct=_uniform(r, 0, 15),
        sleep_worsen_pct=_uniform(r, 0, 15),
        hr_baseline_rise=_uniform(r, 0, 8),
        spo2_drop_points=_uniform(r, 0, 1.5),
        consciousness_altered=False,
    )


def _sample_ui_screenshot_fp(r: random.Random) -> Tuple[VitalSnapshot, Dict[str, str]]:
    """
    Padrão do print da UI: paciente 'CRÍTICO' com FC 78, temp 36.5, sono Boa,
    alertas 'crise hipertensiva' (FC 90) + 'hiperglicemia' — discrepância clássica.
    """
    v = VitalSnapshot(
        pas=_uniform(r, 185, 200),  # phantom PA alta (falso)
        pad=_uniform(r, 110, 125),
        hr=_uniform(r, 75, 92),  # amostra real estável / 90 no alerta
        spo2=_uniform(r, 97, 99),
        temp_c=_uniform(r, 36.3, 36.8),
        glucose_mgdl=_uniform(r, 185, 230),  # phantom hiperglicemia leve
        steps_drop_pct=_uniform(r, 0, 15),
        sleep_worsen_pct=_uniform(r, 0, 12),  # sono "Bom"
        hr_baseline_rise=_uniform(r, 0, 5),
        spo2_drop_points=_uniform(r, 0, 1),
    )
    meta = {"bp_source": "phantom", "glucose_source": "phantom"}
    return v, meta


def _sample_false_positive(r: random.Random) -> VitalSnapshot:
    """
    Anomalias isoladas / limítrofes que NÃO devem acionar a matriz
    (ou só acionariam ruído sem cruzamento completo).
    """
    kind = r.choice(
        [
            "borderline_hr",
            "borderline_spo2",
            "prehyper",
            "low_grade_temp",
            "pre_hyperglycemia",
            "mild_steps",
            "isolated_hr_100",
            "ui_screenshot_fp",
            "phantom_crisis_stable_hr",
            "phantom_hyper_stable",
        ]
    )
    base = _sample_normal(r)
    if kind == "ui_screenshot_fp" or kind == "phantom_crisis_stable_hr":
        v, _ = _sample_ui_screenshot_fp(r)
        return v
    if kind == "phantom_hyper_stable":
        base.hr = _uniform(r, 70, 88)
        base.temp_c = _uniform(r, 36.3, 36.9)
        base.spo2 = _uniform(r, 97, 99)
        base.pas = _uniform(r, 110, 125)
        base.pad = _uniform(r, 70, 82)
        base.glucose_mgdl = _uniform(r, 190, 240)
        base.sleep_worsen_pct = _uniform(r, 0, 10)
        return base
    if kind == "borderline_hr":
        base.hr = _uniform(r, 100, 110)  # taquicardia isolada leve sem PA/SpO2 críticos
        base.pas = _uniform(r, 110, 129)
        base.pad = _uniform(r, 70, 85)
        base.spo2 = _uniform(r, 97, 99)
        base.temp_c = _uniform(r, 36.3, 37.2)
    elif kind == "borderline_spo2":
        base.spo2 = _uniform(r, 96.2, 97.0)  # fora de 95-96 isolado da matriz
        base.hr = _uniform(r, 70, 90)
    elif kind == "prehyper":
        base.pas = _uniform(r, 130, 139)
        base.pad = _uniform(r, 80, 89)
        base.hr = _uniform(r, 70, 90)
    elif kind == "low_grade_temp":
        base.temp_c = _uniform(r, 37.5, 38.05)
        base.hr = _uniform(r, 70, 90)
    elif kind == "pre_hyperglycemia":
        base.glucose_mgdl = _uniform(r, 140, 180)
        base.hr = _uniform(r, 70, 90)
        base.temp_c = _uniform(r, 36.3, 37.2)
    elif kind == "mild_steps":
        base.steps_drop_pct = _uniform(r, 20, 39)
        base.sleep_worsen_pct = _uniform(r, 10, 25)
        base.hr = _uniform(r, 70, 90)
    else:
        base.hr = _uniform(r, 100, 109)
        base.pas = 118
        base.pad = 76
        base.spo2 = 98
        base.temp_c = 36.7
        base.glucose_mgdl = 105
    return base


def _sample_patient_context(
    r: random.Random,
    rule_id: str = "",
    *,
    force_normal: bool = False,
) -> PatientContext:
    """Amostra de prontuário alinhada à tabela de promoção Next2U."""
    if force_normal:
        return PatientContext(data_valid=True)
    profile_id, _ = RULE_TO_NEXT2U.get(rule_id, (1, 1))
    from src.clinical_intelligence.next2u_context import PROFILE_CONCORDANCE

    spec = PROFILE_CONCORDANCE.get(profile_id, {"diseases": set(), "meds": set()})
    roll = r.random()
    diseases: List[str] = []
    meds: List[str] = []
    confirm = False
    progress = False
    n_meds = r.randint(1, 4)
    hosp = False
    alone = False
    mobility = False
    if roll < 0.35:
        # baixo risco, sem promoção
        diseases = r.sample(list(spec["diseases"]), k=min(1, len(spec["diseases"]))) if spec["diseases"] and r.random() < 0.4 else []
    elif roll < 0.65:
        # moderado com concordância ± confirmação
        diseases = r.sample(list(spec["diseases"]), k=min(2, len(spec["diseases"]))) if spec["diseases"] else []
        if spec["meds"] and r.random() < 0.6:
            meds = r.sample(list(spec["meds"]), k=1)
        n_meds = r.randint(3, 7)
        confirm = r.random() < 0.5
        hosp = r.random() < 0.3
    elif roll < 0.85:
        # alto risco
        diseases = r.sample(list(spec["diseases"]), k=min(3, len(spec["diseases"]))) if spec["diseases"] else ["hf", "ckd"]
        if spec["meds"]:
            meds = r.sample(list(spec["meds"]), k=min(2, len(spec["meds"])))
        n_meds = r.randint(6, 10)
        confirm = r.random() < 0.7
        progress = r.random() < 0.35
        hosp = True
        mobility = r.random() < 0.4
    else:
        # crítico
        diseases = list(spec["diseases"])[:4] or ["hf", "neoplasm", "ckd"]
        meds = list(spec["meds"])[:2]
        n_meds = r.randint(7, 12)
        confirm = True
        progress = r.random() < 0.7
        hosp = True
        alone = r.random() < 0.5
        mobility = True
    return PatientContext(
        diseases=diseases,
        medications=meds,
        n_continuous_meds=n_meds,
        reduced_mobility=mobility,
        hospitalized_last_6_months=hosp,
        lives_alone=alone,
        confirmation_or_persistence=confirm,
        clinical_progression=progress,
        data_valid=True,
    )


def _feats_for(
    vitals: VitalSnapshot,
    *,
    bp_source: str = "measured",
    glucose_source: str = "measured",
    context: Optional[PatientContext] = None,
    rule_id: str = "",
) -> Dict[str, float]:
    feats = vitals.to_feature_dict()
    feats.update(
        discrepancy_feature_flags(
            vitals, bp_source=bp_source, glucose_source=glucose_source
        )
    )
    profile_id = RULE_TO_NEXT2U.get(rule_id, (1, 1))[0]
    feats.update(context_features(context, profile_id=profile_id))
    return feats


def generate_dataset(
    n_per_rule: int = 80,
    n_normal: int = 1500,
    n_false_positive: int = 2000,
    n_ui_fp: int = 800,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Gera DataFrame com features + labels.

    Labels:
      - severity: none | leve | moderado | critico
      - is_true_alert: 0/1
      - is_false_positive: 1 se FP (inclui discrepância UI/phantom)
      - rule_id: regra alvo (se true alert) ou ''
    """
    r = _rng(seed)
    engine = AlertMatrixEngine()
    rows: List[Dict[str, Any]] = []

    # True positives por regra (BP/glicose "medidos") + contexto Next2U
    for rule in ALERT_RULES:
        rid = rule["rule_id"]
        for _ in range(n_per_rule):
            vitals = _fill_baseline_context(_sample_for_rule(rid, r), r)
            ctx = _sample_patient_context(r, rid)
            result = engine.evaluate(vitals, context=ctx)
            attempts = 0
            while not result.is_true_alert and attempts < 8:
                vitals = _fill_baseline_context(_sample_for_rule(rid, r), r)
                ctx = _sample_patient_context(r, rid)
                result = engine.evaluate(vitals, context=ctx)
                attempts += 1
            if not result.is_true_alert:
                continue
            # True alerts medidos não devem ser suprimidos por discrepância phantom
            disc = evaluate_discrepancy(
                vitals,
                [h.to_dict() for h in result.hits],
                primary_rule_id=result.primary_rule_id,
                primary_alert_name=result.primary_alert_name,
                bp_source="measured",
                glucose_source="measured",
                bp_reliable=True,
                glucose_reliable=True,
            )
            if disc.should_suppress_alert:
                continue
            feats = _feats_for(
                vitals,
                bp_source="measured",
                glucose_source="measured",
                context=ctx,
                rule_id=rid,
            )
            rows.append(
                {
                    **feats,
                    "severity": result.max_severity,
                    "is_true_alert": 1,
                    "is_false_positive": 0,
                    "rule_id": result.primary_rule_id or rid,
                    "alert_name": result.primary_alert_name or "",
                    "sample_type": "true_alert",
                    "next2u_id": result.next2u_id or "",
                    "stars": result.stars,
                }
            )

    # Normais — inclusive escore alto SEM padrão fisiológico (trava de segurança)
    for _ in range(n_normal):
        vitals = _sample_normal(r)
        ctx = (
            _sample_patient_context(r, force_normal=False)
            if r.random() < 0.25
            else _sample_patient_context(r, force_normal=True)
        )
        result = engine.evaluate(vitals, context=ctx)
        feats = _feats_for(
            vitals,
            bp_source="measured",
            glucose_source="measured",
            context=ctx,
        )
        rows.append(
            {
                **feats,
                "severity": result.max_severity if result.is_true_alert else "none",
                "is_true_alert": int(result.is_true_alert),
                "is_false_positive": 0,
                "rule_id": result.primary_rule_id or "",
                "alert_name": result.primary_alert_name or "",
                "sample_type": "normal",
                "next2u_id": result.next2u_id or "",
                "stars": result.stars,
            }
        )

    # Falsos positivos genéricos
    for _ in range(n_false_positive):
        vitals = _fill_baseline_context(_sample_false_positive(r), r)
        ctx = _sample_patient_context(r, force_normal=r.random() < 0.5)
        result = engine.evaluate(vitals, context=ctx)
        # UI/phantom pattern: marcar fontes phantom
        is_ui = (
            vitals.hr is not None
            and 70 <= vitals.hr <= 92
            and vitals.pas is not None
            and vitals.pas >= 180
        )
        bp_src = "phantom" if is_ui else "unknown"
        glu_src = "phantom" if (vitals.glucose_mgdl or 0) >= 181 and is_ui else "unknown"
        disc = evaluate_discrepancy(
            vitals,
            [h.to_dict() for h in result.hits],
            primary_rule_id=result.primary_rule_id,
            primary_alert_name=result.primary_alert_name,
            bp_source=bp_src,
            glucose_source=glu_src,
            bp_reliable=bp_src != "phantom",
            glucose_reliable=glu_src != "phantom",
        )
        feats = _feats_for(
            vitals, bp_source=bp_src, glucose_source=glu_src, context=ctx
        )
        if result.is_true_alert and not disc.should_suppress_alert:
            rows.append(
                {
                    **feats,
                    "severity": result.max_severity,
                    "is_true_alert": 1,
                    "is_false_positive": 0,
                    "rule_id": result.primary_rule_id or "",
                    "alert_name": result.primary_alert_name or "",
                    "sample_type": "true_alert_from_fp_sampler",
                    "next2u_id": result.next2u_id or "",
                    "stars": result.stars,
                }
            )
        else:
            rows.append(
                {
                    **feats,
                    "severity": "none",
                    "is_true_alert": 0,
                    "is_false_positive": 1,
                    "rule_id": "",
                    "alert_name": "",
                    "sample_type": "false_positive",
                    "next2u_id": "",
                    "stars": 0,
                }
            )

    # Extra: padrões explícitos do screenshot (crise + hiperglicemia fantasma + estável)
    for _ in range(n_ui_fp):
        vitals, meta = _sample_ui_screenshot_fp(r)
        ctx = _sample_patient_context(r, force_normal=True)
        result = engine.evaluate(vitals, context=ctx)
        disc = evaluate_discrepancy(
            vitals,
            [h.to_dict() for h in result.hits],
            primary_rule_id=result.primary_rule_id,
            primary_alert_name=result.primary_alert_name,
            bp_source=meta["bp_source"],
            glucose_source=meta["glucose_source"],
            bp_reliable=False,
            glucose_reliable=False,
        )
        feats = _feats_for(
            vitals,
            bp_source=meta["bp_source"],
            glucose_source=meta["glucose_source"],
            context=ctx,
        )
        # Sempre FP rotulado — mesmo se regras phantom batessem
        rows.append(
            {
                **feats,
                "severity": "none",
                "is_true_alert": 0,
                "is_false_positive": 1,
                "rule_id": "",
                "alert_name": "",
                "sample_type": "ui_screenshot_fp",
                "next2u_id": "",
                "stars": 0,
            }
        )

    df = pd.DataFrame(rows)
    # garantir colunas de disc
    for c in FEATURE_COLUMNS:
        if c not in df.columns:
            df[c] = 0.0
    return df
