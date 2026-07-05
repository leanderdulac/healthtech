"""
Adaptador Google Fit — REST API com fallback local.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from src.datalake.schemas.base import DeviceType, MetricType, TelemetrySource
from src.ingestion.real.base import AdapterResult, TelemetryAdapter
from src.ingestion.real.normalizer import TelemetryNormalizer

logger = logging.getLogger(__name__)

GOOGLE_FIT_DATA_TYPES = {
    "com.google.heart_rate.bpm": MetricType.HEART_RATE,
    "com.google.oxygen_saturation": MetricType.SPO2,
    "com.google.step_count.delta": MetricType.STEPS,
    "com.google.heart_rate.variability": MetricType.HRV,
}


class GoogleFitAdapter(TelemetryAdapter):
    """Cliente Google Fit REST API + cache local JSON."""

    source_name = "google_fit"
    API_BASE = "https://www.googleapis.com/fitness/v1/users/me"

    def __init__(
        self,
        access_token: Optional[str] = None,
        cache_path: Optional[str] = None,
        patient_id: Optional[str] = None,
        device_id: str = "google-fit-primary",
    ):
        self.access_token = access_token or os.getenv("GOOGLE_FIT_ACCESS_TOKEN", "")
        self.cache_path = Path(
            cache_path or os.getenv("GOOGLE_FIT_CACHE_PATH", "data/ingestion/google_fit/cache.json")
        )
        self.patient_id = patient_id or os.getenv("GOOGLE_FIT_PATIENT_ID", "PAT-GFIT-001")
        self.device_id = device_id
        self.normalizer = TelemetryNormalizer(default_vendor="google")

    def is_available(self) -> bool:
        return bool(self.access_token) or self.cache_path.exists()

    def fetch_records(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> AdapterResult:
        pid = patient_id or self.patient_id
        errors: List[str] = []
        records = []

        if self.access_token:
            try:
                records.extend(self._fetch_api(pid, start_time, end_time))
            except Exception as e:
                errors.append(f"API Google Fit: {e}")
                logger.warning("Google Fit API falhou, tentando cache: %s", e)

        if not records and self.cache_path.exists():
            records = self._load_cache(pid, start_time, end_time)

        if not records and not errors:
            errors.append("Nenhuma fonte Google Fit disponível (token ou cache)")

        return AdapterResult(
            source=self.source_name,
            records=records,
            errors=errors,
            metadata={"api_used": bool(self.access_token), "cache": str(self.cache_path)},
        )

    def _fetch_api(
        self,
        patient_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> List:
        start_ns = int((start_time or datetime(2020, 1, 1, tzinfo=timezone.utc)).timestamp() * 1e9)
        end_ns = int((end_time or datetime.now(timezone.utc)).timestamp() * 1e9)
        headers = {"Authorization": f"Bearer {self.access_token}"}

        records = []
        for data_type, metric in GOOGLE_FIT_DATA_TYPES.items():
            url = f"{self.API_BASE}/dataSources"
            params = {
                "dataTypeName": data_type,
                "startTimeNanos": start_ns,
                "endTimeNanos": end_ns,
            }
            resp = requests.get(
                f"{self.API_BASE}/dataset:aggregate",
                headers=headers,
                params={
                    "aggregateBy": json.dumps([{"dataTypeName": data_type}]),
                    "startTimeMillis": start_ns // 1_000_000,
                    "endTimeMillis": end_ns // 1_000_000,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                logger.debug("Google Fit %s: HTTP %d", data_type, resp.status_code)
                continue

            body = resp.json()
            for bucket in body.get("bucket", []):
                for dataset in bucket.get("dataset", []):
                    for point in dataset.get("point", []):
                        ts = datetime.fromtimestamp(
                            point["startTimeNanos"] / 1e9, tz=timezone.utc,
                        )
                        value = point["value"][0].get("fpVal") or point["value"][0].get("intVal", 0)
                        records.append(self.normalizer.from_raw_reading(
                            patient_id=patient_id,
                            device_id=self.device_id,
                            metric_type=metric,
                            value=float(value),
                            timestamp=ts,
                            vendor="google",
                            device_type=DeviceType.FITNESS_BAND,
                            source=TelemetrySource.BATCH_SYNC,
                            raw_payload={"dataType": data_type, "point": point},
                        ))

        self._save_cache(records)
        return records

    def _load_cache(
        self,
        patient_id: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> List:
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        readings = data.get("readings", data if isinstance(data, list) else [])
        return self.normalizer.batch_from_dicts(
            readings=[r for r in readings if self._filter_row(r, start_time, end_time)],
            patient_id=patient_id,
            device_id=self.device_id,
            vendor="google",
            source=TelemetrySource.BATCH_SYNC,
        )

    def _save_cache(self, records: List) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        readings = [
            {
                "metric_type": r.metric_type.value,
                "value": r.metric_value,
                "timestamp": r.timestamp_utc.isoformat(),
                "raw_payload": r.raw_payload,
            }
            for r in records
        ]
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump({"readings": readings, "saved_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)

    @staticmethod
    def _filter_row(row: Dict, start: Optional[datetime], end: Optional[datetime]) -> bool:
        ts = row.get("timestamp", "")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if start and ts < start:
            return False
        if end and ts > end:
            return False
        return True