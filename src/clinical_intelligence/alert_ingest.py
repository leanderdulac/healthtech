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
_MATRIX_VERSION = "next2u-158-971-2026-08-16"
_PILOT_SOURCES = frozenset({"ble_hband", "ble_standard"})
_KNOWN_SOURCES = frozenset(
    {"companion_manual", "ble_sim", "ble_hband", "ble_standard", "http"}
)
# Mesma sessão: a leitura de ontem não confirma a de agora.
CONFIRM_WINDOW_SECONDS = 15 * 60
# Abaixo do intervalo de 3 s do companion. Repetir o mesmo quadro não é persistência.
DUPLICATE_WINDOW_SECONDS = 2
# Escala 0–100 do contrato. Abaixo de 20 a matriz já trata como repouso.
MOTION_ACTIVITY = 40.0
# Taquicardia isolada. SpO2, pressão, glicose e temperatura ficam de fora.
_EXERCISE_HR_RULES = frozenset(
    {
        "n2u_091",
        "n2u_092",
        "n2u_094",
        "n2u_095",
        "n2u_096",
        "n2u_100",
        "n2u_101",
        "n2u_102",
    }
)


def _ingest_source(raw: Optional[Dict[str, Any]]) -> str:
    raw = raw or {}
    val = str(raw.get("ingest_source") or "companion_manual").strip().lower()
    if val in _KNOWN_SOURCES:
        return val
    return "companion_manual"


@lru_cache(maxsize=1)
def rules_fingerprint() -> Dict[str, Any]:
    """Hash do catálogo vivo das regras. É o que o piloto executa."""
    import hashlib
    import json

    from src.clinical_intelligence.alert_matrix_rules import rules_catalog

    catalog = rules_catalog()
    blob = json.dumps(
        catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "rules_sha256": hashlib.sha256(blob).hexdigest(),
        "rules_count": len(catalog),
    }


@lru_cache(maxsize=1)
def git_sha() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        sha = (out.stdout or "").strip()
        if out.returncode == 0 and sha:
            return sha
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def alert_provenance(ingest_source: str) -> Dict[str, Any]:
    fp = rules_fingerprint()
    return {
        "git_sha": git_sha(),
        "rules_sha256": fp["rules_sha256"],
        "rules_count": fp["rules_count"],
        "matrix_version": _MATRIX_VERSION,
        "ingest_source": ingest_source,
        "pilot_eligible": ingest_source in _PILOT_SOURCES,
    }


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
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Faixa do contrato do piloto (OpenAPI e companion): fora dela o valor não entra na regra.
_HR_LO, _HR_HI = 20.0, 250.0


def resolve_heart_rate(
    measured: Any,
    ppg: Optional[list] = None,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """FC da leitura. A média de ppg_signal não é batimento.

    heart_rate vale entre 20 e 250 bpm. Uma lista PPG é onda ou contagem de
    ADC; o valor médio não substitui a frequência medida.
    """
    samples = list(ppg) if ppg else []
    note: Dict[str, Any] = {
        "ppg_samples": len(samples),
        "ppg_role": "waveform" if len(samples) >= 4 else "absent",
        "ppg_not_used_as_bpm": len(samples) >= 4,
    }
    hr = _num(measured)
    if hr is None:
        note["heart_rate_source"] = "absent"
        return None, note
    if hr < _HR_LO or hr > _HR_HI:
        note["heart_rate_source"] = "rejected"
        note["rejected_heart_rate"] = hr
        return None, note
    note["heart_rate_source"] = "measured"
    return hr, note


def _accept(v: Any, lo: float, hi: float, field: str, rejected: list) -> Optional[float]:
    n = _num(v)
    if n is None:
        return None
    if lo <= n <= hi:
        return n
    rejected.append({
        "field": field,
        "value": n,
        "reason": f"fora de {lo:g}–{hi:g}",
    })
    return None


def reading_age_seconds(current: Any, previous: Any) -> Optional[float]:
    """Segundos entre a leitura atual e a anterior. Sem os dois instantes, None."""
    from src.ops.timestamps import parse_timestamp

    cur = parse_timestamp(current)
    prev = parse_timestamp(previous)
    if cur is None or prev is None:
        return None
    return (cur - prev).total_seconds()


def measured_previous_from_frame(frame: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Sinais que a regra aceitou no quadro anterior. Estimativa não entra."""
    if not isinstance(frame, dict):
        return None
    raw = frame.get("raw_telemetry") if isinstance(frame.get("raw_telemetry"), dict) else {}
    used: Dict[str, Any] = {}
    alerts = frame.get("clinical_alerts")
    if isinstance(alerts, dict) and isinstance(alerts.get("vitals_used"), dict):
        used = alerts["vitals_used"]
    out: Dict[str, Any] = {}
    hr = _num(used.get("hr"))
    if hr is None:
        hr = _num(raw.get("heart_rate_bpm") or raw.get("heart_rate") or frame.get("heart_rate"))
        if hr is not None and not (_HR_LO <= hr <= _HR_HI):
            hr = None
    spo2 = _num(used.get("spo2"))
    if spo2 is None:
        spo2 = _num(raw.get("spo2_percent") or raw.get("spo2") or frame.get("spo2"))
    glucose = _num(used.get("glucose_mgdl"))
    if glucose is None:
        glucose = _num(raw.get("glucose_mgdl") or frame.get("glucose_mgdl"))
    if hr is not None:
        out["heart_rate"] = hr
    if spo2 is not None:
        out["spo2"] = spo2
    if glucose is not None:
        out["glucose_mgdl"] = glucose
    ts = frame.get("timestamp") or raw.get("timestamp") or frame.get("received_at")
    if not ts or not out:
        return None
    out["timestamp"] = ts
    return out


def attach_previous_reading(
    payload: Dict[str, Any],
    previous_frame: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Copia a leitura anterior do mesmo paciente quando o POST não trouxe uma.

    A cópia só entra se os dois quadros têm instante e a distância cabe na
    janela de confirmação. Um previous_reading já presente no POST fica como está;
    a idade também é conferida em vitals_from_ingest_context.
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("previous_reading") or payload.get("previous_vitals"):
        return payload
    previous = measured_previous_from_frame(previous_frame)
    if not previous:
        return payload
    current_ts = payload.get("timestamp") or payload.get("received_at")
    age = reading_age_seconds(current_ts, previous.get("timestamp"))
    if age is None or age < 0 or age > CONFIRM_WINDOW_SECONDS:
        return payload
    enriched = dict(payload)
    enriched["previous_reading"] = previous
    return enriched


def _same_presence(left: Optional[float], right: Optional[float], tol: float = 0.5) -> bool:
    if (left is None) != (right is None):
        return False
    if left is None:
        return True
    return abs(left - right) <= tol


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
) -> Tuple[VitalSnapshot, Dict[str, Any]]:
    """
    Monta VitalSnapshot + metadados de origem (measured/phantom).

    PA/glicose phantom só entram se reliable=True (ou use_unreliable_phantom).
    """
    hband = hband_ext or {}
    raw = raw_telemetry or {}
    ph = phantom or {}
    pas = pad = glucose = None
    rejected: list = []
    meta: Dict[str, Any] = {
        "bp_source": "unknown",
        "glucose_source": "unknown",
        "bp_reliable": True,
        "glucose_reliable": True,
        "rejected": rejected,
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

    # PA medida. Estimativa phantom só entra com reliable=True.
    pas_m = _accept(hband.get("blood_pressure_sys"), 50, 300, "pas", rejected)
    if pas_m is None and "blood_pressure_sys" not in hband:
        pas_m = _accept(raw.get("blood_pressure_sys"), 50, 300, "pas", rejected)
    pad_m = _accept(hband.get("blood_pressure_dia"), 30, 200, "pad", rejected)
    if pad_m is None and "blood_pressure_dia" not in hband:
        pad_m = _accept(raw.get("blood_pressure_dia"), 30, 200, "pad", rejected)
    if pas_m is not None and pad_m is not None and pas_m <= pad_m:
        rejected.append({
            "field": "blood_pressure",
            "value": [pas_m, pad_m],
            "reason": "sistólica não é maior que a diastólica",
        })
        pas_m = pad_m = None
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
    glu_m = _accept(hband.get("glucose_mgdl"), 20, 1000, "glucose_mgdl", rejected)
    if glu_m is None and "glucose_mgdl" not in hband:
        glu_m = _accept(raw.get("glucose_mgdl"), 20, 1000, "glucose_mgdl", rejected)
    if glu_m is not None:
        glucose = glu_m
        meta["glucose_source"] = "measured"
        meta["glucose_reliable"] = True
    else:
        glucose, glu_rel = phantom_est("glucose_mgdl", "glucose", "blood_glucose")
        if glucose is not None:
            meta["glucose_source"] = "phantom"
            meta["glucose_reliable"] = glu_rel

    temp = _accept(skin_temp, 25, 45, "temp_c", rejected)
    if temp is not None and temp < 35.0:
        body = _accept(hband.get("body_temp_c"), 30, 45, "body_temp_c", rejected)
        if body is None and "body_temp_c" not in hband:
            body = _accept(raw.get("body_temp_c"), 30, 45, "body_temp_c", rejected)
        if body is not None:
            temp = body

    steps_drop = _num(hband.get("steps_drop_pct")) or _num(raw.get("steps_drop_pct"))
    sleep_worsen = _num(hband.get("sleep_worsen_pct")) or _num(raw.get("sleep_worsen_pct"))
    hr_rise = _num(hband.get("hr_baseline_rise")) or _num(raw.get("hr_baseline_rise"))
    spo2_drop = _num(hband.get("spo2_drop_points")) or _num(raw.get("spo2_drop_points"))
    consciousness = bool(
        hband.get("consciousness_altered") or raw.get("consciousness_altered")
    )

    basal = raw.get("basal") or raw.get("baseline") or hband.get("basal") or {}
    prev = raw.get("previous_reading") or raw.get("previous_vitals") or {}
    if not isinstance(basal, dict):
        basal = {}
    if not isinstance(prev, dict):
        prev = {}

    pas_b = _num(basal.get("pas") or basal.get("blood_pressure_sys"))
    pad_b = _num(basal.get("pad") or basal.get("blood_pressure_dia"))
    spo2_b = _num(basal.get("spo2"))
    temp_b = _num(basal.get("temp_c") or basal.get("body_temp_c"))
    glu_b = _num(basal.get("glucose_mgdl") or basal.get("glucose"))
    cur_spo2 = _accept(spo2, 50, 100, "spo2", rejected)
    hr_now = _accept(heart_rate, _HR_LO, _HR_HI, "hr", rejected)
    current_ts = raw.get("timestamp") or raw.get("received_at")
    age = reading_age_seconds(current_ts, prev.get("timestamp") or prev.get("received_at"))
    if age is None or age < 0 or age > CONFIRM_WINDOW_SECONDS:
        prev = {}
        age = None
    glu_prev = _num(prev.get("glucose_mgdl") or prev.get("glucose"))
    spo2_prev = _num(prev.get("spo2") or prev.get("spo2_percent"))
    hr_prev = _num(prev.get("heart_rate") or prev.get("hr") or prev.get("heart_rate_bpm"))
    duplicate = False
    if age is not None and age <= DUPLICATE_WINDOW_SECONDS:
        duplicate = (
            _same_presence(hr_now, hr_prev)
            and hr_now is not None
            and _same_presence(cur_spo2, spo2_prev)
            and _same_presence(glucose, glu_prev)
        )
    if duplicate:
        meta["duplicate_sample"] = True
        spo2_prev = None
        glu_prev = None
    consecutive = 1
    if (
        spo2_prev is not None
        and cur_spo2 is not None
        and abs(spo2_prev - cur_spo2) <= 1.0
    ):
        consecutive = 2
    glu_now = glucose
    if glu_prev is not None and glu_now is not None and abs(glu_prev - glu_now) <= 15:
        consecutive = max(consecutive, 2)

    if spo2_drop is None and cur_spo2 is not None and spo2_b is not None:
        spo2_drop = max(0.0, spo2_b - cur_spo2)
    hr_b = _num(basal.get("hr") or basal.get("heart_rate"))
    if hr_rise is None and hr_now is not None and hr_b is not None:
        hr_rise = hr_now - hr_b

    rest = bool(raw.get("rest") or hband.get("rest") or (activity_level is not None and float(activity_level) < 20))
    fasting = bool(raw.get("fasting") or raw.get("preprandial") or hband.get("fasting"))
    sleep_hours = _num(raw.get("sleep_hours") or hband.get("sleep_hours"))
    steps_days = int(raw.get("steps_drop_days") or hband.get("steps_drop_days") or 0)
    interrupted = bool(
        raw.get("steps_interrupted")
        or hband.get("steps_interrupted")
        or raw.get("fall_suspected")
    )
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


def _wear_off(raw: Dict[str, Any], hband: Dict[str, Any]) -> bool:
    for source in (hband, raw):
        if not isinstance(source, dict) or "wear_status" not in source:
            continue
        value = source.get("wear_status")
        if value is False or value == 0:
            return True
        if isinstance(value, str) and value.strip().lower() in {"false", "0", "off", "loose"}:
            return True
    return False


def _exercise_hr_only(hits: list, hr: Optional[float], activity: Optional[float]) -> bool:
    if activity is None or float(activity) < MOTION_ACTIVITY:
        return False
    if hr is None or hr < 91:
        return False
    if not hits:
        return False
    return all(
        isinstance(hit, dict) and hit.get("rule_id") in _EXERCISE_HR_RULES
        for hit in hits
    )


def _apply_quality_gate(
    full: Dict[str, Any],
    vitals: VitalSnapshot,
    meta: Dict[str, Any],
    *,
    activity_level: Optional[float],
    raw_telemetry: Optional[Dict[str, Any]],
    hband_ext: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Guarda o quadro e segura o alerta quando o sinal não sustenta a regra.

    Pulseira fora do pulso e amostra repetida em poucos segundos seguram
    qualquer alerta. Atividade alta segura só taquicardia isolada: SpO2,
    pressão, glicose e temperatura continuam valendo.
    """
    raw = raw_telemetry or {}
    hband = hband_ext or {}
    reasons: list[str] = []
    if _wear_off(raw, hband):
        reasons.append("wear_off")
    if meta.get("duplicate_sample"):
        reasons.append("duplicate_sample")
    hits = full.get("rule_hits") or []
    motion = _exercise_hr_only(hits, vitals.hr, activity_level)
    if motion and full.get("is_true_alert"):
        reasons.append("motion")
    if not reasons:
        return full

    suppress = bool(full.get("is_true_alert")) and (
        "wear_off" in reasons or "duplicate_sample" in reasons or "motion" in reasons
    )
    rejected = meta.get("rejected")
    if not isinstance(rejected, list):
        rejected = []
        meta["rejected"] = rejected
    for reason in reasons:
        rejected.append({"field": "frame", "reason": reason})
    meta["quality"] = {"reasons": reasons, "alert_suppressed": suppress}
    full = dict(full)
    full["source_meta"] = meta
    if not suppress:
        return full

    full["suppressed_alert_name"] = full.get("primary_alert_name")
    full["suppressed_rule_id"] = full.get("primary_rule_id")
    full["is_true_alert"] = False
    full["severity"] = "none"
    full["decision"] = "suppressed_quality"
    full["care_line"] = None
    note = "SUPRIMIDO: " + ", ".join(reasons)
    explanation = full.get("rule_explanation") or ""
    full["rule_explanation"] = f"{explanation} | {note}" if explanation else note
    return full


def _apply_discrepancy(full: Dict[str, Any], vitals: VitalSnapshot, meta: Dict[str, Any]) -> Dict[str, Any]:
    disc = evaluate_discrepancy(
        vitals,
        full.get("rule_hits") or [],
        primary_rule_id=full.get("primary_rule_id"),
        primary_alert_name=full.get("primary_alert_name"),
        bp_source=meta.get("bp_source", "unknown"),
        glucose_source=meta.get("glucose_source", "unknown"),
        glucose_reliable=bool(meta.get("glucose_reliable", True)),
        bp_reliable=bool(meta.get("bp_reliable", True)),
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
    rules_only: bool = False,
) -> Dict[str, Any]:
    """
    Avalia alertas clínicos para um frame de ingestão.

    Retorno enxuto para embutir em processed_frame['clinical_alerts'].
    rules_only ignora o classificador mesmo quando o .pkl está no disco.
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
    )

    from src.clinical_intelligence.next2u_context import PatientContext

    ctx = PatientContext.from_payload(raw_telemetry or {})
    # Confirmação automática: 2ª leitura consecutiva válida
    if (vitals.consecutive_valid or 1) >= 2:
        ctx.confirmation_or_persistence = True

    source = _ingest_source(raw_telemetry)
    provenance = alert_provenance(source)
    clf = None if rules_only else _load_classifier()
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
    full = _apply_quality_gate(
        full,
        vitals,
        meta,
        activity_level=activity_level,
        raw_telemetry=raw_telemetry,
        hband_ext=hband_ext,
    )
    full["provenance"] = provenance
    full["ingest_source"] = source
    full["pilot_eligible"] = provenance["pilot_eligible"]

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
        "vitals_used": vitals.to_reading_dict(),
        "ml": None if rules_only else full.get("ml"),
        "discrepancy": full.get("discrepancy"),
        "source_meta": full.get("source_meta") or meta,
        "suppressed_alert_name": full.get("suppressed_alert_name"),
        "engine": "alert_matrix_rules" if clf is None else "alert_matrix_ml",
        "matrix_version": _MATRIX_VERSION,
        "ingest_source": source,
        "pilot_eligible": provenance["pilot_eligible"],
        "provenance": provenance,
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
    ) in {"suppressed_sample_discrepancy", "suppressed_quality"}:
        if out.get("modo") in {
            "Detecção Local BMO",
            "Deteção Local",
            "Deteção Local BMO",
        } or out.get("alerta"):
            out["alerta"] = False
            out["score"] = min(float(out.get("score") or 0.05), 0.15)
            out["suppressed_by_matrix"] = True
            if clinical_alerts.get("decision") == "suppressed_quality":
                quality = (clinical_alerts.get("source_meta") or {}).get("quality") or {}
                out["modo"] = "Suprimido (qualidade do sinal)"
                out["quality_reasons"] = list(quality.get("reasons") or [])
            else:
                out["modo"] = "Suprimido (falso positivo / discrepância amostra)"
                if clinical_alerts.get("discrepancy"):
                    out["discrepancy_reasons"] = clinical_alerts["discrepancy"].get(
                        "reasons", []
                    )
    return out
