#!/usr/bin/env python3
"""
Integração completa: Datalake de Telemetria 24h → Vertex AI.

Fluxo:
  Datalake (Bronze→Silver→Gold) → Features → Treino → Online → Batch
"""

import logging
from datetime import datetime
from pathlib import Path

from src.datalake.config import LakehouseConfig
from src.datalake.utils.telemetry_simulator import SimulationConfig
from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.orchestrator import VertexIntegrationOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    print_section("INTEGRAÇÃO DATALAKE → VERTEX AI")

    lakehouse_config = LakehouseConfig(base_path=Path("data/lakehouse"))
    vertex_config = VertexConfig()

    print(f"\n  GCP Project           : {vertex_config.project_id}")
    print(f"  GCP Location          : {vertex_config.location}")
    print(f"  Vertex Endpoint       : {vertex_config.endpoint_id}")
    print(f"  Vertex Model          : {vertex_config.model_name}")
    print(f"  GCP Configurado       : {'Sim' if vertex_config.is_gcp_configured else 'Não (modo local)'}")

    orchestrator = VertexIntegrationOrchestrator(lakehouse_config, vertex_config)

    sim_config = SimulationConfig(
        num_patients=3,
        hours=6.0,
        hr_interval_seconds=10,
        anomaly_probability=0.03,
        seed=42,
    )

    start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    print_section("EXECUTANDO PIPELINE INTEGRADO")
    result = orchestrator.run_full_integration(
        simulation_config=sim_config,
        start_time=start_time,
        online_max_records=15,
    )

    dl = result.datalake
    print(f"\n  --- Datalake ---")
    print(f"  Bronze eventos        : {dl.ingestion.get('total', 0)}")
    print(f"  Silver janelas        : {dl.silver_rows}")
    print(f"  Gold hourly           : {dl.gold_hourly_rows}")
    print(f"  Gold daily            : {dl.gold_daily_rows}")
    print(f"  Gold alerts           : {dl.gold_alerts_rows}")

    print(f"\n  --- Treinamento ---")
    print(f"  Amostras              : {result.training.get('training_samples', 0)}")
    local = result.training.get("local_model", {})
    print(f"  Modelo local          : {local.get('status', 'N/A')}")
    if local.get("anomaly_rate") is not None:
        print(f"  Taxa anomalia treino  : {local['anomaly_rate']:.1%}")
    print(f"  CSV treino            : {result.training.get('csv_path', 'N/A')}")
    vtx_train = result.training.get("vertex_training", {})
    print(f"  Vertex Training       : {vtx_train.get('status', 'N/A')}")

    print(f"\n  --- Inferência Online ---")
    print(f"  Leituras processadas  : {len(result.online)}")
    if result.online:
        alerts = [r for r in result.online if r.get("alerta")]
        print(f"  Alertas detectados    : {len(alerts)}")
        print(f"  Modo                  : {result.online[0].get('modo', 'N/A')}")
        print(f"\n  Últimas 5 leituras:")
        for r in result.online[-5:]:
            print(f"    BPM={r.get('valor_atual', 0):.0f} SpO2={r.get('spo2', 0):.0f} "
                  f"score={r.get('score', 0):.2f} [{r.get('status', '')}]")

    print(f"\n  --- Inferência Batch ---")
    print(f"  Status                : {result.batch.get('status', 'N/A')}")
    print(f"  Registros input       : {result.batch.get('input_records', 0)}")
    print(f"  Anomalias locais      : {result.batch.get('local_anomalies', 0)}")
    print(f"  JSONL input           : {result.batch.get('jsonl_path', 'N/A')}")
    print(f"  Predições locais      : {result.batch.get('local_predictions_path', 'N/A')}")

    vtx_job = result.batch.get("vertex_job", {})
    if vtx_job.get("job_url"):
        print(f"  Vertex Job URL        : {vtx_job['job_url']}")
    elif vtx_job.get("mensagem"):
        print(f"  Vertex Batch          : {vtx_job['mensagem']}")

    gcs = result.batch.get("gcs_upload", {})
    if gcs.get("upload_command"):
        print(f"\n  Para submeter batch real no GCP:")
        print(f"    {gcs['upload_command']}")

    print(f"\n  --- FHIR Export (HL7 R4) ---")
    fhir = dl.fhir_export or {}
    if fhir:
        print(f"  Bundle FHIR           : {fhir.get('bundle_path', 'N/A')}")
        print(f"  NDJSON                : {fhir.get('ndjson_path', 'N/A')}")
        val = fhir.get("validation", {})
        print(f"  Recursos              : {val.get('resource_counts', {})}")

    print(f"\n  --- BigQuery Sync ---")
    bq = result.bigquery
    if bq:
        prov = bq.get("provision", {})
        fhir_bq = bq.get("fhir_resources", {})
        silv = bq.get("silver_biometrics", {})
        gold = bq.get("gold_daily", {})
        print(f"  Provisionamento       : {prov.get('status', 'N/A')}")
        print(f"  FHIR → BQ             : {fhir_bq.get('status', 'N/A')} ({fhir_bq.get('rows', 0)} rows)")
        print(f"  Silver → BQ           : {silv.get('status', 'N/A')} ({silv.get('rows', 0)} rows)")
        print(f"  Gold daily → BQ       : {gold.get('status', 'N/A')} ({gold.get('rows', 0)} rows)")
        if silv.get("path"):
            print(f"  Fallback local        : {silv['path']}")

    print_section("INTEGRAÇÃO CONCLUÍDA")
    print(f"  Artefatos em          : data/vertex_exports/ e data/models/")
    print(f"  Lakehouse em          : {lakehouse_config.base_path.resolve()}")
    print(f"  Diagramas/docs        : docs/Healthtech_Datalake_VertexAI.pptx")
    print(f"  Visualização HTML     : docs/diagramas.html")


if __name__ == "__main__":
    main()