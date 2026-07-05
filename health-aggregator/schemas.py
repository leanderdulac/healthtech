from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthRecordCreate(BaseModel):
    user_id: str
    source: str
    timestamp: Optional[datetime] = None
    date: Optional[str] = None
    steps: int = 0
    heart_rate_bpm: Optional[float] = None
    hrv: Optional[float] = None
    spo2: Optional[float] = None
    calories_burned: float = 0
    sleep_duration_min: int = 0
    weight: Optional[float] = None
    body_fat: Optional[float] = None
    raw_data: Optional[Dict[str, Any]] = None


class HealthRecordRead(HealthRecordCreate):
    id: int
    record_id: str

    class Config:
        from_attributes = True


class AggregateRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, alias="patient_id")
    sources: Optional[List[str]] = Field(
        default=None,
        description="apple_health | google_fit | ble | fhir | tcn",
    )
    run_silver_gold: bool = False
    sync_clinical: bool = True
    run_prediction: bool = True

    class Config:
        populate_by_name = True


class DailyAggregation(BaseModel):
    date: str
    user_id: str
    source: Optional[str] = None
    total_steps: int = 0
    avg_heart_rate_bpm: Optional[float] = None
    avg_hrv: Optional[float] = None
    avg_spo2: Optional[float] = None
    total_calories: float = 0
    total_sleep_min: int = 0
    record_count: int = 0


class UserHealthSummary(BaseModel):
    user_id: str
    record_count: int = 0
    latest_metrics: Dict[str, float] = {}
    sources: List[str] = []
    clinical: Optional[Dict[str, Any]] = None
    prediction: Optional[Dict[str, Any]] = None
    daily: List[DailyAggregation] = []
    aggregated_at: datetime


class AggregationRunRead(BaseModel):
    id: int
    user_id: Optional[str]
    sources: List[str]
    records_count: int
    status: str
    detail: Dict[str, Any] = {}
    started_at: datetime
    finished_at: Optional[datetime]

    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    status: str
    service: str = "health-aggregator"
    version: str = "2.0.0"
    healthtech_root: Optional[str] = None