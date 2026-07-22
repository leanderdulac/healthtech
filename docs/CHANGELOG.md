# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/). O projeto segue versionamento por feature documentada em [`FEATURES.md`](FEATURES.md).

## [Unreleased]

### Added
- **Hardening de segurança** — `src/security/auth.py` (API key `X-API-Key`, CORS restrito, validação de `SECRET_SALT`)
- Auth nas APIs `health-aggregator` e `src/api_server.py` (REST + WebSocket `?api_key=`)
- Endpoint público `/api/health` e `/health` para probes
- Suite de testes `tests/` + `pytest.ini` + `requirements-dev.txt`
- CI GitHub Actions (`.github/workflows/ci.yml`)
- Dockerfile multi-stage com usuário não-root, HEALTHCHECK e uvicorn
- Deploy GCP exige `API_KEY`/`SECRET_SALT`; auth pública opt-in (`ALLOW_UNAUTHENTICATED`)
- **F18** — Dashboard glassmórfico, signal processing avançado, phantom data EKF/UKF, rede bayesiana, anomaly ensemble
- **F17** — Framework de produção (`src/integrations/production/`, `run_production_pipeline.py`)
- Ingestão real: Apple Health, Google Fit, BLE (`src/ingestion/real/`, `run_real_ingestion.py`)
- Integração clínica FHIR Server (`src/integrations/clinical/`, `run_clinical_sync.py`)
- Deploy Vertex AI dos 3 TCNs (`src/integrations/vertex/deploy/`, `run_vertex_deploy.py`)
- Conformal prediction multi-horizonte (`run_conformal_calibration.py`)
- Validação clínica com relatório JSON (`run_clinical_validation.py`)
- Fase 9 no VertexIntegrationOrchestrator
- **F16** — Modelo temporal TCN+BiLSTM com features ghost+fuzzy (`run_temporal_training.py`)
- Predição multi-horizonte: 6h, 24h, 72h com BCE ponderada e early stopping
- **F15** — Inteligência clínica preditiva multimodal (`src/clinical_intelligence/`, `run_clinical_prediction.py`)
- Filtragem Kalman+Hampel, sinais fantasmas, fuzzy Mamdani, fusão Bayesiana, CUSUM
- Fase 8 no VertexIntegrationOrchestrator para predição com lead time
- **F14** — Módulo hemodinâmica grad/div/curl (`src/hemodynamics/`, `run_hemodynamics_analysis.py`)
- Simulador vascular 3D com cenários: normal, stenosis, aneurysm, turbulent
- Detecção de irregularidades (gradiente, divergência, curl) + alertas FHIR
- Fase 7 no VertexIntegrationOrchestrator para análise hemodinâmica
- **F13** — Ontologia médica integrada (`src/ontology/`, `run_ontology_integration.py`)
- Features ML enriquecidas com domínios ontológicos (`ont_cardiovascular`, etc.)
- FHIR CodeSystem exportado a partir da ontologia USP
- Fase 6 no VertexIntegrationOrchestrator para sync de ontologia
- **F12** — Scraper USP Teses de Medicina (`src/scraping/usp_teses/`, `run_usp_scraper.py`)
- Construtor de ontologia a partir de palavras-chave e áreas de concentração
- Corpus NLP (`training_corpus.txt`) para treino de modelos
- **F08** — Módulo FHIR R4/HL7 (`src/fhir/`) com terminologias LOINC, UCUM, SNOMED CT
- **F09** — Exportação FHIR: Bundle JSON, NDJSON bulk (`run_fhir_export.py`)
- **F10** — Tabela BigQuery `fhir_resources` com JSON nativo FHIR
- **F07** — Anonimização aprimorada com perfil HL7 de-identification
- Documentação: `README.md`, `docs/ARCHITECTURE.md`, `docs/FEATURES.md`, `docs/CHANGELOG.md`
- Diagrama `docs/diagrams/05-fhir-hl7.mmd`
- Variáveis de ambiente FHIR em `.env.example`
- Dependência `fhir.resources>=7.0.0,<8.0.0`

### Changed
- `DatalakeOrchestrator` exporta Bundle FHIR automaticamente após pipeline
- `BigQueryBridge` sincroniza `fhir_resources` além de tabelas legadas
- `bigquery_setup.py` provisiona schema FHIR nativo
- `data_generator.py` gera recursos FHIR com códigos LOINC
- `fluxo-completo.mmd` atualizado com fases FHIR
- Anonimização FHIR: remove `city` do endereço (minimização LGPD)
- `health-aggregator` default DB = SQLite local; PostgreSQL via `DATABASE_URL`
- `requirements.txt` sem duplicatas; ranges alinhados ao aggregator
- `.gitignore` ignora `data/chroma_db/` e `data/lake/`

### Fixed
- Compatibilidade `fhir.resources` v7 (R4) via `src/fhir/compat.py`
- IDs de Device normalizados para pattern FHIR `[A-Za-z0-9\-.]+`
- Import circular entre `datalake` e `fhir` resolvido com lazy import
- `datetime.utcnow()` substituído por `datetime.now(timezone.utc)` no aggregator/API

---

## [0.2.0] — 2026-06

### Added
- **F05** — Integração Vertex AI (treino, online, batch)
- **F06** — BigQuery Bridge com fallback local
- `run_vertex_integration.py`, `run_datalake_pipeline.py`
- `src/integrations/vertex/` — orquestrador, pipelines, feature builder
- Documentação visual: `docs/diagrams/`, apresentação PPTX

---

## [0.1.0] — 2026-06

### Added
- **F01** — Datalake Medallion (Bronze → Silver → Gold)
- **F02** — Simulação de telemetria 24h multi-wearable
- **F03** — Quality Gates entre camadas
- **F04** — Camada de extração (timeline, vitals, anomalias, coorte)
- **F11** — Reconciliação multi-sensor
- `main_simulation.py`, `src/datalake/`, `src/ml_pipeline/`