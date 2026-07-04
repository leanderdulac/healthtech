from dataclasses import dataclass, field
from typing import List, Optional

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import MetricType, QualityFlag
from src.datalake.schemas.bronze import BronzeTelemetryRecord


@dataclass
class ValidationResult:
    is_valid: bool
    quality_score: float
    flags: List[QualityFlag] = field(default_factory=list)
    reason: Optional[str] = None


class TelemetryValidator:
    """Validação fisiológica e de integridade para telemetria de wearables."""

    def __init__(self, config: LakehouseConfig):
        self.config = config

    def validate_bronze(self, record: BronzeTelemetryRecord) -> ValidationResult:
        flags: List[QualityFlag] = []
        score = 1.0

        if record.signal_confidence < 0.5:
            flags.append(QualityFlag.LOW_CONFIDENCE)
            score -= 0.2

        if record.battery_level is not None and record.battery_level < 0.1:
            flags.append(QualityFlag.LOW_CONFIDENCE)
            score -= 0.1

        range_check = self._check_physiological_range(record.metric_type, record.metric_value)
        if not range_check:
            flags.append(QualityFlag.OUT_OF_RANGE)
            score -= 0.4

        if not record.timestamp_utc:
            flags.append(QualityFlag.MISSING_TIMESTAMP)
            score = 0.0

        score = max(0.0, min(1.0, score))
        return ValidationResult(
            is_valid=score >= self.config.min_quality_score and QualityFlag.OUT_OF_RANGE not in flags,
            quality_score=score,
            flags=flags,
        )

    def _check_physiological_range(self, metric: MetricType, value: float) -> bool:
        ranges = {
            MetricType.HEART_RATE: (self.config.hr_min_valid, self.config.hr_max_valid),
            MetricType.SPO2: (self.config.spo2_min_valid, self.config.spo2_max_valid),
            MetricType.HRV: (self.config.hrv_min_valid, self.config.hrv_max_valid),
            MetricType.STEPS: (0, 500),
            MetricType.STRESS_INDEX: (0, 100),
            MetricType.SKIN_TEMP: (30.0, 42.0),
            MetricType.RESPIRATORY_RATE: (8, 40),
        }
        if metric not in ranges:
            return True
        low, high = ranges[metric]
        return low <= value <= high