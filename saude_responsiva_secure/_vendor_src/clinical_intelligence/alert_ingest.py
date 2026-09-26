"""
Integração da matriz de alertas com a ingestão de wearables (API / HBand).

Mapeia telemetria + phantom/estimativas → VitalSnapshot → AlertMatrixClassifier.assess()
+ detecção de discrepância amostra vs alerta (ex.: crise hipertensiva com FC 78–90).
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from src.clinical_intelligence.alert_discrepancy import evaluate_discrepancy
from src.clinical_intelligence.alert_matrix_rules import (
    AlertMatrixEngine,
    VitalSnapshot,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_REL = Path("data/models") / "alert_matrix_classifier.pkl"
_DEFAULT_PROVENANCE = "synthetic-unvalidated"
_SEV_RANK = {"none": 0, "leve": 1, "moderado": 2, "critico": 3}
_DISCREPANCY_DECISIONS = {"suppressed_sample_discrepancy"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def alert_ml_enabled() -> bool:
    """Piloto Next2U: ML desligado por omissão (só regras)."""
    return _env_flag("ALERT_ML_ENABLED", False)


def alert_ml_allow_suppress() -> bool:
    return _env_flag("ALERT_ML_ALLOW_SUPPRESS", False)


def alert_ml_allow_soft_alert() -> bool:
    return _env_flag("ALERT_ML_ALLOW_SOFT_ALERT", False)


def resolve_model_spec() -> str:
    """ALERT_MATRIX_MODEL_PATH (ficheiro ou gs://) ou dir + nome padrão."""
    explicit = (os.getenv("ALERT_MATRIX_MODEL_PATH") or "").strip()
    if explicit:
        return explicit
    model_dir = (os.getenv("ALERT_MATRIX_MODEL_DIR") or "data/models").strip()
    return str(Path(model_dir) / "alert_matrix_classifier.pkl")


def _cache_dir() -> Path:
    return Path(os.getenv("ALERT_ML_CACHE_DIR") or "/tmp/alert_matrix_cache")


def _download_gcs_uri(uri: str) -> Path:
    """Baixa gs://bucket/blob para cache local. Requer google-cloud-storage."""
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"URI GCS inválida: {uri}")
    bucket_name = parsed.netloc
    blob_name = parsed.path.lstrip("/")
    dest = _cache_dir() / bucket_name / blob_name
    if dest.is_file() and dest.stat().st_size > 0:
        logger.info("alert_ml cache hit path=%s", dest)
        return dest
    try:
        from google.cloud import storage  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "gcs_client_unavailable: instale google-cloud-storage "
            "ou use um caminho local em ALERT_MATRIX_MODEL_PATH"
        ) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = storage.Client()
    client.bucket(bucket_name).blob(blob_name).download_to_filename(str(dest))
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise RuntimeError(f"download GCS vazio: {uri}")
    logger.info("alert_ml cached gs://%s/%s -> %s", bucket_name, blob_name, dest)
    return dest


def materialize_model_path(spec: str) -> Path:
    """Resolve spec local ou gs:// para um ficheiro .pkl no disco."""
    if spec.startswith("gs://"):
        return _download_gcs_uri(spec)
    path = Path(spec)
    if path.is_dir():
        return path / "alert_matrix_classifier.pkl"
    return path


def _model_version(local_path: Path, clf: Any) -> str:
    env_v = (os.getenv("ALERT_ML_MODEL_VERSION") or "").strip()
    if env_v:
        return env_v
    meta_path = local_path.parent / "alert_matrix_classifier_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key in ("version", "model_version"):
                if meta.get(key):
                    return str(meta[key])
        except Exception:
            pass
    metrics = getattr(clf, "metrics_", None) or {}
    if isinstance(metrics, dict) and metrics.get("version"):
        return str(metrics["version"])
    return (os.getenv("ALERT_ML_PROVENANCE") or _DEFAULT_PROVENANCE).strip() or _DEFAULT_PROVENANCE


@lru_cache(maxsize=1)
def get_alert_ml_state() -> Dict[str, Any]:
    """Carrega o classificador uma vez e emite a linha de estado do startup."""
    spec = resolve_model_spec()
    if not alert_ml_enabled():
        logger.info("alert_ml=disabled reason=ALERT_ML_ENABLED=false")
        return {
            "classifier": None,
            "enabled": False,
            "reason": "ALERT_ML_ENABLED=false",
            "model": spec,
            "version": "",
        }
    try:
        local = materialize_model_path(spec)
        if not local.is_file():
            reason = f"model_missing path={local}"
            logger.warning("alert_ml=disabled reason=%s", reason)
            return {
                "classifier": None,
                "enabled": False,
                "reason": reason,
                "model": str(local),
                "version": "",
            }
        from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier

        clf = AlertMatrixClassifier.load(local)
        version = _model_version(local, clf)
        logger.info("alert_ml=enabled model=%s version=%s", local, version)
        return {
            "classifier": clf,
            "enabled": True,
            "reason": "",
            "model": str(local),
            "version": version,
        }
    except Exception as exc:
        reason = f"load_failed: {exc}"
        logger.warning("alert_ml=disabled reason=%s", reason)
        return {
            "classifier": None,
            "enabled": False,
            "reason": reason,
            "model": spec,
            "version": "",
        }


def _load_classifier():
    """Lazy load do classificador treinado; None se flag off ou indisponível."""
    return get_alert_ml_state().get("classifier")


def clear_classifier_cache() -> None:
    get_alert_ml_state.cache_clear()


def log_alert_ml_startup() -> Dict[str, Any]:
    """Força o log `alert_ml=enabled|disabled` no lifespan da API."""
    return get_alert_ml_state()


def _hit_severity(hit: Any) -> str:
    if isinstance(hit, dict):
        return str(hit.get("severity") or "none")
    return str(getattr(hit, "severity", "none") or "none")


def _apply_pilot_ml_guards(full: Dict[str, Any]) -> Dict[str, Any]:
    """ML no piloto é sugestão: não suprime alerta de regra nem rebaixa ★★★.

    A supressão por discrepância amostra↔alerta (regras, não ML) mantém-se.
    Soft-alert e supressão por ML só se as flags explícitas estiverem ligadas.
    """
    out = dict(full)
    hits = out.get("rule_hits") or []
    rule_max = "none"
    for hit in hits:
        sev = _hit_severity(hit)
        if _SEV_RANK.get(sev, 0) > _SEV_RANK.get(rule_max, 0):
            rule_max = sev
    had_rule_alert = bool(hits) and rule_max != "none"
    stars = int(out.get("stars") or 0)
    three_star = stars >= 3 or rule_max == "critico"
    decision = str(out.get("decision") or "")
    discrepancy = decision in _DISCREPANCY_DECISIONS

    if decision == "ml_soft_alert_no_rule" and not alert_ml_allow_soft_alert():
        out["is_true_alert"] = False
        out["is_false_positive"] = False
        out["severity"] = "none"
        out["decision"] = "ml_suggestion_only"
        out["primary_alert_name"] = None
        out["primary_rule_id"] = None

    if (
        had_rule_alert
        and not out.get("is_true_alert")
        and not discrepancy
        and not alert_ml_allow_suppress()
    ):
        out["is_true_alert"] = True
        out["is_false_positive"] = False
        out["severity"] = rule_max
        out["decision"] = "rule_match_ml_suggestive_only"
        if hits and not out.get("primary_alert_name"):
            first = hits[0]
            if isinstance(first, dict):
                out["primary_alert_name"] = first.get("name")
                out["primary_rule_id"] = first.get("rule_id")
        out.pop("suppressed_alert_name", None)
        out.pop("suppressed_rule_id", None)

    if three_star and had_rule_alert and not discrepancy:
        if out.get("severity") != "critico":
            out["severity"] = "critico"
        if not out.get("is_true_alert") and not alert_ml_allow_suppress():
            out["is_true_alert"] = True
            out["is_false_positive"] = False
            out["decision"] = "rule_match_ml_suggestive_only"

    ml = out.get("ml")
    if isinstance(ml, dict):
        annotated = dict(ml)
        annotated["suggestive_only"] = not (
            alert_ml_allow_suppress() or alert_ml_allow_soft_alert()
        )
        annotated["role"] = "suggestion"
        annotated["provenance"] = (
            os.getenv("ALERT_ML_PROVENANCE") or _DEFAULT_PROVENANCE
        ).strip() or _DEFAULT_PROVENANCE
        out["ml"] = annotated
    return out


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
    pas = pad = glucose = None
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
    glu_prev = _num(prev.get("glucose_mgdl") or prev.get("glucose"))
    spo2_prev = _num(prev.get("spo2"))
    consecutive = 1
    cur_spo2 = _num(spo2)
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
    hr_now = _num(heart_rate)
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
        full = _apply_pilot_ml_guards(full)
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
        "vitals_used": full.get("vitals") or vitals.to_feature_dict(),
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
