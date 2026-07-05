#!/usr/bin/env python3
"""Pipeline de produção F17 — ingestão real, FHIR, conformal, validação, Vertex."""

import argparse
import json
import logging

from src.integrations.production.orchestrator import ProductionOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Pipeline de produção Healthtech F17")
    parser.add_argument("--patient-id", default=None)
    parser.add_argument("--sources", nargs="+", default=None)
    parser.add_argument("--skip-ingestion", action="store_true")
    parser.add_argument("--skip-clinical", action="store_true")
    parser.add_argument("--skip-conformal", action="store_true")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--deploy-vertex", action="store_true")
    parser.add_argument("--no-sim-fallback", action="store_true")
    args = parser.parse_args()

    orchestrator = ProductionOrchestrator(ingestion_sources=args.sources)
    result = orchestrator.run_production_pipeline(
        patient_id=args.patient_id,
        run_ingestion=not args.skip_ingestion,
        run_clinical_sync=not args.skip_clinical,
        run_conformal=not args.skip_conformal,
        run_validation=not args.skip_validation,
        run_vertex_deploy=args.deploy_vertex,
        use_simulated_datalake_if_empty=not args.no_sim_fallback,
    )
    print(json.dumps(result.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()