"""Pydantic schemas — validação e sanitização de entrada."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class WearableTelemetryRequest(BaseModel):
    model_config = {"extra": "allow"}

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device_id: Optional[str] = Field("wrist_wearable", max_length=64)
    timestamp: Optional[str] = Field(None, max_length=64)
    heart_rate: float = Field(..., ge=20.0, le=250.0)
    hrv_rmssd: Optional[float] = Field(40.0, ge=0.0, le=300.0)
    skin_temp: Optional[float] = Field(33.0, ge=25.0, le=45.0)
    spo2: Optional[float] = Field(98.0, ge=50.0, le=100.0)
    activity_level: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    ppg_signal: Optional[List[float]] = None
    filter_type: Optional[str] = Field("BMO", max_length=32)
    # Opcionais matriz de alertas / HBand
    blood_pressure_sys: Optional[float] = Field(None, ge=50.0, le=300.0)
    blood_pressure_dia: Optional[float] = Field(None, ge=20.0, le=200.0)
    glucose_mgdl: Optional[float] = Field(None, ge=20.0, le=1000.0)
    body_temp_c: Optional[float] = Field(None, ge=30.0, le=45.0)
    steps_drop_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    sleep_worsen_pct: Optional[float] = Field(None, ge=0.0, le=100.0)

    @field_validator("filter_type")
    @classmethod
    def validate_filter_type(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {"BMO", "Wavelet", "Butterworth", "Raw", "Adaptive"}:
            raise ValueError(
                "filter_type inválido. Valores aceitos: "
                "BMO, Wavelet, Butterworth, Raw, Adaptive."
            )
        return v


class WearableBatchIngestRequest(BaseModel):
    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    readings: List[WearableTelemetryRequest] = Field(..., min_length=1, max_length=200)


class BMOAnalysisRequest(BaseModel):
    signal: List[float] = Field(..., min_length=4)
    scales: Optional[List[int]] = None


class BMODenoiseRequest(BaseModel):
    signal: List[float] = Field(..., min_length=1)
    window_size: int = Field(8, ge=2, le=256)
    alpha: float = Field(0.5, ge=0.0, le=1.0)


class BMOHRVRequest(BaseModel):
    rr_intervals: List[float] = Field(..., min_length=4)


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    n_results: int = Field(3, ge=1, le=20)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class StatusResponse(BaseModel):
    status: str
    patients_tracked: int
    history_entries: int
    environment: str


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    request_id: Optional[str] = None


class ProcessedTelemetry(BaseModel):
    patient_id: str
    device_id: Optional[str] = None
    timestamp: str
    raw_telemetry: Dict[str, Any]
    cleaned_telemetry: Dict[str, Any]
    phantom_data: Dict[str, Any]
    anomaly_detection: Dict[str, Any]
