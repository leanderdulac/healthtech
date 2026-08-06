"""Análise de sinais: BMO / denoise / HRV."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.models.schemas import BMOAnalysisRequest, BMODenoiseRequest, BMOHRVRequest
from app.security.auth import require_scope
from app.services import signal_core

router = APIRouter(prefix="/api/v1/signal", tags=["signal"])


@router.post("/bmo-analysis")
def analyze_bmo(
    payload: BMOAnalysisRequest,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Perfil multi-escala BMO/VMO. Requer wearables:read."""
    _ = request
    return signal_core.multiscale_bmo(payload.signal, scales=payload.scales)


@router.post("/bmo-denoise")
def denoise_bmo(
    payload: BMODenoiseRequest,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """Denoising adaptativo BMO. Requer wearables:write."""
    _ = request
    filtered = signal_core.denoise_signal(
        payload.signal, window_size=payload.window_size, alpha=payload.alpha
    )
    return {
        "filtered_signal": filtered,
        "original_len": len(payload.signal),
        "window_size": payload.window_size,
        "alpha": payload.alpha,
    }


@router.post("/hrv/bmo-metrics")
def bmo_hrv_metrics(
    payload: BMOHRVRequest,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Métricas de HRV no domínio BMO. Requer wearables:read."""
    _ = request
    return signal_core.hrv_bmo_metrics(payload.rr_intervals)
