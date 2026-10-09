"""Núcleo de análise de sinal (BMO / denoise / HRV) com fallback local."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np


def _try_parent_bmo():
    try:
        from src.signal_processing import BMOAnalyzer  # type: ignore
        from src.signal_processing.noise_separation import BMODenoiser  # type: ignore
        from src.phantom_data import HRVAnalyzer  # type: ignore

        return BMOAnalyzer, BMODenoiser, HRVAnalyzer
    except Exception:
        return None, None, None


def multiscale_bmo(signal: List[float], scales: Optional[List[int]] = None) -> Dict[str, Any]:
    BMOAnalyzer, _, _ = _try_parent_bmo()
    arr = np.asarray(signal, dtype=float)
    if BMOAnalyzer is not None:
        analyzer = BMOAnalyzer(default_scales=scales)
        return analyzer.multiscale_bmo_profile(arr, scales=scales)

    # Fallback: amplitude média e variância multi-escala simples
    used_scales = scales or [2, 4, 8, 16]
    profiles = []
    for s in used_scales:
        if len(arr) < s * 2:
            continue
        windows = [arr[i : i + s] for i in range(0, len(arr) - s + 1, s)]
        if not windows:
            continue
        osc = float(np.mean([np.ptp(w) for w in windows]))
        profiles.append({"scale": s, "bmo": round(osc, 4), "vmo": round(float(np.var(arr)), 4)})
    return {
        "n_samples": len(arr),
        "scales": profiles,
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr)), 4),
        "engine": "fallback",
    }


def denoise_signal(signal: List[float], window_size: int = 8, alpha: float = 0.5) -> List[float]:
    _, BMODenoiser, _ = _try_parent_bmo()
    arr = np.asarray(signal, dtype=float)
    if BMODenoiser is not None:
        denoiser = BMODenoiser(window_size=window_size, alpha=alpha)
        return denoiser.denoise(arr).tolist()

    # Fallback: média móvel ponderada
    w = max(2, window_size)
    if len(arr) < w:
        return arr.tolist()
    kernel = np.ones(w) / w
    padded = np.pad(arr, (w // 2, w - 1 - w // 2), mode="edge")
    smoothed = np.convolve(padded, kernel, mode="valid")
    # blend com original via alpha
    blended = alpha * smoothed[: len(arr)] + (1 - alpha) * arr
    return blended.tolist()


def hrv_bmo_metrics(rr_intervals: List[float]) -> Dict[str, Any]:
    _, _, HRVAnalyzer = _try_parent_bmo()
    arr = np.asarray(rr_intervals, dtype=float)
    if HRVAnalyzer is not None:
        hrv = HRVAnalyzer()
        return hrv.compute_bmo_domain(arr)

    # Fallback time-domain HRV
    diff = np.diff(arr)
    rmssd = float(np.sqrt(np.mean(diff**2))) if len(diff) else 0.0
    sdnn = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    mean_rr = float(np.mean(arr))
    return {
        "mean_rr_ms": round(mean_rr, 2),
        "sdnn_ms": round(sdnn, 2),
        "rmssd_ms": round(rmssd, 2),
        "n_intervals": len(arr),
        "engine": "fallback",
    }


def _record_pilot(frame: Dict[str, Any]) -> Optional[str]:
    try:
        from app.services.pilot_review import record_ingest

        return record_ingest(frame)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Falha ao gravar revisão do piloto: %s", exc)
        return None


def _has(payload: Dict[str, Any], key: str) -> bool:
    return key in payload and payload.get(key) is not None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _measured_blood_pressure(payload: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """Pressão que o app mandou. O schema antigo não tem o objeto aninhado."""
    nested = payload.get("blood_pressure") if _has(payload, "blood_pressure") else None
    if isinstance(nested, dict):
        systolic = _as_float(nested.get("systolic", nested.get("sys")))
        diastolic = _as_float(nested.get("diastolic", nested.get("dia")))
        return systolic, diastolic
    if _has(payload, "blood_pressure_sys") or _has(payload, "blood_pressure_dia"):
        return _as_float(payload.get("blood_pressure_sys")), _as_float(payload.get("blood_pressure_dia"))
    return None, None


def _measured_raw(
    payload: Dict[str, Any],
    *,
    heart_rate: float,
    hrv_rmssd: Optional[float],
    hrv_score: Optional[float],
    skin_measured: Optional[float],
    spo2: Optional[float],
    activity: Optional[float],
    systolic: Optional[float],
    diastolic: Optional[float],
) -> Dict[str, Any]:
    """Sinais que chegaram no POST. Ausência fica de fora — não vira 98/40/33."""
    raw: Dict[str, Any] = {
        "heart_rate_bpm": heart_rate,
        "ingest_source": str(payload.get("ingest_source") or "companion_manual"),
    }
    if hrv_rmssd is not None:
        raw["hrv_rmssd_ms"] = hrv_rmssd
    if hrv_score is not None and hrv_score > 0:
        raw["hrv_score"] = hrv_score
    if skin_measured is not None and _has(payload, "skin_temp"):
        raw["skin_temp_celsius"] = skin_measured
    if _has(payload, "temperature"):
        temperature = _as_float(payload.get("temperature"))
        if temperature is not None and temperature > 0:
            raw["temperature_celsius"] = temperature
    if _has(payload, "body_temp_c"):
        body = _as_float(payload.get("body_temp_c"))
        if body is not None:
            raw["body_temp_celsius"] = body
    if spo2 is not None:
        raw["spo2_percent"] = spo2
    if activity is not None:
        raw["activity_level"] = activity
    if _has(payload, "glucose_mgdl"):
        glucose = _as_float(payload.get("glucose_mgdl"))
        if glucose is not None:
            raw["glucose_mgdl"] = glucose
    if "wear_status" in payload and payload.get("wear_status") is not None:
        raw["wear_status"] = bool(payload.get("wear_status"))
    if _has(payload, "steps"):
        steps = _as_float(payload.get("steps"))
        if steps is not None and steps >= 0:
            raw["steps"] = int(steps)
    if systolic is not None and diastolic is not None and systolic > 0 and diastolic > 0:
        raw["blood_pressure_sys"] = systolic
        raw["blood_pressure_dia"] = diastolic
    model = payload.get("device_model") if _has(payload, "device_model") else None
    if isinstance(model, str) and model.strip():
        raw["device_model"] = model.strip()[:80]
    calories = _as_float(payload.get("calories")) if _has(payload, "calories") else None
    if calories is not None and calories > 0:
        raw["calories"] = calories
    distance = _as_float(payload.get("distance")) if _has(payload, "distance") else None
    if distance is not None and distance > 0:
        raw["distance_m"] = distance
    return raw


def _resolve_heart_rate(measured: float, ppg: Optional[List[float]]) -> tuple[Optional[float], Dict[str, Any]]:
    """FC medida. A onda PPG não substitui o batimento."""
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from src.clinical_intelligence.alert_ingest import resolve_heart_rate

        return resolve_heart_rate(measured, ppg)
    except Exception:
        samples = list(ppg) if ppg else []
        accepted = measured if 20.0 <= float(measured) <= 250.0 else None
        return accepted, {
            "heart_rate_source": "measured" if accepted is not None else "rejected",
            "ppg_role": "waveform" if len(samples) >= 4 else "absent",
            "ppg_samples": len(samples),
            "ppg_not_used_as_bpm": len(samples) >= 4,
        }


def _with_prior_reading(payload: Dict[str, Any]) -> Dict[str, Any]:
    """A leitura anterior do mesmo paciente, se ainda cabe na janela."""
    patient_id = str(payload.get("patient_id") or "")
    if not patient_id:
        return payload
    try:
        from app.services import telemetry_store
        from src.clinical_intelligence.alert_ingest import attach_previous_reading
    except Exception:
        return payload
    try:
        previous = telemetry_store.get_latest(patient_id)
    except Exception:
        return payload
    return attach_previous_reading(payload, previous)


def process_ingest_frame(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa uma leitura de wearable (denoising + anomalia local + phantom simples)."""
    payload = _with_prior_reading(dict(payload))
    systolic, diastolic = _measured_blood_pressure(payload)
    if systolic is not None and systolic > 0 and not _has(payload, "blood_pressure_sys"):
        payload["blood_pressure_sys"] = systolic
    if diastolic is not None and diastolic > 0 and not _has(payload, "blood_pressure_dia"):
        payload["blood_pressure_dia"] = diastolic

    hr = float(payload["heart_rate"])
    # 40 ms e 33 °C são só o prior interno do phantom. Não são medição.
    hrv_rmssd = _as_float(payload.get("hrv_rmssd")) if _has(payload, "hrv_rmssd") else None
    hrv_score = _as_float(payload.get("hrv_score")) if _has(payload, "hrv_score") else None
    skin_measured = _as_float(payload.get("skin_temp")) if _has(payload, "skin_temp") else None
    if skin_measured is None and _has(payload, "temperature"):
        temperature = _as_float(payload.get("temperature"))
        if temperature is not None and temperature > 0:
            skin_measured = temperature
    if skin_measured is None and _has(payload, "body_temp_c"):
        skin_measured = _as_float(payload.get("body_temp_c"))
    spo2 = _as_float(payload.get("spo2")) if _has(payload, "spo2") else None
    activity = _as_float(payload.get("activity_level")) if _has(payload, "activity_level") else None
    hrv_prior = hrv_rmssd if hrv_rmssd is not None else 40.0
    skin_prior = skin_measured if skin_measured is not None else 33.0
    activity_prior = activity if activity is not None else 0.0
    filter_type = payload.get("filter_type") or "BMO"
    ppg = payload.get("ppg_signal")

    bpm_clean, hr_note = _resolve_heart_rate(hr, ppg if isinstance(ppg, list) else None)
    bmo_metrics: Dict[str, Any] = {}
    if isinstance(ppg, list) and len(ppg) >= 4:
        bmo_metrics = multiscale_bmo(ppg)

    is_anomalia = (
        bpm_clean is not None and (bpm_clean > 100 or bpm_clean < 40)
    ) or (spo2 is not None and float(spo2) < 92)
    anomaly = {
        "alerta": bool(is_anomalia),
        "score": 0.95 if is_anomalia else 0.05,
        "modo": "Detecção Local BMO",
    }

    # Heurística local. Não é medição e não entra na matriz (reliable=False).
    hr_prior = bpm_clean if bpm_clean is not None else 70.0
    map_est = 70.0 + (hr_prior - 70.0) * 0.3 + (skin_prior - 33.0) * 2.0
    glucose_est = 95.0 + max(0.0, activity_prior - 30) * 0.2
    vagal = max(0.0, min(1.0, hrv_prior / 80.0))
    pas_est = map_est + 13.3
    pad_est = map_est - 6.7

    def _heuristic(estimate: float, half_width: float) -> Dict[str, Any]:
        return {
            "estimate": round(estimate, 2),
            "ci_lower": round(estimate - half_width, 2),
            "ci_upper": round(estimate + half_width, 2),
            "reliable": False,
            "method": "heuristic",
        }

    phantom_data = {
        "map_mmhg": _heuristic(map_est, 5),
        "systolic_bp": _heuristic(pas_est, 8),
        "diastolic_bp": _heuristic(pad_est, 6),
        "glucose_mgdl": _heuristic(glucose_est, 10),
        "vagal_tone": {
            "estimate": round(vagal, 3),
            "ci_lower": round(max(0, vagal - 0.1), 3),
            "ci_upper": round(min(1, vagal + 0.1), 3),
            "reliable": False,
            "method": "heuristic",
        },
    }

    # Piloto: só a matriz de regras. O classificador sintético não altera o alerta.
    hband_ext = payload.get("_hband") or payload.get("hband") or {}
    if not isinstance(hband_ext, dict):
        hband_ext = {}
    else:
        hband_ext = dict(hband_ext)
    for key in (
        "blood_pressure_sys",
        "blood_pressure_dia",
        "glucose_mgdl",
        "body_temp_c",
        "steps_drop_pct",
        "sleep_worsen_pct",
    ):
        if payload.get(key) is not None:
            hband_ext[key] = payload[key]
    body_temp = payload.get("body_temp_c")
    try:
        # Garantir monorepo no path quando a API secure roda na raiz
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from src.clinical_intelligence.alert_ingest import (
            assess_ingest_alerts,
            merge_anomaly_with_alerts,
        )

        clinical_alerts = assess_ingest_alerts(
            heart_rate=hr,
            spo2=float(spo2) if spo2 is not None else None,
            skin_temp=float(body_temp) if body_temp is not None else skin_measured,
            hrv_rmssd=hrv_rmssd,
            activity_level=activity,
            phantom=phantom_data,
            hband_ext=hband_ext,
            raw_telemetry=payload,
            rules_only=True,
        )
        anomaly = merge_anomaly_with_alerts(anomaly, clinical_alerts)
    except Exception as exc:
        clinical_alerts = {
            "is_true_alert": False,
            "is_false_positive": False,
            "severity": "none",
            "decision": "unavailable",
            "error": str(exc),
        }

    frame = {
        "patient_id": payload["patient_id"],
        "device_id": payload.get("device_id") or "wrist_wearable",
        "timestamp": payload.get("timestamp") or "",
        "received_at": payload.get("received_at") or payload.get("timestamp") or "",
        "last_seen_local": payload.get("last_seen_local"),
        "device_time_local": payload.get("device_time_local"),
        "ingest_source": str(payload.get("ingest_source") or "companion_manual"),
        "raw_telemetry": _measured_raw(
            payload,
            heart_rate=hr,
            hrv_rmssd=hrv_rmssd,
            hrv_score=hrv_score,
            skin_measured=skin_measured,
            spo2=spo2,
            activity=activity,
            systolic=systolic,
            diastolic=diastolic,
        ),
        "cleaned_telemetry": {
            "heart_rate_clean": None if bpm_clean is None else round(bpm_clean, 2),
            "heart_rate_source": hr_note.get("heart_rate_source"),
            "ppg_role": hr_note.get("ppg_role"),
            "ppg_samples": hr_note.get("ppg_samples", 0),
            "filter_applied": filter_type,
            "bmo_metrics": bmo_metrics,
        },
        "phantom_data": phantom_data,
        "anomaly_detection": anomaly,
        "clinical_alerts": clinical_alerts,
    }
    event_id = _record_pilot(frame)
    if event_id and isinstance(clinical_alerts, dict):
        clinical_alerts["review_event_id"] = event_id
    return frame
