import pandas as pd

from src.datalake.extraction.extractors.base import BaseExtractor
from src.datalake.extraction.filters import QueryFilters
from src.datalake.schemas.base import DataLayer, MetricType


class PatientTimelineExtractor(BaseExtractor):
    """
    Extrai timeline completa 24h de um paciente.
    Consolida todos os sinais vitais em ordem cronológica.
    """

    def extract(self, filters: QueryFilters) -> pd.DataFrame:
        if not filters.patient_id:
            raise ValueError("patient_id é obrigatório para extração de timeline")

        silver_filters = QueryFilters(
            patient_id=filters.patient_id,
            start_time=filters.start_time,
            end_time=filters.end_time,
            layer=DataLayer.SILVER,
            partition_dates=filters.partition_dates,
        )
        df = self.store.read_layer(**silver_filters.to_store_kwargs())

        if df.empty:
            return df

        df["window_start"] = pd.to_datetime(df["window_start"], utc=True)

        if filters.metrics:
            metric_values = [m.value for m in filters.metrics]
            df = df[df["metric_type"].isin(metric_values)]

        if filters.min_quality_score > 0 and "quality_score" in df.columns:
            df = df[df["quality_score"] >= filters.min_quality_score]

        if filters.anomalies_only and "is_anomaly" in df.columns:
            df = df[df["is_anomaly"] == True]  # noqa: E712

        return df.sort_values("window_start").reset_index(drop=True)