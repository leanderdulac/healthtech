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


def process_ingest_frame(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa uma leitura de wearable (denoising + anomalia local + phantom simples)."""
    hr = float(payload["heart_rate"])
    hrv = float(payload.get("hrv_rmssd") or 40.0)
    skin = float(payload.get("skin_temp") or 33.0)
    spo2 = payload.get("spo2")
    activity = float(payload.get("activity_level") or 0.0)
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

    # Phantom simplificado (estimativas heurísticas — produção usa Kalman no monólito)
    map_est = 70.0 + (bpm_clean - 70.0) * 0.3 + (skin - 33.0) * 2.0
    glucose_est = 95.0 + max(0.0, activity - 30) * 0.2
    vagal = max(0.0, min(1.0, hrv / 80.0))

    return {
        "patient_id": payload["patient_id"],
        "device_id": payload.get("device_id") or "wrist_wearable",
        "timestamp": payload.get("timestamp") or "",
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
        "phantom_data": {
            "map_mmhg": {
                "estimate": round(map_est, 2),
                "ci_lower": round(map_est - 5, 2),
                "ci_upper": round(map_est + 5, 2),
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
        },
        "anomaly_detection": anomaly,
    }
