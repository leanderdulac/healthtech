from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class DataLayer(str, Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class DeviceType(str, Enum):
    SMARTWATCH = "smartwatch"
    FITNESS_BAND = "fitness_band"
    CHEST_STRAP = "chest_strap"
    RING = "ring"


class MetricType(str, Enum):
    HEART_RATE = "heart_rate"
    SPO2 = "spo2"
    HRV = "hrv"
    STEPS = "steps"
    SLEEP_STAGE = "sleep_stage"
    STRESS_INDEX = "stress_index"
    SKIN_TEMP = "skin_temp"
    RESPIRATORY_RATE = "respiratory_rate"


class TelemetrySource(str, Enum):
    DEVICE_STREAM = "device_stream"
    BATCH_SYNC = "batch_sync"
    MANUAL_UPLOAD = "manual_upload"


class QualityFlag(str, Enum):
    VALID = "valid"
    OUT_OF_RANGE = "out_of_range"
    DUPLICATE = "duplicate"
    SENSOR_DRIFT = "sensor_drift"
    MISSING_TIMESTAMP = "missing_timestamp"
    LOW_CONFIDENCE = "low_confidence"
    RECONCILED = "reconciled"


@dataclass
class DeviceBinding:
    """Associação paciente ↔ dispositivo para rastreabilidade longitudinal."""

    patient_id: str
    device_id: str
    device_type: DeviceType
    vendor: str
    firmware_version: str
    paired_at: datetime
    is_primary: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionRequest:
    """Contrato de requisição para a camada de extração."""

    patient_id: Optional[str] = None
    patient_ids: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    metrics: Optional[List[MetricType]] = None
    layer: DataLayer = DataLayer.SILVER
    min_quality_score: float = 0.0
    include_anomalies_only: bool = False