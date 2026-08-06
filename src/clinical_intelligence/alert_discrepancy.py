"""
Detecção de discrepância entre alertas da matriz e as amostras fisiológicas atuais.

Caso de UI (falso positivo típico):
  - Badge CRÍTICO / "Possível crise hipertensiva"
  - FC atual 78 bpm (há 5 min), temperatura 36,5 °C, sono Bom, passos ok
  - Alerta exibe FC 90 bpm como se sustentasse crise
  - Segundo alerta "Possível hiperglicemia" sem glicemia medida (só phantom)

Regras de inconsistência → forçar supressão / FP, mesmo se alguma regra
foi acionada por estimativa phantom ou amostra desatualizada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.clinical_intelligence.alert_matrix_rules import VitalSnapshot


@dataclass
class DiscrepancyResult:
    is_discrepant: bool
    reasons: List[str]
    should_suppress_alert: bool
    confidence_penalty: float  # 0–1, multiplica confiança do alerta

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_discrepant": self.is_discrepant,
            "reasons": self.reasons,
            "should_suppress_alert": self.should_suppress_alert,
            "confidence_penalty": self.confidence_penalty,
        }


def _stable_core(v: VitalSnapshot) -> bool:
    """Vitais centrais compatíveis com paciente estável na UI."""
    hr_ok = v.hr is not None and 55 <= v.hr <= 95
    spo2_ok = v.spo2 is None or v.spo2 >= 96
    temp_ok = v.temp_c is None or (35.5 <= v.temp_c <= 37.4)
    # PA não crítica se medida
    pa_ok = True
    if v.pas is not None:
        pa_ok = 95 <= v.pas < 160
    if v.pad is not None:
        pa_ok = pa_ok and 55 <= v.pad < 100
    return hr_ok and spo2_ok and temp_ok and pa_ok


def _rule_ids(hits: List[Dict[str, Any]]) -> List[str]:
    return [h.get("rule_id") or "" for h in hits]


def evaluate_discrepancy(
    vitals: VitalSnapshot,
    rule_hits: List[Dict[str, Any]],
    *,
    primary_rule_id: Optional[str] = None,
    primary_alert_name: Optional[str] = None,
    bp_source: str = "unknown",  # measured | phantom | unknown
    glucose_source: str = "unknown",
    glucose_reliable: bool = True,
    bp_reliable: bool = True,
) -> DiscrepancyResult:
    """
    Avalia se o conjunto de hits/alerta contraria as amostras atuais.
    """
    reasons: List[str] = []
    suppress = False
    penalty = 1.0
    rids = set(_rule_ids(rule_hits))
    if primary_rule_id:
        rids.add(primary_rule_id)

    name = (primary_alert_name or "").lower()
    hypertensive_rules = {r for r in rids if r.startswith("pa_elev_")}
    hypergly_rules = {r for r in rids if r.startswith("hyper_")}
    hypo_rules = {r for r in rids if r.startswith("hypo_")}

    # --- 1. Crise/descompensação hipertensiva sem suporte nas amostras ---
    if hypertensive_rules or "hipertens" in name or "pressóric" in name:
        # Crise com taquicardia exige FC ≥ 111 (regras pa_elev_2/3)
        needs_tachy = any(r in hypertensive_rules for r in ("pa_elev_2", "pa_elev_3"))
        if needs_tachy and vitals.hr is not None and vitals.hr < 111:
            reasons.append(
                f"Alerta hipertensivo com taquicardia, mas FC atual={vitals.hr:.0f} < 111"
            )
            suppress = True
            penalty *= 0.15

        # Crise crítica exige PA elevada; se BP phantom/não confiável e FC estável → FP
        if bp_source == "phantom" or not bp_reliable:
            if vitals.hr is not None and vitals.hr <= 95 and _stable_core(vitals):
                reasons.append(
                    "PA de origem phantom/não confiável com FC e vitais estáveis "
                    "(padrão UI: crise hipertensiva + FC 78–90)"
                )
                suppress = True
                penalty *= 0.1

        # Nome sugere crise mas PAS/PAD não atingem limiar crítico
        if "crise" in name or any(r in ("pa_elev_3", "pa_elev_4", "pa_elev_5", "pa_elev_6") for r in rids):
            pas_ok = vitals.pas is not None and vitals.pas >= 180
            pad_ok = vitals.pad is not None and vitals.pad >= 110
            if not (pas_ok and pad_ok):
                if vitals.hr is not None and vitals.hr < 111:
                    reasons.append(
                        "Rótulo de crise hipertensiva sem PAS≥180/PAD≥110 e sem taquicardia"
                    )
                    suppress = True
                    penalty *= 0.12

        # FC exibida no alerta (~90) vs amostra atual estável (~78) — ambas sem crise
        if vitals.hr is not None and 70 <= vitals.hr <= 95 and _stable_core(vitals):
            if any(r in ("pa_elev_2", "pa_elev_3") for r in rids):
                reasons.append(
                    "Vitais estáveis (FC 70–95, temp normal) incompatíveis com "
                    "descompensação hipertensiva com taquicardia"
                )
                suppress = True
                penalty *= 0.1

    # --- 2. Hiperglicemia só por phantom não confiável ---
    if hypergly_rules or "hiperglicemia" in name or "hiperglicêm" in name:
        if glucose_source == "phantom" or not glucose_reliable:
            if _stable_core(vitals) and (vitals.hr is None or vitals.hr < 111):
                reasons.append(
                    "Hiperglicemia inferida só por phantom não confiável com paciente estável"
                )
                suppress = True
                penalty *= 0.15
        # Glicemia phantom em faixa leve (181–249) + estável → não escalar atenção
        if (
            vitals.glucose_mgdl is not None
            and 181 <= vitals.glucose_mgdl < 250
            and _stable_core(vitals)
            and (glucose_source == "phantom" or not glucose_reliable)
        ):
            reasons.append("Hiperglicemia leve só por estimativa, sem descompensação clínica")
            suppress = True
            penalty *= 0.2

    # --- 3. Hipoglicemia phantom ---
    if hypo_rules and (glucose_source == "phantom" or not glucose_reliable):
        if vitals.hr is not None and 60 <= vitals.hr <= 100 and _stable_core(vitals):
            reasons.append("Hipoglicemia por phantom com FC/vitais estáveis")
            suppress = True
            penalty *= 0.2

    # --- 4. Severidade crítica com amostra global estável ---
    critical_hits = [h for h in rule_hits if h.get("severity") == "critico"]
    if critical_hits and _stable_core(vitals):
        # SpO2 crítico real: spo2 ≤ 91 não é "estável" — _stable_core exige ≥96
        # Temp febre já excluída
        # Se ainda assim critical_hits com core estável → quase sempre phantom PA/glicose
        only_metabolic_or_pa = all(
            (h.get("rule_id") or "").startswith(("pa_elev_", "hyper_", "hypo_"))
            for h in critical_hits
        )
        if only_metabolic_or_pa and (
            bp_source == "phantom"
            or glucose_source == "phantom"
            or not bp_reliable
            or not glucose_reliable
        ):
            reasons.append(
                "Alerta crítico metabólico/pressórico com amostra wearable estável "
                "(FC/temp/SpO2) — discrepância amostra vs alerta"
            )
            suppress = True
            penalty *= 0.1

    # --- 5. Caso canônico da UI (screenshot) ---
    # FC 78, temp 36.5, sem SpO2 baixa, sono bom, passos ok + alerta crise/hiperglicemia
    if (
        vitals.hr is not None
        and 70 <= vitals.hr <= 92
        and (vitals.temp_c is None or 36.0 <= vitals.temp_c <= 37.2)
        and (vitals.spo2 is None or vitals.spo2 >= 96)
        and (vitals.steps_drop_pct is None or vitals.steps_drop_pct < 25)
        and (vitals.sleep_worsen_pct is None or vitals.sleep_worsen_pct < 25)
    ):
        if hypertensive_rules or hypergly_rules or "crise" in name or "hiperglicemia" in name:
            if bp_source != "measured" and glucose_source != "measured":
                reasons.append(
                    "Padrão FP de UI: telemetria estável (FC~78, temp~36.5, sono/passos ok) "
                    "com alerta de crise hipertensiva/hiperglicemia sem medição confiável"
                )
                suppress = True
                penalty *= 0.08

    is_disc = len(reasons) > 0
    if not is_disc:
        return DiscrepancyResult(False, [], False, 1.0)
    return DiscrepancyResult(
        is_discrepant=True,
        reasons=reasons,
        should_suppress_alert=suppress,
        confidence_penalty=max(0.05, min(1.0, penalty)),
    )


def discrepancy_feature_flags(
    vitals: VitalSnapshot,
    *,
    bp_source: str = "unknown",
    glucose_source: str = "unknown",
) -> Dict[str, float]:
    """Features extras para o classificador ML (treinar FP por discrepância)."""
    return {
        "disc_stable_core": 1.0 if _stable_core(vitals) else 0.0,
        "disc_hr_mid_stable": 1.0
        if (vitals.hr is not None and 70 <= vitals.hr <= 95)
        else 0.0,
        "disc_bp_phantom": 1.0 if bp_source == "phantom" else 0.0,
        "disc_glucose_phantom": 1.0 if glucose_source == "phantom" else 0.0,
        "disc_ui_fp_pattern": 1.0
        if (
            vitals.hr is not None
            and 70 <= vitals.hr <= 92
            and (vitals.temp_c is None or 36.0 <= vitals.temp_c <= 37.2)
            and (vitals.spo2 is None or vitals.spo2 >= 96)
        )
        else 0.0,
    }
