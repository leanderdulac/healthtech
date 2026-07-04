import pandas as pd

from src.datalake.extraction.extractors.base import BaseExtractor
from src.datalake.extraction.filters import QueryFilters
from src.datalake.schemas.base import DataLayer


class AnomalyWindowExtractor(BaseExtractor):
    """
    Extrai janelas críticas onde anomalias foram detectadas.
    Agrupa episódios consecutivos para análise clínica.
    """

    def extract(self, filters: QueryFilters) -> pd.DataFrame:
        silver_filters = QueryFilters(
            patient_id=filters.patient_id,
            patient_ids=filters.patient_ids,
            start_time=filters.start_time,
            end_time=filters.end_time,
            layer=DataLayer.SILVER,
            anomalies_only=True,
            partition_dates=filters.partition_dates,
        )
        df = self.store.read_layer(**silver_filters.to_store_kwargs())

        if df.empty:
            return df

        df = df[df.get("is_anomaly", False) == True]  # noqa: E712
        df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
        df["window_end"] = pd.to_datetime(df["window_end"], utc=True)

        episodes = []
        for patient_id, group in df.groupby("patient_id"):
            group = group.sort_values("window_start")
            episode_start = None
            episode_end = None
            episode_metrics = []
            episode_devices = set()
            max_score = 0.0

            for _, row in group.iterrows():
                ws = row["window_start"]
                we = row["window_end"]

                if episode_start is None:
                    episode_start = ws
                    episode_end = we
                    episode_metrics = [row["metric_type"]]
                    episode_devices = set(row.get("devices_involved", []))
                    max_score = float(row.get("anomaly_score", 0))
                    continue

                gap = (ws - episode_end).total_seconds()
                if gap <= 30:
                    episode_end = we
                    episode_metrics.append(row["metric_type"])
                    episode_devices.update(row.get("devices_involved", []))
                    max_score = max(max_score, float(row.get("anomaly_score", 0)))
                else:
                    episodes.append(self._build_episode(
                        patient_id, episode_start, episode_end,
                        episode_metrics, episode_devices, max_score,
                    ))
                    episode_start = ws
                    episode_end = we
                    episode_metrics = [row["metric_type"]]
                    episode_devices = set(row.get("devices_involved", []))
                    max_score = float(row.get("anomaly_score", 0))

            if episode_start is not None:
                episodes.append(self._build_episode(
                    patient_id, episode_start, episode_end,
                    episode_metrics, episode_devices, max_score,
                ))

        return pd.DataFrame(episodes)

    @staticmethod
    def _build_episode(patient_id, start, end, metrics, devices, max_score) -> dict:
        duration_min = (end - start).total_seconds() / 60
        return {
            "patient_id": patient_id,
            "episode_start": start.isoformat(),
            "episode_end": end.isoformat(),
            "duration_minutes": round(duration_min, 2),
            "metrics_involved": list(set(metrics)),
            "devices_involved": list(devices),
            "max_anomaly_score": round(max_score, 3),
            "reading_count": len(metrics),
        }