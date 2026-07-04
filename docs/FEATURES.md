# Documentação por Feature

Cada feature embutida no projeto está documentada abaixo com objetivo, componentes, entradas/saídas e como executar.

---

## F01 — Datalake Medallion (Bronze → Silver → Gold)

**Objetivo:** Armazenar e transformar telemetria de wearables em camadas progressivas de qualidade.

**Componentes:**
- `src/datalake/storage/local_parquet_store.py` — persistência Parquet particionada
- `src/datalake/schemas/` — schemas Bronze, Silver, Gold
- `src/datalake/pipeline/bronze_to_silver.py` — ETL com reconciliação
- `src/datalake/pipeline/silver_to_gold.py` — agregações e alertas
- `src/datalake/pipeline/orchestrator.py` — orquestração

**Camadas:**

| Camada | Tabela | Descrição |
|--------|--------|-----------|
| Bronze | `telemetry_raw` | Dados brutos com payload original |
| Silver | `telemetry_curated` | Reconciliado, validado, enriquecido |
| Gold | `hourly_vitals` | Agregação horária de sinais vitais |
| Gold | `daily_summary` | Resumo clínico 24h por paciente |
| Gold | `patient_alerts` | Alertas clínicos (taquicardia, hipoxemia, etc.) |

**Execução:** `python run_datalake_pipeline.py`

---

## F02 — Simulação de Telemetria 24h

**Objetivo:** Gerar stream contínuo de dados biométricos multi-paciente e multi-dispositivo.

**Componentes:**
- `src/datalake/utils/telemetry_simulator.py` — `TelemetrySimulator`, `SimulationConfig`
- `src/datalake/ingestion/device_registry.py` — registro paciente ↔ dispositivo
- `src/datalake/ingestion/telemetry_ingestor.py` — ingestão Bronze

**Métricas simuladas:** heart_rate, spo2, hrv, steps, stress_index

**Parâmetros:** `num_patients`, `hours`, `hr_interval_seconds`, `anomaly_probability`

---

## F03 — Quality Gates

**Objetivo:** Validar integridade entre transições de camada.

**Componentes:**
- `src/datalake/quality/quality_gates.py` — `QualityGateRunner`
- `src/datalake/quality/validators.py` — regras de validação

**Gates:**
- Bronze → Silver: taxa de passagem, cobertura, duplicatas
- Silver → Gold: completude de agregações, consistência de alertas

---

## F04 — Camada de Extração

**Objetivo:** Consultar dados processados por paciente, janela temporal ou coorte.

**Componentes:**
- `src/datalake/extraction/query_engine.py` — fachada unificada
- Extractors: `patient_timeline`, `vitals_stream`, `anomaly_windows`, `population_cohort`

**API principal:**
```python
orchestrator.query_engine.extract_patient_24h(patient_id, partition_date)
orchestrator.query_engine.extract_high_risk_cohort(min_risk_score=0.3)
```

---

## F05 — Integração Vertex AI (ML)

**Objetivo:** Treinar e executar detecção de anomalias com modelo local e Vertex AI.

**Componentes:**
- `src/integrations/vertex/orchestrator.py` — orquestração unificada
- `src/integrations/vertex/feature_builder.py` — features a partir do datalake
- `src/integrations/vertex/training_pipeline.py` — treino local + Vertex CustomTraining
- `src/integrations/vertex/online_pipeline.py` — inferência em tempo real
- `src/integrations/vertex/batch_pipeline.py` — inferência em lote (coorte)
- `src/integrations/vertex/local_model.py` — Isolation Forest local

**Fases do pipeline integrado:**
1. Datalake completo
2. Treinamento → `data/models/anomaly_detector.pkl`
3. Inferência online (stream vitals)
4. Inferência batch (JSONL → predições)
5. Sync BigQuery + FHIR

**Execução:** `python run_vertex_integration.py`

---

## F06 — BigQuery Bridge

**Objetivo:** Sincronizar dados processados para Google BigQuery (ou simulação local).

**Componentes:**
- `src/integrations/bigquery_bridge.py` — `BigQueryBridge`
- `src/data_warehouse/bigquery_setup.py` — provisionamento de tabelas

**Tabelas:**
- `fhir_resources` — recursos FHIR R4 em JSON
- `wearable_biometrics` — biometria com LOINC (compatibilidade)
- `gold_daily_summary` — resumos diários

**Modo fallback:** sem GCP, grava Parquet em `data/bigquery_simulation/`.

---

## F07 — Anonimização FHIR (De-identification HL7)

**Objetivo:** Remover PII de recursos FHIR Patient mantendo utilidade analítica.

**Componentes:**
- `src/security/anonymization.py` — `anonimizar_paciente_fhir()`
- `src/utils/data_generator.py` — mocks com e sem PII

**Regras aplicadas:**
- Remove `name`, `telecom`, `photo`, `contact`
- Generaliza `birthDate` para ano (`YYYY-01-01`)
- Substitui identificadores por hash SHA-256 com salt
- Generaliza endereço (cidade, estado, país)
- Adiciona `meta.security` com código `HTEST`
- Perfil HL7: `http://hl7.org/fhir/uv/anonymization/StructureDefinition/anonymized`

---

## F08 — Interoperabilidade FHIR R4 / HL7

**Objetivo:** Adaptar dados internos ao padrão HL7 FHIR R4 com terminologias abertas.

**Componentes:**
- `src/fhir/terminology.py` — LOINC, UCUM, SNOMED CT, HL7 CodeSystems
- `src/fhir/builders.py` — construtores de recursos FHIR
- `src/fhir/mappers.py` — Bronze/Silver/Gold → FHIR
- `src/fhir/validator.py` — validação de recursos
- `src/fhir/compat.py` — compatibilidade `fhir.resources` v7 (R4)
- `src/fhir/export.py` — `FhirExporter`

**Recursos FHIR:**

| Recurso | Perfil | Origem |
|---------|--------|--------|
| Patient | HealthtechPatient | PatientProfile / mock |
| Device | HealthtechWearableDevice | DeviceBinding |
| Observation | HealthtechVitalSignObservation | Bronze/Silver |
| Flag | HealthtechClinicalAlert | Gold patient_alerts |
| Bundle | collection | Empacotamento bulk |

**Dependência:** `fhir.resources>=7.0.0,<8.0.0`

---

## F09 — Exportação FHIR (Bundle + NDJSON)

**Objetivo:** Exportar artefatos FHIR para interoperabilidade e integração externa.

**Componentes:**
- `src/fhir/export.py` — `FhirExporter`
- `run_fhir_export.py` — entry point dedicado

**Saídas:**

| Arquivo | Formato | Conteúdo |
|---------|---------|----------|
| `bundle_*.json` | FHIR Bundle | Patient + Device + Observation + Flag |
| `resources_*.ndjson` | NDJSON bulk | Todos os recursos do bundle |
| `Observation_silver_*.ndjson` | NDJSON | Observações por camada |
| `Patient_*.ndjson` | NDJSON | Pacientes |
| `Device_*.ndjson` | NDJSON | Dispositivos |

**Diretório:** `data/fhir_exports/`

**Execução:** `python run_fhir_export.py`

---

## F10 — BigQuery FHIR Nativo

**Objetivo:** Armazenar recursos FHIR completos em JSON no warehouse.

**Schema `fhir_resources`:**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| resource_type | STRING | Patient, Observation, Device, Flag |
| resource_id | STRING | ID do recurso |
| patient_id | STRING | Referência Patient |
| effective_datetime | TIMESTAMP | Data efetiva |
| fhir_version | STRING | R4 |
| last_updated | TIMESTAMP | Última atualização |
| resource_json | JSON | Recurso FHIR completo |

**Integração:** automática no `VertexIntegrationOrchestrator` (Fase 5).

---

## F11 — Reconciliação Multi-sensor (Legado)

**Objetivo:** Deduplicar leituras de múltiplos sensores em janelas temporais.

**Componentes:**
- `src/ingestion/data_reconciliation.py`
- Integrado no `BronzeToSilverTransformer` (F01)

---

## Mapa de dependências entre features

```
F02 (Simulação) → F01 (Datalake) → F03 (Quality Gates)
                                  → F04 (Extração)
                                  → F08 (FHIR) → F09 (Export) → F10 (BQ FHIR)
                                  → F05 (Vertex) → F06 (BigQuery)
F07 (Anonimização) → F08 (FHIR)
```