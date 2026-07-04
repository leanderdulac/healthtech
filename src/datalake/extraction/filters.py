from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.datalake.schemas.base import DataLayer, MetricType


@dataclass
class QueryFilters:
    """Filtros composáveis para extração do lakehouse."""

    patient_id: Optional[str] = None
    patient_ids: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    metrics: Optional[List[MetricType]] = None
    layer: DataLayer = DataLayer.SILVER
    min_quality_score: float = 0.0
    anomalies_only: bool = False
    min_risk_score: float = 0.0
    clinical_risk_levels: Optional[List[str]] = None
    partition_dates: Optional[List[str]] = None

    def to_store_kwargs(self) -> dict:
        return {
            "layer": self.layer,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "patient_id": self.patient_id,
            "patient_ids": self.patient_ids,
            "partition_dates": self.partition_dates,
        }