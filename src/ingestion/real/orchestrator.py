"""
Orquestrador de ingestão real — multi-fonte → Bronze via TelemetryIngestor.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Type

from src.datalake.config import LakehouseConfig
from src.datalake.ingestion.telemetry_ingestor import TelemetryIngestor
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.datalake.schemas.bronze import BronzeTelemetryRecord
from src.ingestion.real.apple_health import AppleHealthAdapter
from src.ingestion.real.base import AdapterResult, TelemetryAdapter
from src.ingestion.real.ble_adapter import BLEHeartRateAdapter
from src.ingestion.real.google_fit import GoogleFitAdapter

logger = logging.getLogger(__name__)

ADAPTER_REGISTRY: Dict[str, Type[TelemetryAdapter]] = {
    "apple_health": AppleHealthAdapter,
    "google_fit": GoogleFitAdapter,
    "ble": BLEHeartRateAdapter,
}


class RealIngestionOrchestrator:
    """
    Coleta telemetria de fontes reais e persiste na camada Bronze.

    Fluxo:
      adaptadores (Apple Health / Google Fit / BLE)
        → normalização BronzeTelemetryRecord
        → TelemetryIngestor.ingest_stream()
        → (opcional) pipeline Silver/Gold
    """

    def __init__(
        self,
        lakehouse_config: Optional[LakehouseConfig] = None,
        adapters: Optional[List[TelemetryAdapter]] = None,
        sources: Optional[List[str]] = None,
    ):
        self.lakehouse_config = lakehouse_config or LakehouseConfig()
        self.datalake = DatalakeOrchestrator(self.lakehouse_config)
        self.ingestor: TelemetryIngestor = self.datalake.ingestor

        if adapters is not None:
            self.adapters = adapters
        elif sources:
            self.adapters = [ADAPTER_REGISTRY[s]() for s in sources if s in ADAPTER_REGISTRY]
        else:
            self.adapters = [cls() for cls in ADAPTER_REGISTRY.values()]

    def describe_sources(self) -> List[Dict]:
        return [a.describe() for a in self.adapters]

    def collect_all(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict:
        all_records: List[BronzeTelemetryRecord] = []
        source_results: Dict[str, Dict] = {}

        for adapter in self.adapters:
            if not adapter.is_available():
                source_results[adapter.source_name] = {
                    "status": "skipped",
                    "reason": "not_available",
                }
                continue

            result: AdapterResult = adapter.fetch_records(
                patient_id=patient_id,
                start_time=start_time,
                end_time=end_time,
            )
            all_records.extend(result.records)
            source_results[adapter.source_name] = {
                "status": "ok" if result.records else "empty",
                "count": result.count,
                "errors": result.errors,
                "metadata": result.metadata,
            }

        return {
            "sources": source_results,
            "collected": len(all_records),
            "records": all_records,
            "patient_id": patient_id,
        }

    def run_full_pipeline(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        run_silver_gold: bool = True,
    ) -> Dict:
        collection = self.collect_all(patient_id, start_time, end_time)
        all_records = collection.pop("records", [])

        pipeline_result = None
        ingestion_stats = {"total": 0, "valid": 0, "invalid": 0, "partitions": 0}

        if all_records and run_silver_gold:
            pipeline_result = self.datalake.run_from_bronze(all_records)
            ingestion_stats = pipeline_result.ingestion
        elif all_records:
            ingestion_stats = self.ingestor.ingest_stream(all_records)

        return {
            **collection,
            "ingestion": ingestion_stats,
            "pipeline": {
                "silver_rows": pipeline_result.silver_rows if pipeline_result else 0,
                "gold_hourly_rows": pipeline_result.gold_hourly_rows if pipeline_result else 0,
                "gold_daily_rows": pipeline_result.gold_daily_rows if pipeline_result else 0,
                "gold_alerts_rows": pipeline_result.gold_alerts_rows if pipeline_result else 0,
                "partition_dates": pipeline_result.partition_dates if pipeline_result else [],
                "patients": pipeline_result.patients if pipeline_result else [],
            } if pipeline_result else None,
        }