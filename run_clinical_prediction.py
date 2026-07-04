#!/usr/bin/env python3
"""
Motor preditivo clínico multimodal.

Pipeline: wearable → denoising → ghost signals → fuzzy → fusão → prognóstico
Antecipação de eventos clínicos com horas/dias de lead time.
"""

import logging
from datetime import datetime
from pathlib import Path

from src.clinical_intelligence.pipeline import ClinicalIntelligencePipeline
from src.clinical_intelligence.storage import ClinicalIntelligenceStorage
from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.datalake.utils.telemetry_simulator import SimulationConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    print_section("INTELIGÊNCIA CLÍNICA PREDITIVA — F15")

    lakehouse_config = LakehouseConfig(base_path=Path("data/lakehouse"))
    orchestrator = DatalakeOrchestrator(lakehouse_config)

    sim_config = SimulationConfig(
        num_patients=3,
        hours=12.0,
        hr_interval_seconds=10,
        anomaly_probability=0.05,
        seed=42,
    )
    start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    print_section("FASE 1: DATALAKE (geração de telemetria)")
    pipeline_result = orchestrator.run_full_pipeline(
        simulation_config=sim_config,
        start_time=start_time,
    )
    print(f"  Pacientes  : {len(pipeline_result.patients)}")
    print(f"  Silver rows: {pipeline_result.silver_rows}")

    print_section("FASE 2: ANÁLISE PREDITIVA MULTIMODAL")
    ci_pipeline = ClinicalIntelligencePipeline()
    storage = ClinicalIntelligenceStorage()

    hemo_scores = {
        "PAT-HEMO-STEN": 0.85,
        "PAT-HEMO-ANEU": 0.65,
    }

    results = ci_pipeline.analyze_from_profiles(
        query_engine=orchestrator.query_engine,
        patient_profiles=pipeline_result.patient_profiles,
        partition_dates=pipeline_result.partition_dates,
        hemodynamic_scores=hemo_scores,
    )

    for result in results:
        path = storage.save_result(result)
        print(f"\n  Paciente: {result.patient_id}")
        print(f"  Fusion score     : {result.fusion_score:.3f}")
        print(f"  Fuzzy            : {result.fuzzy.linguistic_summary}")
        print(f"  Ghost signals    : {len(result.ghost_signals)}")
        for g in result.ghost_signals:
            print(f"    • {g.name}: {g.value:.2f} (conf={g.confidence:.2f}) — {g.clinical_relevance}")

        print(f"  Ruído/artefatos  : noise={result.fuzzy.noise_gate:.2f}, fp_risk={result.fuzzy.false_positive_risk:.2f}")
        print(f"  Persistência     : {result.fuzzy.persistence_score:.2f}")

        if result.predictions:
            print(f"  Predições:")
            for p in result.predictions[:3]:
                print(f"    → [{p.probability:.0%}] {p.event_type}")
                print(f"      Lead time: {p.lead_time_hours:.0f}h ({p.lead_time_days:.1f} dias)")
                print(f"      {p.recommendation}")
        else:
            print(f"  Predições: nenhum evento acima do threshold")

        print(f"  Artefato: {path}")

    summary_path = storage.save_batch_summary(results)

    print_section("RESUMO")
    print(f"  Pacientes analisados : {len(results)}")
    print(f"  Com predição ativa   : {sum(1 for r in results if r.predictions)}")
    print(f"  Batch summary        : {summary_path}")
    print(f"\n  Pipeline: Kalman+Hampel → Ghost → Fuzzy Mamdani → Bayes Fusion → CUSUM")
    print(f"  Saída   : data/clinical_intelligence/")


if __name__ == "__main__":
    main()