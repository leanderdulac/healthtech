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
    meta: Dict[str, Any] = {
        "bp_source": "unknown",
        "glucose_source": "unknown",
        "bp_reliable": True,
        "glucose_reliable": True,
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
    if temp is not None and 25.0 <= temp < 35.0:
        body = _num(hband.get("body_temp_c")) or _num(raw.get("body_temp_c"))
        if body is not None:
            temp = body

    steps_drop = _num(hband.get("steps_drop_pct")) or _num(raw.get("steps_drop_pct"))
    sleep_worsen = _num(hband.get("sleep_worsen_pct")) or _num(raw.get("sleep_worsen_pct"))
    hr_rise = _num(hband.get("hr_baseline_rise")) or _num(raw.get("hr_baseline_rise"))
    spo2_drop = _num(hband.get("spo2_drop_points")) or _num(raw.get("spo2_drop_points"))
    consciousness = bool(
        hband.get("consciousness_altered") or raw.get("consciousness_altered")
    )

    if hr_rise is None and activity_level is not None and float(activity_level) > 40:
        hr_rise = min(25.0, float(activity_level) * 0.2)

    # Sono "Bom" implícito se não informado
    if sleep_worsen is None:
        sleep_worsen = 5.0
    if steps_drop is None:
        steps_drop = 5.0

    vitals = VitalSnapshot(
        pas=pas,
        pad=pad,
        hr=_num(heart_rate),
        spo2=_num(spo2),
        temp_c=temp,
        glucose_mgdl=glucose,
        steps_drop_pct=steps_drop,
        sleep_worsen_pct=sleep_worsen,
        hr_baseline_rise=hr_rise,
        spo2_drop_points=spo2_drop,
        consciousness_altered=consciousness,
    )
    return vitals, meta


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
) -> Dict[str, Any]:
    """
    Avalia alertas clínicos para um frame de ingestão.

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
    )

    clf = _load_classifier()
    if clf is not None:
        full = clf.assess(
            vitals,
            source_meta=meta,
        )
    else:
        engine = AlertMatrixEngine()
        rule = engine.evaluate(vitals)
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
        }
        full = _apply_discrepancy(full, vitals, meta)

    # Payload estável para API / WebSocket / dashboard
    return {
        "is_true_alert": bool(full.get("is_true_alert")),
        "is_false_positive": bool(full.get("is_false_positive")),
        "severity": full.get("severity") or "none",
        "confidence": round(float(full.get("confidence") or 0.0), 4),
        "decision": full.get("decision"),
        "primary_alert_name": full.get("primary_alert_name")
        if full.get("is_true_alert")
        else None,
        "primary_rule_id": full.get("primary_rule_id") if full.get("is_true_alert") else None,
        "rule_hits": full.get("rule_hits") or [],
        "rule_explanation": full.get("rule_explanation"),
        "vitals_used": full.get("vitals") or vitals.to_feature_dict(),
        "ml": full.get("ml"),
        "discrepancy": full.get("discrepancy"),
        "source_meta": full.get("source_meta") or meta,
        "suppressed_alert_name": full.get("suppressed_alert_name"),
        "engine": "alert_matrix_ml" if clf is not None else "alert_matrix_rules",
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
