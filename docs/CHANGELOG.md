# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/). O projeto segue versionamento por feature documentada em [`FEATURES.md`](FEATURES.md).

## [Unreleased]

### Added
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

### Fixed
- Compatibilidade `fhir.resources` v7 (R4) via `src/fhir/compat.py`
- IDs de Device normalizados para pattern FHIR `[A-Za-z0-9\-.]+`
- Import circular entre `datalake` e `fhir` resolvido com lazy import

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