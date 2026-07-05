from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    patient_id: str
    display_name: str = ""
    birth_year: Optional[int] = None
    risk_factor: float = 0.0


class PatientRead(PatientCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TelemetryRead(BaseModel):
    id: int
    event_id: str
    patient_id: str
    source: str
    metric_type: str
    metric_value: float
    unit: str
    vendor: str
    timestamp_utc: datetime

    class Config:
        from_attributes = True


class ClinicalSnapshotRead(BaseModel):
    id: int
    patient_id: str
    conditions: List[str] = []
    medications: List[str] = []
    fhir_live: bool = False
    synced_at: datetime

    class Config:
        from_attributes = True


class PredictionRead(BaseModel):
    id: int
    patient_id: str
    prob_6h: float
    prob_24h: float
    prob_72h: float
    horizon_at_risk: str
    conformal_intervals: Dict[str, List[float]] = {}
    modo: str
    predicted_at: datetime

    class Config:
        from_attributes = True


class AggregateRequest(BaseModel):
    patient_id: Optional[str] = None
    sources: Optional[List[str]] = Field(
        default=None,
        description="apple_health | google_fit | ble | fhir | tcn",
    )
    run_silver_gold: bool = False
    sync_clinical: bool = True
    run_prediction: bool = True


class PatientHealthSummary(BaseModel):
    patient_id: str
    display_name: str = ""
    telemetry_count: int = 0
    latest_metrics: Dict[str, float] = {}
    clinical: Optional[ClinicalSnapshotRead] = None
    prediction: Optional[PredictionRead] = None
    sources: List[str] = []
    aggregated_at: datetime


class AggregationRunRead(BaseModel):
    id: int
    patient_id: Optional[str]
    sources: List[str]
    telemetry_count: int
    status: str
    detail: Dict[str, Any] = {}
    started_at: datetime
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    status: str
    service: str = "health-aggregator"
    version: str = "1.0.0"
    healthtech_root: Optional[str] = None