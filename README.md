# Healthtech — Datalake de Telemetria + FHIR + Vertex AI

Plataforma de processamento de telemetria contínua 24h de wearables com arquitetura **Medallion** (Bronze → Silver → Gold), interoperabilidade **HL7 FHIR R4** e detecção de anomalias via **Vertex AI**.

## Visão geral

O projeto simula e processa dados biométricos de relógios inteligentes (frequência cardíaca, SpO2, HRV, passos, stress), aplica qualidade e reconciliação multi-sensor, gera agregações clínicas, exporta recursos FHIR e alimenta pipelines de ML para detecção de anomalias.

```
Wearables → Bronze → Silver → Gold → Extração / FHIR / Vertex AI / BigQuery
```

Diagramas detalhados em [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) e [`docs/diagrams/`](docs/diagrams/).

## Requisitos

- Python 3.11+
- Dependências em `requirements.txt`
- Google Cloud (opcional): Vertex AI, BigQuery, Cloud Storage

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # configure variáveis GCP e SECRET_SALT
```

## Execução

| Comando | Descrição |
|---------|-----------|
| `python main_simulation.py` | Pipeline completo (redireciona para Vertex) |
| `python run_datalake_pipeline.py` | Datalake + FHIR + extração |
| `python run_vertex_integration.py` | Pipeline completo (ML + FHIR + Predição) |
| `python run_fhir_export.py` | Exportação FHIR dedicada |
| `python run_usp_scraper.py` | Scraper de teses USP (medicina) |
| `python run_ontology_integration.py` | Integração ontologia → FHIR + ML |
| `python run_hemodynamics_analysis.py` | Análise hemodinâmica grad/div/curl |
| `python run_clinical_prediction.py` | Predição clínica multimodal (fuzzy + ghost) |

## Estrutura do projeto

```
healthtech-main/
├── main_simulation.py          # Entry point unificado
├── run_datalake_pipeline.py    # Pipeline datalake
├── run_vertex_integration.py   # Integração Vertex AI
├── run_fhir_export.py          # Exportação FHIR R4
├── requirements.txt
├── .env.example
├── src/
│   ├── datalake/               # Lakehouse Medallion
│   ├── fhir/                   # Interoperabilidade HL7 FHIR R4
│   ├── integrations/           # BigQuery + Vertex AI
│   ├── ml_pipeline/            # Treino e inferência
│   ├── scraping/               # Scraper teses USP
│   ├── ontology/               # Ontologia médica integrada
│   ├── hemodynamics/           # Análise vascular grad/div/curl
│   ├── clinical_intelligence/  # Predição clínica fuzzy + ghost signals
│   ├── security/               # Anonimização FHIR
│   └── utils/                  # Geradores de dados
└── docs/
    ├── ARCHITECTURE.md         # Arquitetura e fluxos
    ├── FEATURES.md             # Documentação por feature
    ├── CHANGELOG.md            # Histórico de versões
    └── diagrams/               # Diagramas Mermaid/SVG
```

## Artefatos gerados

| Caminho | Conteúdo |
|---------|----------|
| `data/lakehouse/` | Parquet Bronze/Silver/Gold |
| `data/fhir_exports/` | Bundle JSON, NDJSON bulk FHIR |
| `data/vertex_exports/` | CSV treino, JSONL batch |
| `data/models/` | Modelo local `anomaly_detector.pkl` |
| `data/bigquery_simulation/` | Fallback local quando GCP não configurado |
| `data/scraping/usp_teses/` | Teses USP, ontologia e corpus NLP |
| `data/hemodynamics/` | Análises hemodinâmicas e FHIR Flags |
| `data/clinical_intelligence/` | Predições clínicas com lead time |

## Interoperabilidade FHIR R4

Recursos suportados: `Patient`, `Device`, `Observation`, `Flag`, `Bundle`.

| Métrica | LOINC | UCUM |
|---------|-------|------|
| Frequência cardíaca | 8867-4 | /min |
| SpO2 | 2708-6 | % |
| Passos | 55423-8 | {steps} |
| HRV | 80404-7 | ms |

Documentação completa em [`docs/FEATURES.md`](docs/FEATURES.md#f08--interoperabilidade-fhir-r4--hl7).

## Configuração GCP

Variáveis em `.env.example`:

- `GCP_PROJECT_ID`, `GCP_LOCATION`
- `VERTEX_ENDPOINT_ID`, `VERTEX_MODEL_NAME`
- `GCS_STAGING_BUCKET`, `GCS_INPUT_DATA`, `GCS_OUTPUT_DATA`
- `BQ_DATASET`, `BQ_LOCATION`
- `SECRET_SALT` (anonimização FHIR)
- `FHIR_VERSION`, `FHIR_EXPORT_DIR`

Sem GCP configurado, o projeto opera em **modo local** com simulação de BigQuery e Vertex.

## Documentação

- [Arquitetura](docs/ARCHITECTURE.md)
- [Features](docs/FEATURES.md)
- [Changelog](docs/CHANGELOG.md)

## Licença

Projeto interno — uso conforme políticas da organização.