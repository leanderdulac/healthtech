import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DataLayer
from src.datalake.extraction.query_engine import DatalakeQueryEngine
from src.datalake.ingestion.device_registry import DeviceRegistry
from src.datalake.ingestion.telemetry_ingestor import TelemetryIngestor
from src.datalake.pipeline.bronze_to_silver import BronzeToSilverTransformer
from src.datalake.pipeline.silver_to_gold import SilverToGoldTransformer
from src.datalake.quality.quality_gates import QualityGateRunner
from src.datalake.schemas.bronze import BronzeTelemetryRecord
from src.datalake.storage.local_parquet_store import LocalParquetStore
from src.datalake.utils.telemetry_simulator import SimulationConfig, TelemetrySimulator
logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    ingestion: Dict[str, int] = field(default_factory=dict)
    silver_rows: int = 0
    gold_hourly_rows: int = 0
    gold_daily_rows: int = 0
    gold_alerts_rows: int = 0
    quality_bronze_silver: Optional[dict] = None
    quality_silver_gold: Optional[dict] = None
    partition_dates: List[str] = field(default_factory=list)
    patients: List[str] = field(default_factory=list)
    fhir_export: Optional[dict] = None
    patient_profiles: list = field(default_factory=list)


class DatalakeOrchestrator:
    """
    Orquestrador do pipeline completo do lakehouse de telemetria 24h.

    Fluxo: Simulação → Bronze → Silver → Gold → Extração
    """

    def __init__(self, config: Optional[LakehouseConfig] = None):
        self.config = config or LakehouseConfig()
        self.store = LocalParquetStore(self.config)
        self.device_registry = DeviceRegistry(self.config)
        self.ingestor = TelemetryIngestor(self.store, self.config, self.device_registry)
        self.bronze_to_silver = BronzeToSilverTransformer(self.store, self.config)
        self.silver_to_gold = SilverToGoldTransformer(self.store, self.config)
        self.quality_gates = QualityGateRunner(self.config)
        self.query_engine = DatalakeQueryEngine(self.store, self.config)
        self._fhir_exporter = None

    def run_full_pipeline(
        self,
        simulation_config: Optional[SimulationConfig] = None,
        start_time: Optional[datetime] = None,
    ) -> PipelineResult:
        sim_config = simulation_config or SimulationConfig(num_patients=5, hours=24.0)
        simulator = TelemetrySimulator(sim_config)

        for profile in simulator.patient_profiles:
            self.device_registry.register_batch(profile.devices)

        logger.info("Gerando telemetria 24h para %d pacientes...", sim_config.num_patients)
        bronze_records = simulator.generate_24h_stream(start_time=start_time)

        result = self.run_from_bronze(bronze_records)
        result.patient_profiles = simulator.patient_profiles
        result.fhir_export = self.export_fhir(
            profiles=simulator.patient_profiles,
            partition_dates=result.partition_dates,
        )
        return result

    def run_from_bronze(self, records: List[BronzeTelemetryRecord]) -> PipelineResult:
        result = PipelineResult()

        result.ingestion = self.ingestor.ingest_stream(records)
        result.patients = sorted({r.patient_id for r in records})
        result.partition_dates = sorted({r.partition_date for r in records})

        bronze_df = self.store.read_layer(
            layer=DataLayer.BRONZE,
            partition_dates=result.partition_dates,
        )

        silver_df = self.bronze_to_silver.transform(partition_dates=result.partition_dates)
        result.silver_rows = len(silver_df)

        qs_report = self.quality_gates.gate_bronze_to_silver(bronze_df, silver_df)
        result.quality_bronze_silver = {
            "passed": qs_report.passed,
            "pass_rate": round(qs_report.pass_rate, 3),
            "checks": qs_report.checks,
            "messages": qs_report.messages,
        }

        hourly_df, daily_df, alerts_df = self.silver_to_gold.transform(
            partition_dates=result.partition_dates
        )
        result.gold_hourly_rows = len(hourly_df)
        result.gold_daily_rows = len(daily_df)
        result.gold_alerts_rows = len(alerts_df)

        qg_report = self.quality_gates.gate_silver_to_gold(silver_df, hourly_df, daily_df)
        result.quality_silver_gold = {
            "passed": qg_report.passed,
            "checks": qg_report.checks,
            "messages": qg_report.messages,
        }

        return result

    @property
    def fhir_exporter(self):
        if self._fhir_exporter is None:
            from src.fhir.export import FhirExporter
            self._fhir_exporter = FhirExporter(self.store)
        return self._fhir_exporter

    def export_fhir(self, profiles: list, partition_dates: Optional[List[str]] = None) -> dict:
        """Exporta dados do lakehouse como Bundle FHIR R4 / HL7."""
        return self.fhir_exporter.export_patient_bundle(
            profiles=profiles,
            partition_dates=partition_dates,
        )

    def demonstrate_extraction(self, patient_id: str, partition_date: str) -> Dict[str, pd.DataFrame]:
        return self.query_engine.extract_patient_24h(patient_id, partition_date)