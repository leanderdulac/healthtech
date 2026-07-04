#!/usr/bin/env python3
"""
Pipeline completo do Datalake de Telemetria 24h — demonstração end-to-end.

Arquitetura Medallion:
  Bronze (raw) → Silver (curated) → Gold (analytics) → Extração
"""

import json
import logging
from datetime import datetime

from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.datalake.utils.telemetry_simulator import SimulationConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    print_section("DATALAKE DE SAÚDE — TELEMETRIA 24H DE WEARABLES")

    config = LakehouseConfig(base_path=__import__("pathlib").Path("data/lakehouse"))
    orchestrator = DatalakeOrchestrator(config)

    sim_config = SimulationConfig(
        num_patients=5,
        hours=24.0,
        hr_interval_seconds=5,
        anomaly_probability=0.03,
        seed=42,
    )

    start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    print_section("FASE 1 — INGESTÃO E TRANSFORMAÇÃO (Bronze → Silver → Gold)")
    result = orchestrator.run_full_pipeline(
        simulation_config=sim_config,
        start_time=start_time,
    )

    print(f"\n  Pacientes processados : {len(result.patients)}")
    print(f"  Partições             : {result.partition_dates}")
    print(f"  Bronze  (ingestão)    : {result.ingestion['total']} eventos "
          f"({result.ingestion['valid']} válidos)")
    print(f"  Silver  (curated)     : {result.silver_rows} janelas reconciliadas")
    print(f"  Gold    (hourly)      : {result.gold_hourly_rows} buckets horários")
    print(f"  Gold    (daily)       : {result.gold_daily_rows} resumos diários")
    print(f"  Gold    (alerts)      : {result.gold_alerts_rows} alertas clínicos")

    fhir = result.fhir_export or {}
    if fhir:
        print(f"\n  FHIR Bundle           : {fhir.get('bundle_path', 'N/A')}")
        validation = fhir.get("validation", {})
        print(f"  FHIR validacao        : {'OK' if validation.get('all_valid') else 'COM ERROS'}")
        print(f"  Recursos FHIR         : {validation.get('resource_counts', {})}")

    print(f"\n  Quality Gate B→S      : {'PASSOU' if result.quality_bronze_silver['passed'] else 'FALHOU'}")
    print(f"  Quality Gate S→G      : {'PASSOU' if result.quality_silver_gold['passed'] else 'FALHOU'}")

    print_section("FASE 2 — ESTATÍSTICAS DO LAKEHOUSE")
    stats = orchestrator.query_engine.get_lakehouse_stats()
    for layer, info in stats.items():
        if layer == "lineage_events":
            print(f"  Eventos de lineage    : {info}")
            continue
        print(f"  [{layer.upper()}] partições={info['partitions']} "
              f"registros={info['total_records']} pacientes={info['patients']}")

    print_section("FASE 3 — EXTRAÇÃO DE DADOS (Paciente Individual 24h)")
    sample_patient = result.patients[0]
    partition = result.partition_dates[0]
    extraction = orchestrator.demonstrate_extraction(sample_patient, partition)

    print(f"\n  Paciente              : {sample_patient}")
    print(f"  Partição              : {partition}")
    print(f"  Timeline (silver)     : {len(extraction['timeline'])} registros")
    print(f"  Vitals stream         : {len(extraction['vitals_stream'])} janelas")
    print(f"  Episódios anômalos    : {len(extraction['anomaly_episodes'])} episódios")
    print(f"  Resumo diário (gold)  : {len(extraction['daily_summary'])} registro(s)")
    print(f"  Alertas (gold)        : {len(extraction['alerts'])} alerta(s)")

    if not extraction["daily_summary"].empty:
        summary = extraction["daily_summary"].iloc[0]
        print(f"\n  --- Resumo Clínico 24h ---")
        print(f"  BPM repouso médio     : {summary.get('avg_resting_hr', 0):.1f}")
        print(f"  BPM máximo            : {summary.get('max_hr', 0):.0f}")
        print(f"  SpO2 médio            : {summary.get('avg_spo2', 0):.1f}%")
        print(f"  Horas de sono         : {summary.get('sleep_hours', 0):.1f}h")
        print(f"  Passos totais         : {summary.get('total_steps', 0)}")
        print(f"  Episódios anômalos    : {summary.get('anomaly_episodes', 0)}")
        print(f"  Cobertura 24h         : {summary.get('coverage_24h', 0):.1%}")
        print(f"  Risco clínico         : {summary.get('clinical_risk_level', 'N/A')}")

    if not extraction["anomaly_episodes"].empty:
        print(f"\n  --- Top Episódios Anômalos ---")
        for _, ep in extraction["anomaly_episodes"].head(3).iterrows():
            print(f"  • {ep['episode_start']} → {ep['episode_end']} "
                  f"({ep['duration_minutes']:.1f}min) "
                  f"score={ep['max_anomaly_score']} "
                  f"métricas={ep['metrics_involved']}")

    print_section("FASE 4 — EXTRAÇÃO POPULACIONAL (Coorte de Alto Risco)")
    cohort = orchestrator.query_engine.extract_high_risk_cohort(min_risk_score=0.3)
    print(f"\n  Pacientes alto risco  : {len(cohort)}")
    if not cohort.empty:
        for _, row in cohort.iterrows():
            print(f"  • {row['patient_id']} | risco={row['clinical_risk_level']} "
                  f"| anomalias={row.get('anomaly_episodes', 0)} "
                  f"| alertas={row.get('total_alerts', 0)}")

    print_section("PIPELINE CONCLUÍDO")
    print(f"  Dados persistidos em  : {config.base_path.resolve()}")
    print(f"  Próximo passo         : python run_vertex_integration.py")


if __name__ == "__main__":
    main()