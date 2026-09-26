"""Núcleo de análise de sinal (BMO / denoise / HRV) com fallback local."""

from __future__ import annotations

import os
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


def _opt_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Mesmo flag de src.clinical_intelligence.alert_ingest.PHANTOM_VITALS_ENV.
_PHANTOM_VITALS_ENV = "ALERT_ALLOW_PHANTOM_VITALS"


def _phantom_vitals_enabled() -> bool:
    return str(os.getenv(_PHANTOM_VITALS_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _phantom_estimates(bpm_clean: float, hrv: float, skin: float, activity: float) -> Dict[str, Any]:
    """Phantom simplificado (DEMO) — estimativas heurísticas, não medidas.

    Só usado com opt-in explícito ALERT_ALLOW_PHANTOM_VITALS=1. Produção usa
    Kalman no monólito; o ingest secure nunca envia isto à matriz por padrão.
    """
    map_est = 70.0 + (bpm_clean - 70.0) * 0.3 + (skin - 33.0) * 2.0
    glucose_est = 95.0 + max(0.0, activity - 30) * 0.2
    vagal = max(0.0, min(1.0, hrv / 80.0))
    # PAS/PAD a partir do MAP (PP≈40)
    pas_est = map_est + 13.3
    pad_est = map_est - 6.7
    return {
        "map_mmhg": {
            "estimate": round(map_est, 2),
            "ci_lower": round(map_est - 5, 2),
            "ci_upper": round(map_est + 5, 2),
            "reliable": True,
        },
        "systolic_bp": {
            "estimate": round(pas_est, 2),
            "ci_lower": round(pas_est - 8, 2),
            "ci_upper": round(pas_est + 8, 2),
            "reliable": True,
        },
        "diastolic_bp": {
            "estimate": round(pad_est, 2),
            "ci_lower": round(pad_est - 6, 2),
            "ci_upper": round(pad_est + 6, 2),
            "reliable": True,
        },
        "glucose_mgdl": {
            "estimate": round(glucose_est, 2),
            "ci_lower": round(glucose_est - 10, 2),
            "ci_upper": round(glucose_est + 10, 2),
            "reliable": activity < 80,
        },
        "vagal_tone": {
            "estimate": round(vagal, 3),
            "ci_lower": round(max(0, vagal - 0.1), 3),
            "ci_upper": round(min(1, vagal + 0.1), 3),
            "reliable": True,
        },
    }


def process_ingest_frame(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa uma leitura de wearable (denoising + anomalia local + matriz).

    Nunca inventa vitais: sinais ausentes seguem None até a matriz de alertas
    (desconhecido ≠ valor). Phantom/simulação só com ALERT_ALLOW_PHANTOM_VITALS=1.
    """
    hr = float(payload["heart_rate"])
    hrv = _opt_float(payload.get("hrv_rmssd"))
    skin = _opt_float(payload.get("skin_temp"))
    spo2 = payload.get("spo2")
    activity = _opt_float(payload.get("activity_level"))
    filter_type = payload.get("filter_type") or "BMO"
    ppg = payload.get("ppg_signal")

    bpm_clean = hr
    bmo_metrics: Dict[str, Any] = {}
    if ppg and len(ppg) >= 4:
        bmo_metrics = multiscale_bmo(ppg)
        if filter_type == "BMO":
            filtered = denoise_signal(ppg, window_size=8, alpha=0.5)
            mean_f = float(np.mean(filtered))
            if mean_f > 30:
                bpm_clean = mean_f

    is_anomalia = bpm_clean > 100 or bpm_clean < 40 or (spo2 is not None and float(spo2) < 92)
    anomaly = {
        "alerta": bool(is_anomalia),
        "score": 0.95 if is_anomalia else 0.05,
        "modo": "Detecção Local BMO",
    }

    # Phantom/simulação: só com opt-in explícito (default OFF). Sem o flag,
    # phantom_data = {} e nenhuma PA/glicose estimada chega à matriz.
    allow_phantom = _phantom_vitals_enabled()
    phantom_data: Dict[str, Any] = {}
    if allow_phantom:
        phantom_data = _phantom_estimates(
            bpm_clean,
            hrv if hrv is not None else 40.0,
            skin if skin is not None else 33.0,
            activity if activity is not None else 0.0,
        )

    # Matriz de alertas clínicos (regras + ML de falsos positivos)
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
    body_temp = _opt_float(payload.get("body_temp_c"))
    temp_for_matrix = body_temp if body_temp is not None else skin
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
            heart_rate=bpm_clean,
            spo2=float(spo2) if spo2 is not None else None,
            skin_temp=temp_for_matrix,
            hrv_rmssd=hrv,
            activity_level=activity,
            phantom=phantom_data,
            hband_ext=hband_ext,
            raw_telemetry=payload,
            allow_phantom_vitals=allow_phantom,
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

    return {
        "patient_id": payload["patient_id"],
        "device_id": payload.get("device_id") or "wrist_wearable",
        "timestamp": payload.get("timestamp") or "",
        "received_at": payload.get("received_at") or payload.get("timestamp") or "",
        "last_seen_local": payload.get("last_seen_local"),
        "device_time_local": payload.get("device_time_local"),
        "ingest_source": payload.get("ingest_source") or "companion_manual",
        "raw_telemetry": {
            "heart_rate_bpm": hr,
            "hrv_rmssd_ms": hrv,
            "skin_temp_celsius": skin,
            "spo2_percent": spo2,
            "activity_level": activity,
        },
        "cleaned_telemetry": {
            "heart_rate_clean": round(bpm_clean, 2),
            "filter_applied": filter_type,
            "bmo_metrics": bmo_metrics,
        },
        "phantom_data": phantom_data,
        "anomaly_detection": anomaly,
        "clinical_alerts": clinical_alerts,
    }
