# Arquitetura

## Diagrama de fluxo completo

```mermaid
flowchart TB
    subgraph ENTRADAS["Pontos de entrada"]
        MAIN["main_simulation.py"]
        DL["run_datalake_pipeline.py"]
        VTX["run_vertex_integration.py"]
        FHIR["run_fhir_export.py"]
    end

    subgraph FONTE["Fonte de dados"]
        SIM["TelemetrySimulator"]
        DEV["DeviceRegistry"]
    end

    subgraph LAKE["Datalake Medallion"]
        BRONZE["Bronze: telemetry_raw"]
        QG1{"Quality Gate B→S"}
        SILVER["Silver: telemetry_curated"]
        QG2{"Quality Gate S→G"}
        GOLD_H["Gold: hourly_vitals"]
        GOLD_D["Gold: daily_summary"]
        GOLD_A["Gold: patient_alerts"]
    end

    subgraph FHIR_MOD["FHIR R4 / HL7"]
        MAP["Mappers"]
        BUILD["Builders"]
        EXP_FHIR["FhirExporter"]
    end

    subgraph ML["Vertex AI"]
        FB["FeatureBuilder"]
        TRAIN["Treinamento"]
        ONLINE["Inferência Online"]
        BATCH["Inferência Batch"]
    end

    subgraph DESTINOS["Destinos"]
        BQ["BigQuery"]
        OUT["Artefatos locais"]
    end

    MAIN --> VTX
    DL --> ORCH_DL["DatalakeOrchestrator"]
    VTX --> ORCH_VTX["VertexIntegrationOrchestrator"] --> ORCH_DL
    FHIR --> ORCH_DL

    SIM --> DEV --> BRONZE
    ORCH_DL --> BRONZE --> QG1 --> SILVER --> QG2
    QG2 --> GOLD_H & GOLD_D & GOLD_A

    SILVER & GOLD_A --> MAP --> BUILD --> EXP_FHIR --> OUT
    ORCH_VTX --> FB --> TRAIN & ONLINE & BATCH
    ORCH_VTX --> BQ
    EXP_FHIR --> BQ
```

## Pipeline integrado (Vertex)

Corresponde a `run_vertex_integration.py` e `main_simulation.py`:

```mermaid
flowchart LR
    P1["Fase 1<br/>Datalake"] --> P2["Fase 2<br/>Treinamento"]
    P2 --> P3["Fase 3<br/>Online"]
    P2 --> P4["Fase 4<br/>Batch"]
    P1 --> P5["Fase 5<br/>BigQuery + FHIR"]
```

| Fase | Módulo | Saída |
|------|--------|-------|
| 1 | `DatalakeOrchestrator` | `data/lakehouse/`, Bundle FHIR |
| 2 | `VertexTrainingPipeline` | `data/models/`, CSV treino |
| 3 | `VertexOnlinePipeline` | Alertas em tempo real |
| 4 | `VertexBatchPipeline` | JSONL + predições |
| 5 | `BigQueryBridge` | BQ ou `data/bigquery_simulation/` |

## Arquitetura Medallion

```mermaid
flowchart LR
    subgraph BRONZE["Bronze"]
        B1[event_id + device]
        B2[metric + value + unit]
        B3[timestamp + raw_payload]
    end

    subgraph SILVER["Silver"]
        S1[janela temporal 5s]
        S2[reconciliação multi-sensor]
        S3[quality_score + is_anomaly]
    end

    subgraph GOLD["Gold"]
        G1[hourly_vitals]
        G2[daily_summary]
        G3[patient_alerts]
    end

    BRONZE -->|ETL| SILVER -->|agregação| GOLD
```

## Camada FHIR

```mermaid
flowchart LR
    SILVER --> OBS["Observation<br/>LOINC + UCUM"]
    GOLD_A --> FLAG["Flag<br/>alertas clínicos"]
    PROFILE --> PAT["Patient"]
    DEVICE --> DEV_FHIR["Device<br/>SNOMED CT"]
    OBS & FLAG & PAT & DEV_FHIR --> BUNDLE["Bundle JSON"]
    BUNDLE --> NDJSON["NDJSON bulk"]
    BUNDLE --> BQ_FHIR["BigQuery fhir_resources"]
```

## Modos de operação

| Modo | Condição | Comportamento |
|------|----------|---------------|
| Local | `GCP_PROJECT_ID` não configurado | Parquet + simulação BQ/Vertex |
| GCP | Credenciais + `.env` válido | BigQuery sync + Vertex Endpoint |
| Híbrido | GCP parcial | Fallback local com log de aviso |

## Diagramas estáticos

Arquivos em `docs/diagrams/`:

| Arquivo | Conteúdo |
|---------|----------|
| `01-visao-geral.mmd` | Visão geral do sistema |
| `02-sequencia.mmd` | Sequência de execução |
| `03-medallion.mmd` | Camadas Bronze/Silver/Gold |
| `04-vertex-modos.mmd` | Modos Vertex AI |
| `05-fhir-hl7.mmd` | Fluxo FHIR R4 |
| `fluxo-completo.mmd` | Pipeline end-to-end atualizado |

SVGs/PNGs gerados a partir dos `.mmd` estão na mesma pasta.