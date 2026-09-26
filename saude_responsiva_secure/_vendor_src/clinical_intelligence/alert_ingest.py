"""
Integração da matriz de alertas com a ingestão de wearables (API / HBand).

Mapeia telemetria + phantom/estimativas → VitalSnapshot → AlertMatrixClassifier.assess()
+ detecção de discrepância amostra vs alerta (ex.: crise hipertensiva com FC 78–90).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.clinical_intelligence.alert_discrepancy import evaluate_discrepancy
from src.clinical_intelligence.alert_matrix_rules import (
    AlertMatrixEngine,
    VitalSnapshot,
)

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(os.getenv("ALERT_MATRIX_MODEL_DIR", "data/models"))

# Opt-in explícito (default OFF): só com ALERT_ALLOW_PHANTOM_VITALS=1 a matriz
# aceita PA/glicose estimadas (phantom/simulação) e os defaults legados de
# sono/passos/FC-basal. Sem o flag, a matriz avalia APENAS vitais medidos:
# sinal ausente = desconhecido (None), nunca um valor inventado.
#
# Isolamento (revisão Rafael, PR #22): o modo phantom exige AMBOS
#   1) ALERT_ALLOW_PHANTOM_VITALS=1, e
#   2) ambiente de desenvolvimento explícito (ENVIRONMENT / APP_ENV em
#      PHANTOM_DEV_ENVIRONMENTS; nenhum dos dois pode indicar produção),
# e NUNCA roda no Cloud Run (K_SERVICE / K_REVISION / K_CONFIGURATION /
# CLOUD_RUN_JOB). Fora disso o flag e o parâmetro allow_phantom_vitals=True
# são ignorados e um WARNING é emitido uma vez por processo/motivo.
PHANTOM_VITALS_ENV = "ALERT_ALLOW_PHANTOM_VITALS"
_TRUTHY = {"1", "true", "yes", "on"}
PHANTOM_ENVIRONMENT_VARS = ("ENVIRONMENT", "APP_ENV")
PHANTOM_DEV_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing"})
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "staging"})
_CLOUD_RUN_ENV_MARKERS = ("K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB")
_phantom_block_warned: set = set()


def phantom_vitals_flag_set() -> bool:
    """True se ALERT_ALLOW_PHANTOM_VITALS está ligado (não basta para ativar)."""
    return str(os.getenv(PHANTOM_VITALS_ENV, "")).strip().lower() in _TRUTHY


def phantom_vitals_block_reason() -> Optional[str]:
    """Motivo pelo qual o ambiente NÃO autoriza phantom; None se autorizado.

    Fail-closed: Cloud Run, produção/staging, ambiente ausente ou qualquer
    valor fora de PHANTOM_DEV_ENVIRONMENTS bloqueiam.
    """
    for marker in _CLOUD_RUN_ENV_MARKERS:
        if str(os.getenv(marker, "")).strip():
            return f"cloud_run({marker})"
    envs = {}
    for name in PHANTOM_ENVIRONMENT_VARS:
        value = str(os.getenv(name, "")).strip().lower()
        if value:
            envs[name] = value
    if not envs:
        return "environment_unset"
    for name, value in envs.items():
        if value in _PRODUCTION_ENVIRONMENTS:
            return f"production({name}={value})"
    for name, value in envs.items():
        if value not in PHANTOM_DEV_ENVIRONMENTS:
            return f"environment_not_dev({name}={value})"
    return None


def _warn_phantom_blocked(reason: str, requested_via: str) -> None:
    key = (reason, requested_via)
    if key in _phantom_block_warned:
        return
    _phantom_block_warned.add(key)
    logger.warning(
        "phantom_vitals=blocked reason=%s requested_via=%s — estimativas "
        "(PA/glicose phantom, defaults sono/passos/FC-basal) DESATIVADAS; "
        "%s=1 só vale junto com ENVIRONMENT de dev explícito (%s) e fora do Cloud Run.",
        reason,
        requested_via,
        PHANTOM_VITALS_ENV,
        ",".join(sorted(PHANTOM_DEV_ENVIRONMENTS)),
    )


def reset_phantom_guard_warnings() -> None:
    """Uso em testes: permite observar de novo o WARNING único."""
    _phantom_block_warned.clear()


def phantom_vitals_enabled(requested: Optional[bool] = None) -> bool:
    """Decide (fail-closed) se o modo phantom/demo pode rodar.

    requested=None → segue o flag; requested=False → sempre desligado;
    requested=True → ainda exige flag + dev explícito (o parâmetro sozinho
    não liga nada e é ignorado em produção/Cloud Run).
    """
    if requested is False:
        return False
    flag = phantom_vitals_flag_set()
    if not flag and not requested:
        return False  # ninguém pediu phantom: caminho normal, sem log
    requested_via = "param" if requested else "env"
    reason = phantom_vitals_block_reason()
    if reason is None and not flag:
        reason = f"flag_{PHANTOM_VITALS_ENV}_not_set"
    if reason is not None:
        _warn_phantom_blocked(reason, requested_via)
        return False
    return True


@lru_cache(maxsize=1)
def _load_classifier():
    """Lazy load do classificador treinado; None se indisponível."""
    try:
        from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier

        pkl = _MODEL_DIR / "alert_matrix_classifier.pkl"
        if not pkl.exists():
            logger.warning(
                "Modelo de matriz de alertas não encontrado em %s — usando só regras.",
                pkl,
            )
            return None
        return AlertMatrixClassifier.load(_MODEL_DIR)
    except Exception as exc:
        logger.warning("Falha ao carregar AlertMatrixClassifier: %s", exc)
        return None


def clear_classifier_cache() -> None:
    _load_classifier.cache_clear()


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --- Proveniência do contexto informado --------------------------------------
# Tabela ÚNICA das fontes (dict, chave) que o CÁLCULO consome para cada campo
# de contexto, na ordem de precedência do `or` legado. vitals_from_ingest_context
# (cálculo) e context_informed (exportador) leem ESTA tabela, então "presente"
# e "usado" não podem divergir: um sinal enviado mas não consumido pela matriz
# (ex.: `_hband.preprandial`, `_hband.fall_suspected`, aliases do schema como
# `fasting_or_preprandial`) NÃO conta como informado e sai null (desconhecido)
# em context_informed — nunca um default (`false`) apresentado como conhecido.
# "raw" = payload do ingest (raw_telemetry); "hband" = hband_ext (`_hband`/`hband`
# do payload + vitais copiados pelo signal_core).
CONTEXT_SOURCES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "consciousness_altered": (
        ("hband", "consciousness_altered"),
        ("raw", "consciousness_altered"),
    ),
    "rest": (("raw", "rest"), ("hband", "rest")),
    "fasting": (("raw", "fasting"), ("raw", "preprandial"), ("hband", "fasting")),
    "steps_interrupted": (
        ("raw", "steps_interrupted"),
        ("hband", "steps_interrupted"),
        ("raw", "fall_suspected"),
    ),
    "sleep_hours": (("raw", "sleep_hours"), ("hband", "sleep_hours")),
    "steps_drop_days": (("raw", "steps_drop_days"), ("hband", "steps_drop_days")),
}

# Leitura anterior (histórico enviado pelo cliente) e tolerâncias da
# "2ª leitura consecutiva válida".
PREVIOUS_READING_KEYS = ("previous_reading", "previous_vitals")
PREVIOUS_GLUCOSE_KEYS = ("glucose_mgdl", "glucose")
CONSECUTIVE_SPO2_TOLERANCE = 1.0
CONSECUTIVE_GLUCOSE_TOLERANCE = 15.0


def _source_dict(where: str, raw: Dict[str, Any], hband: Dict[str, Any]) -> Dict[str, Any]:
    return raw if where == "raw" else hband


def _context_value(field: str, raw: Dict[str, Any], hband: Dict[str, Any]) -> Any:
    """Equivale a `fonte1 or fonte2 or ...` (semântica exata do cálculo legado)."""
    value = None
    for where, key in CONTEXT_SOURCES[field]:
        value = _source_dict(where, raw, hband).get(key)
        if value:
            return value
    return value


def context_signal_present(
    field: str, raw: Optional[Dict[str, Any]], hband: Optional[Dict[str, Any]]
) -> bool:
    """True se alguma fonte QUE O CÁLCULO CONSOME para `field` veio não-nula."""
    raw = raw or {}
    hband = hband or {}
    return any(
        _source_dict(where, raw, hband).get(key) is not None
        for where, key in CONTEXT_SOURCES[field]
    )


def _previous_reading(raw: Dict[str, Any]) -> Dict[str, Any]:
    prev: Any = {}
    for key in PREVIOUS_READING_KEYS:
        prev = raw.get(key)
        if prev:
            break
    return prev if isinstance(prev, dict) else {}


def _previous_glucose(prev: Dict[str, Any]) -> Optional[float]:
    value = None
    for key in PREVIOUS_GLUCOSE_KEYS:
        value = prev.get(key)
        if value:
            break
    return _num(value)


def vitals_from_ingest_context(
    *,
    heart_rate: Optional[float] = None,
    spo2: Optional[float] = None,
    skin_temp: Optional[float] = None,
    hrv_rmssd: Optional[float] = None,
    activity_level: Optional[float] = None,
    phantom: Optional[Dict[str, Any]] = None,
    hband_ext: Optional[Dict[str, Any]] = None,
    raw_telemetry: Optional[Dict[str, Any]] = None,
    use_unreliable_phantom: bool = False,
    allow_phantom_vitals: Optional[bool] = None,
) -> Tuple[VitalSnapshot, Dict[str, Any]]:
    """
    Monta VitalSnapshot + metadados de origem (measured/phantom/absent).

    Padrão: só vitais efetivamente presentes na leitura. Sinal ausente fica
    None (desconhecido) e regras que dependem dele não disparam.

    Modo demo legado (PA/glicose phantom se reliable=True ou
    use_unreliable_phantom; defaults de sono/passos/FC-basal) só roda com
    ALERT_ALLOW_PHANTOM_VITALS=1 E ambiente dev explícito fora do Cloud Run
    (ver phantom_vitals_enabled). allow_phantom_vitals=True não basta.
    """
    # Guard central: em produção/Cloud Run o parâmetro é ignorado (fail-closed).
    allow_phantom_vitals = phantom_vitals_enabled(allow_phantom_vitals)
    hband = hband_ext or {}
    raw = raw_telemetry or {}
    ph = (phantom or {}) if allow_phantom_vitals else {}
    pas = pad = glucose = None
    meta: Dict[str, Any] = {
        "bp_source": "absent",
        "glucose_source": "absent",
        "bp_reliable": False,
        "glucose_reliable": False,
        "phantom_vitals_enabled": bool(allow_phantom_vitals),
    }

    def phantom_est(*keys: str) -> Tuple[Optional[float], bool]:
        for k in keys:
            node = ph.get(k)
            if isinstance(node, dict) and "estimate" in node:
                rel = bool(node.get("reliable", True))
                if not rel and not use_unreliable_phantom:
                    continue
                return _num(node["estimate"]), rel
            if node is not None and not isinstance(node, dict):
                return _num(node), True
        return None, True

    # PA medida
    pas_m = _num(hband.get("blood_pressure_sys")) or _num(raw.get("blood_pressure_sys"))
    pad_m = _num(hband.get("blood_pressure_dia")) or _num(raw.get("blood_pressure_dia"))
    if pas_m is not None or pad_m is not None:
        pas, pad = pas_m, pad_m
        meta["bp_source"] = "measured"
        meta["bp_reliable"] = True
    else:
        pas, pas_rel = phantom_est("systolic_bp", "sbp", "pas")
        pad, pad_rel = phantom_est("diastolic_bp", "dbp", "pad")
        if pas is None and pad is None:
            map_v, map_rel = phantom_est("map_mmhg", "map", "mean_arterial_pressure")
            if map_v is not None:
                pas = map_v + 13.3
                pad = map_v - 6.7
                meta["bp_source"] = "phantom"
                meta["bp_reliable"] = map_rel
        elif pas is not None or pad is not None:
            meta["bp_source"] = "phantom"
            meta["bp_reliable"] = pas_rel and pad_rel

    # Glicose
    glu_m = _num(hband.get("glucose_mgdl")) or _num(raw.get("glucose_mgdl"))
    if glu_m is not None:
        glucose = glu_m
        meta["glucose_source"] = "measured"
        meta["glucose_reliable"] = True
    else:
        glucose, glu_rel = phantom_est("glucose_mgdl", "glucose", "blood_glucose")
        if glucose is not None:
            meta["glucose_source"] = "phantom"
            meta["glucose_reliable"] = glu_rel

    temp = _num(skin_temp)
    body = _num(hband.get("body_temp_c")) or _num(raw.get("body_temp_c"))
    if body is not None and (temp is None or 25.0 <= temp < 35.0):
        temp = body

    steps_drop = _num(hband.get("steps_drop_pct")) or _num(raw.get("steps_drop_pct"))
    sleep_worsen = _num(hband.get("sleep_worsen_pct")) or _num(raw.get("sleep_worsen_pct"))
    hr_rise = _num(hband.get("hr_baseline_rise")) or _num(raw.get("hr_baseline_rise"))
    spo2_drop = _num(hband.get("spo2_drop_points")) or _num(raw.get("spo2_drop_points"))
    consciousness = bool(_context_value("consciousness_altered", raw, hband))

    if allow_phantom_vitals:
        # Heurísticas/defaults legados (modo demo). Fora do opt-in: ausente = None.
        if hr_rise is None and activity_level is not None and float(activity_level) > 40:
            hr_rise = min(25.0, float(activity_level) * 0.2)
        # Sono "Bom" implícito se não informado
        if sleep_worsen is None:
            sleep_worsen = 5.0
        if steps_drop is None:
            steps_drop = 5.0

    basal = raw.get("basal") or raw.get("baseline") or hband.get("basal") or {}
    prev = _previous_reading(raw)
    if not isinstance(basal, dict):
        basal = {}

    pas_b = _num(basal.get("pas") or basal.get("blood_pressure_sys"))
    pad_b = _num(basal.get("pad") or basal.get("blood_pressure_dia"))
    spo2_b = _num(basal.get("spo2"))
    temp_b = _num(basal.get("temp_c") or basal.get("body_temp_c"))
    glu_b = _num(basal.get("glucose_mgdl") or basal.get("glucose"))
    glu_prev = _previous_glucose(prev)
    spo2_prev = _num(prev.get("spo2"))
    consecutive = 1
    cur_spo2 = _num(spo2)
    if (
        spo2_prev is not None
        and cur_spo2 is not None
        and abs(spo2_prev - cur_spo2) <= CONSECUTIVE_SPO2_TOLERANCE
    ):
        consecutive = 2
    glu_now = glucose
    # Obs.: no modo demo (dev autorizado) glu_now pode ser phantom e confirmar a
    # 2ª leitura para as REGRAS (comportamento de dev inalterado). O exportador
    # context_informed recalcula só com glicose MEDIDA (ver _measured_consecutive).
    if (
        glu_prev is not None
        and glu_now is not None
        and abs(glu_prev - glu_now) <= CONSECUTIVE_GLUCOSE_TOLERANCE
    ):
        consecutive = max(consecutive, 2)

    if spo2_drop is None and cur_spo2 is not None and spo2_b is not None:
        spo2_drop = max(0.0, spo2_b - cur_spo2)
    hr_now = _num(heart_rate)
    hr_b = _num(basal.get("hr") or basal.get("heart_rate"))
    if hr_rise is None and hr_now is not None and hr_b is not None:
        hr_rise = hr_now - hr_b

    rest = bool(
        _context_value("rest", raw, hband)
        or (activity_level is not None and float(activity_level) < 20)
    )
    fasting = bool(_context_value("fasting", raw, hband))
    sleep_hours = _num(_context_value("sleep_hours", raw, hband))
    steps_days = int(_context_value("steps_drop_days", raw, hband) or 0)
    interrupted = bool(_context_value("steps_interrupted", raw, hband))
    no_steps_active = bool(
        raw.get("no_steps_rest_of_active") or hband.get("no_steps_rest_of_active")
    )

    vitals = VitalSnapshot(
        pas=pas,
        pad=pad,
        hr=hr_now,
        spo2=cur_spo2,
        temp_c=temp,
        glucose_mgdl=glu_now,
        steps_drop_pct=steps_drop,
        sleep_worsen_pct=sleep_worsen,
        hr_baseline_rise=hr_rise,
        spo2_drop_points=spo2_drop,
        consciousness_altered=consciousness,
        pas_basal=pas_b,
        pad_basal=pad_b,
        spo2_basal=spo2_b,
        temp_basal=temp_b,
        glucose_basal=glu_b,
        glucose_prev=glu_prev,
        consecutive_valid=consecutive,
        rest=rest,
        fasting=fasting,
        sleep_hours=sleep_hours,
        steps_drop_days=steps_days,
        steps_interrupted=interrupted,
        no_steps_rest_of_active=no_steps_active,
    )
    return vitals, meta


_PRESENT_VITAL_FIELDS = (
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
)


def vitals_present(vitals: VitalSnapshot) -> Dict[str, Optional[float]]:
    """Vitais usados pela matriz, sem imputação: ausente → None."""
    return {k: getattr(vitals, k) for k in _PRESENT_VITAL_FIELDS}


# Campos do vitals_used legado (to_feature_dict, 22 chaves) que saíram na
# PR #22. Aqui voltam SEM imputação: só valor derivado de dado efetivamente
# enviado pelo cliente (ou medido); caso contrário None. Ver
# docs/contracts/INGEST_VITALS_USED_CONTRACT.md.
CONTEXT_INFORMED_FIELDS = (
    "consciousness_altered",
    "map_approx",
    "pulse_pressure",
    "consecutive_valid",
    "rest",
    "fasting",
    "steps_interrupted",
    "sleep_hours",
    "steps_drop_days",
    "pas_rise_vs_basal",
    "pas_drop_vs_basal",
    "glucose_delta",
)


def _measured_consecutive(
    vitals: VitalSnapshot, meta: Dict[str, Any], raw: Dict[str, Any]
) -> Optional[int]:
    """2ª leitura consecutiva SÓ com medidas reais comparáveis; senão None.

    Compara a leitura atual com `previous_reading`/`previous_vitals` apenas
    quando AMBOS os lados têm o mesmo sinal medido: SpO2 (sempre medida — não
    existe SpO2 phantom) e glicose com glucose_source == "measured". Glicose
    phantom/estimada nunca entra (nem no modo demo). Sem par comparável → None
    (desconhecido), nunca o default 1.
    """
    prev = _previous_reading(raw)
    if not prev:
        return None
    matches = []
    spo2_prev = _num(prev.get("spo2"))
    if spo2_prev is not None and vitals.spo2 is not None:
        matches.append(abs(spo2_prev - float(vitals.spo2)) <= CONSECUTIVE_SPO2_TOLERANCE)
    glu_prev = _previous_glucose(prev)
    if (
        glu_prev is not None
        and meta.get("glucose_source") == "measured"
        and vitals.glucose_mgdl is not None
    ):
        matches.append(
            abs(glu_prev - float(vitals.glucose_mgdl)) <= CONSECUTIVE_GLUCOSE_TOLERANCE
        )
    if not matches:
        return None
    return 2 if any(matches) else 1


def context_informed(
    vitals: VitalSnapshot,
    meta: Dict[str, Any],
    *,
    hband_ext: Optional[Dict[str, Any]] = None,
    raw_telemetry: Optional[Dict[str, Any]] = None,
    activity_level: Optional[float] = None,
) -> Dict[str, Any]:
    """Contexto que a matriz consumiu, com proveniência medida — nunca imputado.

    Regras (contrato docs/contracts/INGEST_VITALS_USED_CONTRACT.md):
      * cada campo vem SÓ de dado efetivamente recebido na leitura atual
        (e, para comparações, de um valor medido comparável no histórico);
      * PA/glicose só contam se bp_source/glucose_source == "measured" —
        phantom/estimativas nunca aparecem aqui, nem no modo demo em dev;
      * "presente" = alguma fonte de CONTEXT_SOURCES (as mesmas que o cálculo
        consome) veio não-nula; sinal presente mas não consumido → None;
      * sem dado → None (desconhecido), nunca um default como false/0/1.
    """
    hband = hband_ext or {}
    raw = raw_telemetry or {}
    bp_measured = meta.get("bp_source") == "measured"
    glu_measured = meta.get("glucose_source") == "measured"
    both_bp = bp_measured and vitals.pas is not None and vitals.pad is not None

    def present(field: str) -> bool:
        return context_signal_present(field, raw, hband)

    def rounded(v: Optional[float]) -> Optional[float]:
        return None if v is None else round(float(v), 2)

    rest_informed = present("rest") or activity_level is not None
    return {
        "consciousness_altered": (
            bool(vitals.consciousness_altered) if present("consciousness_altered") else None
        ),
        "map_approx": rounded((vitals.pas + 2 * vitals.pad) / 3.0) if both_bp else None,
        "pulse_pressure": rounded(vitals.pas - vitals.pad) if both_bp else None,
        "consecutive_valid": _measured_consecutive(vitals, meta, raw),
        "rest": bool(vitals.rest) if rest_informed else None,
        "fasting": bool(vitals.fasting) if present("fasting") else None,
        "steps_interrupted": (
            bool(vitals.steps_interrupted) if present("steps_interrupted") else None
        ),
        "sleep_hours": vitals.sleep_hours if present("sleep_hours") else None,
        "steps_drop_days": (
            int(vitals.steps_drop_days or 0) if present("steps_drop_days") else None
        ),
        "pas_rise_vs_basal": rounded(vitals.pas_rise()) if bp_measured else None,
        "pas_drop_vs_basal": rounded(vitals.pas_drop()) if bp_measured else None,
        "glucose_delta": rounded(vitals.glucose_delta()) if glu_measured else None,
    }


def _apply_discrepancy(full: Dict[str, Any], vitals: VitalSnapshot, meta: Dict[str, Any]) -> Dict[str, Any]:
    disc = evaluate_discrepancy(
        vitals,
        full.get("rule_hits") or [],
        primary_rule_id=full.get("primary_rule_id"),
        primary_alert_name=full.get("primary_alert_name"),
        bp_source=meta.get("bp_source", "unknown"),
        glucose_source=meta.get("glucose_source", "unknown"),
        glucose_reliable=bool(meta.get("glucose_reliable", False)),
        bp_reliable=bool(meta.get("bp_reliable", False)),
    )
    full = dict(full)
    full["discrepancy"] = disc.to_dict()
    full["source_meta"] = meta

    if disc.should_suppress_alert and full.get("is_true_alert"):
        full["is_true_alert"] = False
        full["is_false_positive"] = True
        full["severity"] = "none"
        full["decision"] = "suppressed_sample_discrepancy"
        conf = float(full.get("confidence") or 0.5) * disc.confidence_penalty
        full["confidence"] = max(0.05, conf)
        full["suppressed_alert_name"] = full.get("primary_alert_name")
        full["suppressed_rule_id"] = full.get("primary_rule_id")
        # mantém rule_hits para auditoria, mas marca como FP
        full["rule_explanation"] = (
            (full.get("rule_explanation") or "")
            + " | SUPRIMIDO: "
            + "; ".join(disc.reasons)
        )
    elif disc.is_discrepant and full.get("is_true_alert"):
        full["confidence"] = max(
            0.1, float(full.get("confidence") or 0.5) * disc.confidence_penalty
        )
        full["decision"] = "rule_match_discrepancy_penalty"
    return full


def assess_ingest_alerts(
    *,
    heart_rate: Optional[float] = None,
    spo2: Optional[float] = None,
    skin_temp: Optional[float] = None,
    hrv_rmssd: Optional[float] = None,
    activity_level: Optional[float] = None,
    phantom: Optional[Dict[str, Any]] = None,
    hband_ext: Optional[Dict[str, Any]] = None,
    raw_telemetry: Optional[Dict[str, Any]] = None,
    allow_phantom_vitals: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Avalia alertas clínicos para um frame de ingestão.

    Só vitais presentes na leitura entram na matriz (ver
    vitals_from_ingest_context / ALERT_ALLOW_PHANTOM_VITALS).

    Retorno enxuto para embutir em processed_frame['clinical_alerts'].
    """
    vitals, meta = vitals_from_ingest_context(
        heart_rate=heart_rate,
        spo2=spo2,
        skin_temp=skin_temp,
        hrv_rmssd=hrv_rmssd,
        activity_level=activity_level,
        phantom=phantom,
        hband_ext=hband_ext,
        raw_telemetry=raw_telemetry,
        allow_phantom_vitals=allow_phantom_vitals,
    )

    from src.clinical_intelligence.next2u_context import PatientContext

    ctx = PatientContext.from_payload(raw_telemetry or {})
    # Confirmação automática: 2ª leitura consecutiva válida
    if (vitals.consecutive_valid or 1) >= 2:
        ctx.confirmation_or_persistence = True

    clf = _load_classifier()
    if clf is not None:
        full = clf.assess(
            vitals,
            source_meta=meta,
            context=ctx,
        )
    else:
        engine = AlertMatrixEngine()
        rule = engine.evaluate(vitals, context=ctx)
        full = {
            "is_true_alert": rule.is_true_alert,
            "is_false_positive": rule.is_false_positive_candidate,
            "severity": rule.max_severity,
            "confidence": 0.9 if rule.is_true_alert else 0.7,
            "decision": "rule_only" if rule.is_true_alert else (
                "suppressed_false_positive"
                if rule.is_false_positive_candidate
                else "stable_or_noise"
            ),
            "primary_alert_name": rule.primary_alert_name,
            "primary_rule_id": rule.primary_rule_id,
            "rule_hits": [h.to_dict() for h in rule.hits],
            "rule_explanation": rule.explanation,
            "ml": None,
            "vitals": vitals.to_feature_dict(),
            "next2u_id": rule.next2u_id,
            "stars": rule.stars,
            "risk_band": rule.risk_band,
            "hospitalization_score": rule.hospitalization_score,
            "care_pathway": rule.care_pathway,
            "care_line": rule.care_line,
            "clinical_notes": list(rule.clinical_notes or []),
        }
        from src.clinical_intelligence.alert_matrix_rules import with_decision_support
        full = with_decision_support(full)
        full = _apply_discrepancy(full, vitals, meta)

    from src.clinical_intelligence.care_flows import apply_care_flow_overlay, evaluate_care_flows

    flow = evaluate_care_flows(vitals, ctx)
    full = apply_care_flow_overlay(full, flow)

    # Payload estável para API / WebSocket / dashboard.
    # Estrelas, escore e rota operacional ficam em staff_only (não expor ao paciente).
    public_name = full.get("primary_alert_name") if full.get("is_true_alert") else None
    return {
        "is_true_alert": bool(full.get("is_true_alert")),
        "is_false_positive": bool(full.get("is_false_positive")),
        "severity": full.get("severity") or "none",
        "confidence": round(float(full.get("confidence") or 0.0), 4),
        "decision": full.get("decision"),
        "primary_alert_name": public_name,
        "primary_rule_id": full.get("primary_rule_id") if full.get("is_true_alert") else None,
        "rule_hits": full.get("rule_hits") or [],
        "rule_explanation": full.get("rule_explanation"),
        # Sem imputação: só o que foi medido (ausente → None). Features do ML
        # (com defaults de treino) ficam fora da resposta.
        "vitals_used": vitals_present(vitals),
        # Contexto informado (sem imputação) dos 12 campos que saíram do
        # vitals_used legado — ausente/não enviado → None.
        "context_informed": context_informed(
            vitals,
            meta,
            hband_ext=hband_ext,
            raw_telemetry=raw_telemetry,
            activity_level=activity_level,
        ),
        "ml": full.get("ml"),
        "discrepancy": full.get("discrepancy"),
        "source_meta": full.get("source_meta") or meta,
        "suppressed_alert_name": full.get("suppressed_alert_name"),
        "engine": "alert_matrix_ml" if clf is not None else "alert_matrix_rules",
        "matrix_version": "next2u-158-971-2026-08-16",
        "care_line": full.get("care_line"),
        "decision_support": full.get("decision_support"),
        "clinical_notes": full.get("clinical_notes") or [],
        "staff_only": {
            "next2u_id": full.get("next2u_id"),
            "stars": full.get("stars") or 0,
            "risk_band": full.get("risk_band"),
            "hospitalization_score": full.get("hospitalization_score") or 0,
            "care_pathway": full.get("care_pathway"),
            "disease_concordant": full.get("disease_concordant"),
            "med_concordant": full.get("med_concordant"),
            "care_flow": full.get("care_flow"),
        },
    }


def merge_anomaly_with_alerts(
    anomaly: Dict[str, Any],
    clinical_alerts: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ajusta flag de anomalia local com a matriz:
      - true alert → reforça alerta
      - FP / discrepância suprimida → não escalar anomalia isolada
    """
    out = dict(anomaly or {})
    if clinical_alerts.get("is_true_alert"):
        out["alerta"] = True
        sev = clinical_alerts.get("severity") or "moderado"
        score_map = {"leve": 0.65, "moderado": 0.85, "critico": 0.98}
        out["score"] = max(float(out.get("score") or 0), score_map.get(sev, 0.8))
        out["modo"] = f"Matriz Clínica ({sev})"
        out["clinical_rule_id"] = clinical_alerts.get("primary_rule_id")
        out["clinical_alert_name"] = clinical_alerts.get("primary_alert_name")
    elif clinical_alerts.get("is_false_positive") or clinical_alerts.get(
        "decision"
    ) == "suppressed_sample_discrepancy":
        if out.get("modo") in {
            "Detecção Local BMO",
            "Deteção Local",
            "Deteção Local BMO",
        } or out.get("alerta"):
            out["alerta"] = False
            out["score"] = min(float(out.get("score") or 0.05), 0.15)
            out["modo"] = "Suprimido (falso positivo / discrepância amostra)"
            out["suppressed_by_matrix"] = True
            if clinical_alerts.get("discrepancy"):
                out["discrepancy_reasons"] = clinical_alerts["discrepancy"].get(
                    "reasons", []
                )
    return out
