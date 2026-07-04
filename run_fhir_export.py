#!/usr/bin/env python3
"""
Exportacao FHIR R4 / HL7 — gera Bundle e NDJSON a partir do lakehouse.

Recursos: Patient, Device, Observation, Flag
Terminologias: LOINC, UCUM, SNOMED CT, HL7 CodeSystems
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.datalake.utils.telemetry_simulator import SimulationConfig
from src.fhir.export import FhirExporter
from src.utils.data_generator import generate_patient_fhir_anonymized, generate_patient_fhir_mock

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    print_section("HEALTHTECH — Exportacao FHIR R4 / HL7")

    print_section("DEMO — Anonimizacao FHIR (HL7 De-Identification)")
    mock = generate_patient_fhir_mock()
    anon = generate_patient_fhir_anonymized()
    print(f"  Patient original  : id={mock.get('id')}, name={'sim' if mock.get('name') else 'nao'}")
    print(f"  Patient anonimizado: id={anon.get('id')[:16]}...")
    print(f"  Perfil de-id      : {anon.get('meta', {}).get('profile', [])[-1]}")

    config = LakehouseConfig(base_path=Path("data/lakehouse"))
    orchestrator = DatalakeOrchestrator(config)

    sim_config = SimulationConfig(num_patients=3, hours=6.0, seed=42)
    start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    print_section("PIPELINE + EXPORTACAO FHIR")
    result = orchestrator.run_full_pipeline(
        simulation_config=sim_config,
        start_time=start_time,
    )

    fhir = result.fhir_export or {}
    validation = fhir.get("validation", {})

    print(f"\n  Pacientes           : {len(result.patients)}")
    print(f"  Bundle FHIR         : {fhir.get('bundle_path', 'N/A')}")
    print(f"  NDJSON resources    : {fhir.get('ndjson_path', 'N/A')}")
    print(f"  Bundle valido       : {validation.get('all_valid', 'N/A')}")
    print(f"  Recursos no bundle  : {validation.get('resource_counts', {})}")

    exporter = orchestrator.fhir_exporter

    obs_export = exporter.export_observations_ndjson(
        partition_dates=result.partition_dates,
    )
    print(f"\n  Observations NDJSON : {obs_export.get('count', 0)} recursos")
    print(f"  Path                : {obs_export.get('path', 'N/A')}")

    pd_export = exporter.export_patients_and_devices(result.patient_profiles)
    print(f"\n  Patients exportados : {pd_export['patients']['count']}")
    print(f"  Devices exportados  : {pd_export['devices']['count']}")

    print_section("EXPORTACAO CONCLUIDA")
    print(f"  Artefatos em        : data/fhir_exports/")
    print(f"  Padrao              : HL7 FHIR R4")
    print(f"  Codigos LOINC       : 8867-4 (HR), 2708-6 (SpO2), 55423-8 (Steps)")


if __name__ == "__main__":
    main()