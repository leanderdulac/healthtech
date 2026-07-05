#!/usr/bin/env python3
"""Calibração conformal multi-horizonte para os TCNs."""

import argparse
import json
import logging

from src.clinical_intelligence.conformal.calibrator import ConformalCalibrator
from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.datalake.utils.telemetry_simulator import SimulationConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Conformal prediction — calibração TCN")
    parser.add_argument("--alpha", type=float, default=0.10, help="Nível de significância")
    parser.add_argument("--subsample", type=int, default=30)
    parser.add_argument("--skip-pipeline", action="store_true")
    args = parser.parse_args()

    config = LakehouseConfig()
    datalake = DatalakeOrchestrator(config)

    if not args.skip_pipeline:
        sim = SimulationConfig(num_patients=5, hours=80.0, seed=42)
        pipeline = datalake.run_full_pipeline(simulation_config=sim)
        profiles = pipeline.patient_profiles
        partitions = pipeline.partition_dates
    else:
        from src.datalake.schemas.base import DataLayer
        from src.ingestion.real.profile_factory import profiles_from_ids
        bronze_df = datalake.query_engine.store.read_layer(layer=DataLayer.BRONZE)
        profiles = profiles_from_ids(bronze_df["patient_id"].unique().tolist()) if not bronze_df.empty else []
        partitions = sorted(bronze_df["partition_date"].astype(str).unique().tolist()) if not bronze_df.empty else []

    calibrator = ConformalCalibrator("data/models", alpha=args.alpha)
    result = calibrator.calibrate_from_datalake(
        query_engine=datalake.query_engine,
        patient_profiles=profiles,
        partition_dates=partitions,
        subsample=args.subsample,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()