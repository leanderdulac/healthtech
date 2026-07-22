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
# opcional (dev/CI):
pip install -r requirements-dev.txt
cp .env.example .env   # configure GCP, SECRET_SALT e API_KEY
```

### Segurança (obrigatório em produção)

| Variável | Descrição |
|----------|-----------|
| `ENVIRONMENT` | `development` ou `production` |
| `SECRET_SALT` | Salt forte para hash de IDs FHIR (`openssl rand -hex 32`) |
| `API_KEY` | Chave para header `X-API-Key` nas APIs |
| `AUTH_DISABLED` | `true` só em dev local (ignorado em production) |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |

Endpoints `/health` e `/api/health` são públicos (probes). Demais rotas exigem API key quando configurada.

## Execução

| Comando | Descrição |
|---------|-----------|
| `python main_simulation.py` | Demo de sinais avançados + phantom + ontologia |
| `python run_datalake_pipeline.py` | Datalake + FHIR + extração |
| `python run_vertex_integration.py` | Pipeline completo (ML + FHIR + Predição) |
| `python run_fhir_export.py` | Exportação FHIR dedicada |
| `python run_usp_scraper.py` | Scraper de teses USP (medicina) |
| `python run_ontology_integration.py` | Integração ontologia → FHIR + ML |
| `python run_hemodynamics_analysis.py` | Análise hemodinâmica grad/div/curl |
| `python run_clinical_prediction.py` | Predição clínica multimodal (fuzzy + ghost) |
| `python run_temporal_training.py` | Treino TCN+LSTM ghost+fuzzy (6h/24h/72h) |
| `python run_real_ingestion.py` | Ingestão real (Apple Health / Google Fit / BLE) |
| `python run_clinical_sync.py` | Sync FHIR Server → baseline clínico |
| `python run_conformal_calibration.py` | Calibração conformal nos TCNs |
| `python run_clinical_validation.py` | Validação clínica (métricas + relatório) |
| `python run_vertex_deploy.py` | Deploy dos 3 TCNs no Vertex AI |
| `python run_production_pipeline.py` | Pipeline de produção F17 completo |
| `cd health-aggregator && uvicorn main:app --port 8000` | API REST de agregação multimodal |
| `uvicorn src.api_server:app --port 8080` | API + dashboard + WebSocket telemetria |
| `streamlit run dashboard/app.py` | Dashboard Streamlit MLOps |
| `pytest` | Suite de testes unitários |

## Estrutura do projeto

```
healthtech-main/
├── main_simulation.py          # Demo sinais + phantom + ontologia
├── run_*.py                    # Entry points por feature
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile                  # Cloud Run (non-root + healthcheck)
├── deploy_to_gcp.sh
├── tests/                      # Pytest (auth, FHIR, quality, hemodynamics)
├── dashboard/                  # UI glassmórfica + Streamlit
├── health-aggregator/          # API REST agregação multimodal
├── src/
│   ├── api_server.py           # FastAPI + WebSocket dashboard
│   ├── datalake/               # Lakehouse Medallion
│   ├── fhir/                   # HL7 FHIR R4
│   ├── integrations/           # BigQuery + Vertex AI
│   ├── ml_pipeline/            # Treino, inferência, RAG
│   ├── signal_processing/      # Wavelet, Butterworth, fusão
│   ├── phantom_data/           # EKF/UKF + HRV
│   ├── anomaly_detection/      # Ensemble temporal
│   ├── clinical_intelligence/  # Fuzzy + ghost + TCN + conformal
│   ├── security/               # Auth API + anonimização FHIR
│   └── ...
└── docs/
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