"""
Schemas Pydantic — contrato de payload do companion Android HBand/Veepoo.

Espelha OpenAPI em docs/openapi/hband-wearable.yaml e os modelos do SDK
(OriginData3, HeartData, Spo2hData, SleepData, PPG raw, SportData).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class HBandMessageType(str, Enum):
    """Tipo de envelope enviado pelo app companion."""

    REALTIME_INGEST = "realtime_ingest"
    ORIGIN_BATCH = "origin_batch"
    SLEEP_BATCH = "sleep_batch"
    SPORT_SNAPSHOT = "sport_snapshot"
    PPG_STREAM = "ppg_stream"
    PPG_RAW_HISTORY = "ppg_raw_history"
    DEVICE_CAPABILITIES = "device_capabilities"


class HBandDeviceInfo(BaseModel):
    """Identidade do wearable HBand/Veepoo."""

    device_id: str = Field(
        ...,
        min_length=3,
        max_length=128,
        description="MAC, serial ou ID estável do pareamento",
        examples=["HBAND-AA:BB:CC:DD:EE:FF"],
    )
    vendor: str = Field(default="hband", max_length=32)
    model: Optional[str] = Field(None, max_length=64, description="SKU / model name")
    firmware_version: Optional[str] = Field(None, max_length=64)
    mac_address: Optional[str] = Field(None, max_length=32)
    origin_protocol_version: Optional[int] = Field(
        None, ge=0, le=10, description="0/1/2 legacy; 3/5 enhanced OriginData3"
    )
    watchday: Optional[int] = Field(
        None, ge=1, le=14, description="Capacidade de histórico no device (dias)"
    )


class HBandRealtimeIngest(BaseModel):
    """
    Payload alinhado a POST /api/v1/wearables/ingest.
    Gerado a partir de startDetectHeart / SpO2 / temp / BP / PPG stream.
    """

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device: HBandDeviceInfo
    timestamp: Optional[str] = Field(
        None, description="ISO-8601 UTC; se omitido, servidor usa now()"
    )
    heart_rate: Optional[float] = Field(None, ge=20.0, le=250.0)
    spo2: Optional[float] = Field(None, ge=50.0, le=100.0)
    skin_temp: Optional[float] = Field(None, ge=25.0, le=45.0)
    hrv_rmssd: Optional[float] = Field(None, ge=0.0, le=300.0)
    activity_level: Optional[float] = Field(None, ge=0.0, le=100.0)
    blood_pressure_sys: Optional[float] = Field(None, ge=60.0, le=300.0)
    blood_pressure_dia: Optional[float] = Field(None, ge=20.0, le=200.0)
    respiratory_rate: Optional[float] = Field(None, ge=0.0, le=80.0)
    ppg_signal: Optional[List[float]] = Field(
        None, description="Amostras PPG (ex.: luz verde ~25 Hz)"
    )
    filter_type: Optional[str] = Field("BMO", max_length=32)
    battery_level: Optional[float] = Field(None, ge=0.0, le=100.0)
    signal_confidence: Optional[float] = Field(0.9, ge=0.0, le=1.0)
    sdk_source: Optional[str] = Field(
        None,
        description="Método SDK de origem, ex.: startDetectHeart",
        max_length=64,
    )
    raw: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Payload bruto do listener Veepoo"
    )

    @field_validator("filter_type")
    @classmethod
    def validate_filter(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {"BMO", "Wavelet", "Butterworth", "Raw", "Adaptive"}:
            raise ValueError("filter_type inválido")
        return v


class HBandOriginSample(BaseModel):
    """Um pacote OriginData / OriginData3 (~5 min)."""

    timestamp: str = Field(..., description="ISO-8601 ou yyyy-MM-dd HH:mm:ss do device")
    package_number: Optional[int] = Field(None, ge=1, le=288)
    rate_value: Optional[float] = Field(None, ge=0, le=250, description="HR bpm")
    spo2_value: Optional[float] = Field(None, ge=0, le=100)
    hrv: Optional[float] = Field(None, ge=0, le=300)
    step_value: Optional[float] = Field(None, ge=0)
    sport_value: Optional[float] = Field(None, ge=0, description="Intensidade 0–65535")
    high_value: Optional[float] = Field(None, ge=0, le=300, description="PA sistólica")
    low_value: Optional[float] = Field(None, ge=0, le=200, description="PA diastólica")
    respiration_rate: Optional[float] = Field(None, ge=0, le=80)
    base_temperature: Optional[float] = Field(None, ge=20, le=45)
    temperature: Optional[float] = Field(None, ge=20, le=45)
    ppg_data: Optional[List[float]] = None
    ecg_data: Optional[List[float]] = None
    raw: Optional[Dict[str, Any]] = Field(default_factory=dict)


class HBandOriginBatch(BaseModel):
    """Batch de OriginData3 (sync histórico)."""

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device: HBandDeviceInfo
    day_offset: Optional[int] = Field(0, ge=0, le=14, description="0=hoje, 1=ontem…")
    samples: List[HBandOriginSample] = Field(..., min_length=1, max_length=500)


class HBandSleepRecord(BaseModel):
    """SleepData do SDK."""

    date: str = Field(..., description="yyyy-MM-dd")
    sleep_quality: Optional[int] = None
    wake_count: Optional[int] = None
    deep_sleep_time_min: Optional[int] = Field(None, ge=0)
    light_sleep_time_min: Optional[int] = Field(None, ge=0)
    all_sleep_time_min: Optional[int] = Field(None, ge=0)
    sleep_line: Optional[str] = Field(
        None, description="Curva 0/1/2 (5min) ou 0–4 (precisão 1min)"
    )
    sleep_down: Optional[str] = None
    sleep_up: Optional[str] = None
    precision_sleep: bool = False
    raw: Optional[Dict[str, Any]] = Field(default_factory=dict)


class HBandSleepBatch(BaseModel):
    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device: HBandDeviceInfo
    records: List[HBandSleepRecord] = Field(..., min_length=1, max_length=30)


class HBandSportSnapshot(BaseModel):
    """SportData do dia corrente."""

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device: HBandDeviceInfo
    timestamp: Optional[str] = None
    step: Optional[int] = Field(None, ge=0)
    distance_km: Optional[float] = Field(None, ge=0)
    kcal: Optional[float] = Field(None, ge=0)
    calc_type: Optional[int] = None
    raw: Optional[Dict[str, Any]] = Field(default_factory=dict)


class HBandPPGStreamChunk(BaseModel):
    """Chunk de PPG em tempo real (luz verde + accel)."""

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device: HBandDeviceInfo
    timestamp: Optional[str] = None
    green_light: List[float] = Field(..., min_length=1, max_length=10000)
    sample_rate_hz: float = Field(25.0, ge=1.0, le=256.0)
    acceleration: Optional[List[Dict[str, float]]] = Field(
        None, description="Lista de {x,y,z} sincronizada"
    )
    mode: Optional[str] = Field(None, description="MODE1 | MODE2 | realtime")


class HBandEnvelope(BaseModel):
    """Envelope polimórfico enviado pelo companion."""

    message_type: HBandMessageType
    schema_version: str = Field(default="1.0.0", max_length=16)
    payload: Dict[str, Any] = Field(..., description="Corpo tipado conforme message_type")


class HBandCapabilities(BaseModel):
    """FunctionDeviceSupportData simplificado (pós confirmDevicePwd)."""

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device: HBandDeviceInfo
    heart_detect: bool = True
    bp: bool = False
    spo2: bool = False
    temperature: bool = False
    precision_sleep: bool = False
    origin_protocol_version: Optional[int] = None
    watchday: Optional[int] = None
    raw: Optional[Dict[str, Any]] = Field(default_factory=dict)
