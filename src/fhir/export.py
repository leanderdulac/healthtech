"""
Exportação de recursos FHIR para arquivos e integração com pipelines.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from src.datalake.schemas.base import DataLayer
from src.datalake.storage.interface import LakehouseStore
from src.datalake.utils.telemetry_simulator import PatientProfile
from src.fhir.mappers import (
    dataframe_to_observations,
    device_binding_to_fhir,
    lakehouse_to_fhir_bundle,
    patient_profile_to_fhir,
)
from src.fhir.validator import validate_bundle

logger = logging.getLogger(__name__)

DEFAULT_FHIR_EXPORT_DIR = Path("data/fhir_exports")


class FhirExporter:
    """Exporta dados do lakehouse como recursos FHIR R4 / HL7."""

    def __init__(
        self,
        store: LakehouseStore,
        export_dir: Optional[Path] = None,
    ):
        self.store = store
        self.export_dir = export_dir or DEFAULT_FHIR_EXPORT_DIR
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_patient_bundle(
        self,
        profiles: List[PatientProfile],
        partition_dates: Optional[List[str]] = None,
        include_bronze: bool = False,
        max_observations: int = 1000,
    ) -> Dict:
        """Gera Bundle FHIR com pacientes, dispositivos, observações e alertas."""
        silver_df = self.store.read_layer(
            layer=DataLayer.SILVER,
            partition_dates=partition_dates,
        )
        bronze_df = None
        if include_bronze:
            bronze_df = self.store.read_layer(
                layer=DataLayer.BRONZE,
                partition_dates=partition_dates,
            )
            if len(bronze_df) > max_observations:
                bronze_df = bronze_df.head(max_observations)

        alerts_df = self.store.read_layer(
            layer=DataLayer.GOLD,
            table="patient_alerts",
            partition_dates=None,
        )

        bundle = lakehouse_to_fhir_bundle(
            patients=profiles,
            bronze_df=bronze_df,
            silver_df=silver_df,
            alerts_df=alerts_df,
            bundle_id=f"healthtech-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        )

        validation = validate_bundle(bundle)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        bundle_path = self.export_dir / f"bundle_{timestamp}.json"
        ndjson_path = self.export_dir / f"resources_{timestamp}.ndjson"

        with open(bundle_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False, default=str)

        self._write_ndjson(bundle, ndjson_path)

        return {
            "status": "EXPORTED",
            "bundle_path": str(bundle_path),
            "ndjson_path": str(ndjson_path),
            "validation": validation,
            "resource_counts": validation.get("resource_counts", {}),
        }

    def export_observations_ndjson(
        self,
        partition_dates: Optional[List[str]] = None,
        layer: DataLayer = DataLayer.SILVER,
    ) -> Dict:
        """Exporta Observations como NDJSON (padrão bulk FHIR)."""
        df = self.store.read_layer(layer=layer, partition_dates=partition_dates)
        observations = dataframe_to_observations(df)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = self.export_dir / f"Observation_{layer.value}_{timestamp}.ndjson"

        with open(path, "w", encoding="utf-8") as f:
            for obs in observations:
                f.write(json.dumps(obs, ensure_ascii=False, default=str) + "\n")

        return {
            "status": "EXPORTED",
            "resource_type": "Observation",
            "layer": layer.value,
            "count": len(observations),
            "path": str(path),
        }

    def export_patients_and_devices(
        self,
        profiles: List[PatientProfile],
    ) -> Dict:
        """Exporta Patient e Device resources separadamente."""
        patients = [patient_profile_to_fhir(p) for p in profiles]
        devices = []
        for p in profiles:
            for d in p.devices:
                devices.append(device_binding_to_fhir(d))

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        patients_path = self.export_dir / f"Patient_{timestamp}.ndjson"
        devices_path = self.export_dir / f"Device_{timestamp}.ndjson"

        self._write_resource_list(patients, patients_path)
        self._write_resource_list(devices, devices_path)

        return {
            "status": "EXPORTED",
            "patients": {"count": len(patients), "path": str(patients_path)},
            "devices": {"count": len(devices), "path": str(devices_path)},
        }

    def to_bigquery_rows(self, profiles: List[PatientProfile]) -> pd.DataFrame:
        """Prepara DataFrame para carga FHIR no BigQuery."""
        rows = []
        for profile in profiles:
            patient = patient_profile_to_fhir(profile)
            rows.append({
                "resource_type": "Patient",
                "resource_id": profile.patient_id,
                "fhir_version": "R4",
                "last_updated": datetime.utcnow().isoformat(),
                "resource_json": json.dumps(patient, ensure_ascii=False),
            })
            for device in profile.devices:
                dev = device_binding_to_fhir(device)
                rows.append({
                    "resource_type": "Device",
                    "resource_id": device.device_id,
                    "fhir_version": "R4",
                    "last_updated": datetime.utcnow().isoformat(),
                    "resource_json": json.dumps(dev, ensure_ascii=False),
                })
        return pd.DataFrame(rows)

    def observations_to_bigquery_rows(
        self,
        partition_dates: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Prepara Observations para tabela FHIR do BigQuery."""
        df = self.store.read_layer(
            layer=DataLayer.SILVER,
            partition_dates=partition_dates,
        )
        observations = dataframe_to_observations(df)
        rows = []
        for obs in observations:
            rows.append({
                "resource_type": "Observation",
                "resource_id": obs.get("id"),
                "patient_id": obs.get("subject", {}).get("reference", "").replace("Patient/", ""),
                "effective_datetime": obs.get("effectiveDateTime"),
                "fhir_version": "R4",
                "last_updated": datetime.utcnow().isoformat(),
                "resource_json": json.dumps(obs, ensure_ascii=False),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _write_ndjson(bundle: dict, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for entry in bundle.get("entry", []):
                resource = entry.get("resource")
                if resource:
                    f.write(json.dumps(resource, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _write_resource_list(resources: list, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for resource in resources:
                f.write(json.dumps(resource, ensure_ascii=False, default=str) + "\n")