import json
import logging
import os
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

from src.datalake.schemas.base import DataLayer, MetricType
from src.datalake.storage.interface import LakehouseStore
from src.data_warehouse.bigquery_setup import provision_bigquery_datalake
from src.fhir.export import FhirExporter

load_dotenv()
logger = logging.getLogger(__name__)


class BigQueryBridge:
    """
    Ponte Datalake local -> BigQuery com suporte FHIR R4 / HL7.

    Sincroniza:
      - fhir_resources: recursos FHIR completos (canonico)
      - wearable_biometrics: compatibilidade retroativa
    """

    def __init__(self, store: LakehouseStore, project_id: Optional[str] = None):
        self.store = store
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID", "project-placeholder")
        self.dataset = os.getenv("BQ_DATASET", "healthtech_datalake")
        self.location = os.getenv("BQ_LOCATION", "US")
        self._client = None
        self.fhir_exporter = FhirExporter(store)

    @property
    def is_configured(self) -> bool:
        return self.project_id not in ("", "project-placeholder")

    def _get_client(self):
        if self._client is None:
            from google.cloud import bigquery
            self._client = bigquery.Client(project=self.project_id, location=self.location)
        return self._client

    def provision(self) -> Dict:
        if not self.is_configured:
            return {"status": "SIMULATION", "mensagem": "GCP nao configurado — schema simulado localmente"}
        try:
            provision_bigquery_datalake(self.project_id, self.location)
            return {"status": "PROVISIONED", "dataset": f"{self.project_id}.{self.dataset}"}
        except Exception as e:
            logger.warning("Provisionamento BigQuery falhou: %s", e)
            return {"status": "FAILED", "error": str(e)}

    def sync_fhir_resources(
        self,
        profiles: list,
        partition_dates: Optional[List[str]] = None,
    ) -> Dict:
        """Sincroniza recursos FHIR (Patient, Device, Observation) para BigQuery."""
        patient_device_df = self.fhir_exporter.to_bigquery_rows(profiles)
        obs_df = self.fhir_exporter.observations_to_bigquery_rows(partition_dates)

        frames = [df for df in [patient_device_df, obs_df] if not df.empty]
        if not frames:
            return {"status": "NO_DATA", "rows": 0}

        fhir_df = pd.concat(frames, ignore_index=True)
        return self._load_dataframe(fhir_df, "fhir_resources")

    def sync_silver_biometrics(self, partition_dates: Optional[List[str]] = None) -> Dict:
        """Sincroniza biometria Silver com codigos LOINC (compatibilidade)."""
        silver_df = self.store.read_layer(
            layer=DataLayer.SILVER,
            partition_dates=partition_dates,
        )
        if silver_df.empty:
            return {"status": "NO_DATA", "rows": 0}

        hr_df = silver_df[silver_df["metric_type"] == MetricType.HEART_RATE.value].copy()
        if hr_df.empty:
            return {"status": "NO_DATA", "rows": 0}

        bq_df = pd.DataFrame({
            "patient_id": hr_df["patient_id"],
            "timestamp": pd.to_datetime(hr_df["window_start"], utc=True),
            "heart_rate_bpm": hr_df["metric_value"].round().astype(int),
            "loinc_code": "8867-4",
            "sensors_used": hr_df["devices_involved"].apply(
                lambda x: x if isinstance(x, list) else []
            ),
            "is_anomaly": hr_df.get("is_anomaly", False),
            "fhir_observation_id": hr_df["record_id"].apply(
                lambda rid: f"obs-{str(rid)[:12]}"
            ),
        })

        return self._load_dataframe(bq_df, "wearable_biometrics")

    def sync_gold_daily_summary(self, partition_dates: Optional[List[str]] = None) -> Dict:
        gold_df = self.store.read_layer(
            layer=DataLayer.GOLD,
            table="daily_summary",
            partition_dates=partition_dates,
        )
        if gold_df.empty:
            return {"status": "NO_DATA", "rows": 0}

        return self._load_dataframe(gold_df, "gold_daily_summary")

    def sync_all(
        self,
        partition_dates: Optional[List[str]] = None,
        patient_profiles: Optional[list] = None,
    ) -> Dict:
        provision = self.provision()
        fhir = {"status": "SKIPPED", "rows": 0}
        if patient_profiles:
            fhir = self.sync_fhir_resources(patient_profiles, partition_dates)
        silver = self.sync_silver_biometrics(partition_dates)
        gold = self.sync_gold_daily_summary(partition_dates)
        return {
            "provision": provision,
            "fhir_resources": fhir,
            "silver_biometrics": silver,
            "gold_daily": gold,
        }

    def _load_dataframe(self, df: pd.DataFrame, table_name: str) -> Dict:
        rows = len(df)
        if not self.is_configured:
            sim_path = os.path.join("data", "bigquery_simulation", f"{table_name}.parquet")
            os.makedirs(os.path.dirname(sim_path), exist_ok=True)
            export_df = df.copy()
            if "resource_json" in export_df.columns:
                export_df["resource_json"] = export_df["resource_json"].apply(
                    lambda x: json.loads(x) if isinstance(x, str) else x
                )
            export_df.to_parquet(sim_path, index=False)
            logger.info("BigQuery simulado: %d rows -> %s", rows, sim_path)
            return {"status": "SIMULATED", "rows": rows, "path": sim_path}

        try:
            client = self._get_client()
            table_id = f"{self.project_id}.{self.dataset}.{table_name}"
            job = client.load_table_from_dataframe(df, table_id)
            job.result()
            logger.info("BigQuery sync: %d rows -> %s", rows, table_id)
            return {"status": "SYNCED", "rows": rows, "table": table_id}
        except Exception as e:
            logger.warning("Sync BigQuery falhou para %s: %s", table_name, e)
            sim_path = os.path.join("data", "bigquery_simulation", f"{table_name}.parquet")
            os.makedirs(os.path.dirname(sim_path), exist_ok=True)
            df.to_parquet(sim_path, index=False)
            return {"status": "FALLBACK_LOCAL", "rows": rows, "path": sim_path, "error": str(e)}