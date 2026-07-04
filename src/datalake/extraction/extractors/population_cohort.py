import pandas as pd

from src.datalake.extraction.extractors.base import BaseExtractor
from src.datalake.extraction.filters import QueryFilters
from src.datalake.schemas.base import DataLayer


class PopulationCohortExtractor(BaseExtractor):
    """
    Extração em nível populacional — resumos diários e alertas agregados.
    Suporta análise de coortes para inferência batch (Vertex AI).
    """

    def extract(self, filters: QueryFilters) -> pd.DataFrame:
        daily_df = self.store.read_layer(
            layer=DataLayer.GOLD,
            table="daily_summary",
            patient_id=filters.patient_id,
            patient_ids=filters.patient_ids,
            partition_dates=filters.partition_dates,
        )

        if daily_df.empty:
            return daily_df

        if filters.clinical_risk_levels:
            daily_df = daily_df[
                daily_df["clinical_risk_level"].isin(filters.clinical_risk_levels)
            ]

        if filters.min_risk_score > 0:
            hourly_df = self.store.read_layer(
                layer=DataLayer.GOLD,
                table="hourly_vitals",
                patient_ids=filters.patient_ids,
                partition_dates=filters.partition_dates,
            )
            if not hourly_df.empty:
                high_risk_patients = hourly_df.groupby("patient_id")["risk_score"].max()
                high_risk_patients = high_risk_patients[high_risk_patients >= filters.min_risk_score].index
                daily_df = daily_df[daily_df["patient_id"].isin(high_risk_patients)]

        alerts_df = self.store.read_layer(
            layer=DataLayer.GOLD,
            table="patient_alerts",
            patient_ids=filters.patient_ids,
        )

        if not alerts_df.empty:
            alert_counts = alerts_df.groupby("patient_id").size().reset_index(name="total_alerts")
            daily_df = daily_df.merge(alert_counts, on="patient_id", how="left")
            daily_df["total_alerts"] = daily_df["total_alerts"].fillna(0).astype(int)
        else:
            daily_df["total_alerts"] = 0

        return daily_df.sort_values(
            ["clinical_risk_level", "anomaly_episodes"],
            ascending=[True, False],
        ).reset_index(drop=True)