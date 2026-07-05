#!/usr/bin/env python3
"""Ingestão real de wearables — Apple Health, Google Fit, BLE → Bronze."""

import argparse
import json
import logging

from src.ingestion.real.orchestrator import RealIngestionOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Ingestão real de telemetria wearable")
    parser.add_argument("--patient-id", default=None, help="ID do paciente")
    parser.add_argument("--sources", nargs="+", default=None,
                        choices=["apple_health", "google_fit", "ble"])
    parser.add_argument("--bronze-only", action="store_true",
                        help="Apenas Bronze, sem Silver/Gold")
    args = parser.parse_args()

    orchestrator = RealIngestionOrchestrator(sources=args.sources)
    print("Fontes:", json.dumps(orchestrator.describe_sources(), indent=2))

    result = orchestrator.run_full_pipeline(
        patient_id=args.patient_id,
        run_silver_gold=not args.bronze_only,
    )

    print(json.dumps({k: v for k, v in result.items() if k != "records"}, indent=2, default=str))


if __name__ == "__main__":
    main()