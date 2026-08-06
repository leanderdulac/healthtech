"""
Integração da matriz de alertas com a ingestão de wearables (API / HBand).

Mapeia telemetria + phantom/estimativas → VitalSnapshot → AlertMatrixClassifier.assess().
Carrega o modelo de forma lazy e degradável (só regras se o .pkl não existir).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

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
) -> VitalSnapshot:
    """
    Monta VitalSnapshot a partir do payload de ingestão e estimativas phantom.

    Prioridade de PA/glicose:
      1. campos explícitos HBand (_hband / extras)
      2. phantom_data do monólito (systolic_bp, diastolic_bp, glucose, map)
      3. None (regra não usa o eixo)
    """
    hband = hband_ext or {}
    raw = raw_telemetry or {}
    ph = phantom or {}

    def phantom_est(*keys: str) -> Optional[float]:
        for k in keys:
            node = ph.get(k)
            if isinstance(node, dict) and "estimate" in node:
                return _num(node["estimate"])
            if node is not None and not isinstance(node, dict):
                return _num(node)
        return None

    pas = (
        _num(hband.get("blood_pressure_sys"))
        or _num(raw.get("blood_pressure_sys"))
        or phantom_est("systolic_bp", "sbp", "pas")
    )
    pad = (
        _num(hband.get("blood_pressure_dia"))
        or _num(raw.get("blood_pressure_dia"))
        or phantom_est("diastolic_bp", "dbp", "pad")
    )
    # Fallback MAP → aproximar PAS/PAD se só MAP existir
    if pas is None and pad is None:
        map_v = phantom_est("map_mmhg", "map", "mean_arterial_pressure")
        if map_v is not None:
            # MAP ≈ (PAS + 2*PAD)/3; assume PP=40 → PAS=MAP+13.3, PAD=MAP-6.7
            pas = map_v + 13.3
            pad = map_v - 6.7

    glucose = (
        _num(hband.get("glucose_mgdl"))
        or _num(raw.get("glucose_mgdl"))
        or phantom_est("glucose_mgdl", "glucose", "blood_glucose")
    )
    resp = (
        _num(hband.get("respiratory_rate"))
        or _num(raw.get("respiratory_rate"))
        or phantom_est("respiratory_rate")
    )

    temp = _num(skin_temp)
    # skin_temp wearable ~33°C; matriz usa corporal ~36–40.
    # Se valor parece de pele (<35), converter heurística para corporal de referência.
    if temp is not None and 25.0 <= temp < 35.0:
        # Mantém valor de pele para hipo termia de superfície; febre via hband explicit
        body = _num(hband.get("body_temp_c")) or _num(raw.get("body_temp_c"))
        if body is not None:
            temp = body
        # senão deixa skin; regras de febre (≥38.1) não disparam com 33°C (correto)

    steps_drop = _num(hband.get("steps_drop_pct")) or _num(raw.get("steps_drop_pct"))
    sleep_worsen = _num(hband.get("sleep_worsen_pct")) or _num(raw.get("sleep_worsen_pct"))
    hr_rise = _num(hband.get("hr_baseline_rise")) or _num(raw.get("hr_baseline_rise"))
    spo2_drop = _num(hband.get("spo2_drop_points")) or _num(raw.get("spo2_drop_points"))
    consciousness = bool(
        hband.get("consciousness_altered") or raw.get("consciousness_altered")
    )

    # activity_level 0–100 como proxy leve de stress (não força regra sozinho)
    if hr_rise is None and activity_level is not None and float(activity_level) > 40:
        hr_rise = min(25.0, float(activity_level) * 0.2)

    return VitalSnapshot(
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
    vitals = vitals_from_ingest_context(
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
        full = clf.assess(vitals)
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

    # Payload estável para API / WebSocket / dashboard
    return {
        "is_true_alert": bool(full.get("is_true_alert")),
        "is_false_positive": bool(full.get("is_false_positive")),
        "severity": full.get("severity") or "none",
        "confidence": round(float(full.get("confidence") or 0.0), 4),
        "decision": full.get("decision"),
        "primary_alert_name": full.get("primary_alert_name"),
        "primary_rule_id": full.get("primary_rule_id"),
        "rule_hits": full.get("rule_hits") or [],
        "rule_explanation": full.get("rule_explanation"),
        "vitals_used": full.get("vitals") or vitals.to_feature_dict(),
        "ml": full.get("ml"),
        "engine": "alert_matrix_ml" if clf is not None else "alert_matrix_rules",
    }


def merge_anomaly_with_alerts(
    anomaly: Dict[str, Any],
    clinical_alerts: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ajusta flag de anomalia local com a matriz:
      - true alert → reforça alerta
      - FP suprimido → não escalar anomalia isolada por FC limítrofe
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
    elif clinical_alerts.get("is_false_positive") and clinical_alerts.get("severity") == "none":
        # Suprime alerta ruidoso de heurística local se matriz classifica FP
        if out.get("modo") in {"Detecção Local BMO", "Deteção Local", "Deteção Local BMO"}:
            out["alerta"] = False
            out["score"] = min(float(out.get("score") or 0.05), 0.15)
            out["modo"] = "Suprimido (falso positivo / matriz)"
            out["suppressed_by_matrix"] = True
    return out
