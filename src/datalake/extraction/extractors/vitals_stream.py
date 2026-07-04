import pandas as pd

from src.datalake.extraction.extractors.base import BaseExtractor
from src.datalake.extraction.filters import QueryFilters
from src.datalake.schemas.base import DataLayer, MetricType


class VitalsStreamExtractor(BaseExtractor):
    """
    Extrai streams de sinais vitais (HR, SpO2, HRV) com pivô temporal.
    Ideal para alimentar modelos de inferência online.
    """

    DEFAULT_METRICS = [
        MetricType.HEART_RATE,
        MetricType.SPO2,
        MetricType.HRV,
    ]

    def extract(self, filters: QueryFilters) -> pd.DataFrame:
        metrics = filters.metrics or self.DEFAULT_METRICS
        silver_filters = QueryFilters(
            patient_id=filters.patient_id,
            patient_ids=filters.patient_ids,
            start_time=filters.start_time,
            end_time=filters.end_time,
            layer=DataLayer.SILVER,
            partition_dates=filters.partition_dates,
        )
        df = self.store.read_layer(**silver_filters.to_store_kwargs())

        if df.empty:
            return df

        metric_values = [m.value for m in metrics]
        df = df[df["metric_type"].isin(metric_values)]
        df["window_start"] = pd.to_datetime(df["window_start"], utc=True)

        pivoted = df.pivot_table(
            index=["patient_id", "window_start"],
            columns="metric_type",
            values="metric_value",
            aggfunc="mean",
        ).reset_index()

        if "quality_score" in df.columns:
            quality = df.groupby(["patient_id", "window_start"])["quality_score"].mean().reset_index()
            pivoted = pivoted.merge(quality, on=["patient_id", "window_start"], how="left")

        if "is_anomaly" in df.columns:
            anomalies = df.groupby(["patient_id", "window_start"])["is_anomaly"].any().reset_index()
            pivoted = pivoted.merge(anomalies, on=["patient_id", "window_start"], how="left")

        return pivoted.sort_values(["patient_id", "window_start"]).reset_index(drop=True)