# Health Aggregator

API REST que agrega telemetria wearable, dados clínicos FHIR e predições TCN do projeto Healthtech em uma visão unificada por paciente.

## Estrutura

```
health-aggregator/
├── main.py          # FastAPI — endpoints REST
├── models.py        # HealthRecord + AggregationRun
├── schemas.py       # Pydantic request/response
├── crud.py          # Operações de banco
├── aggregator.py    # Motor de agregação (Healthtech F17)
├── database.py      # SQLite / PostgreSQL + sessão
├── alembic/         # Migrações de schema
├── requirements.txt
├── .env.example
└── README.md
```

## Instalação

```bash
cd health-aggregator
pip install -r requirements.txt

# Dependências do Healthtech (para ingestão real + TCN)
pip install -r ../requirements.txt
```

## Execução

```bash
uvicorn main:app --reload --port 8000
# ou
python main.py
```

Documentação interativa: http://localhost:8000/docs

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |
| POST | `/ingest/` | Ingestão em lote (normaliza e salva) |
| GET | `/aggregate/daily/{user_id}` | Agregação diária (pandas + overall_score) |
| POST | `/records` | Criar registro único |
| GET | `/records/{user_id}` | Listar registros |
| POST | `/aggregate` | Pipeline Healthtech (wearables + FHIR + TCN) |
| GET | `/runs` | Histórico de agregações |

## Exemplo — agregação completa

```bash
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '[{
    "user_id": "user-123",
    "source": "apple",
    "timestamp": "2026-07-05T10:00:00",
    "steps": 8500,
    "heart_rate_bpm": 68,
    "spo2": 97.5
  }]'

curl -X POST http://localhost:8000/aggregate \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "PAT-APPLE-001",
    "sources": ["apple_health", "google_fit", "ble", "fhir", "tcn"],
    "sync_clinical": true,
    "run_prediction": true
  }'
```

## Fontes suportadas

| Source | Origem Healthtech |
|--------|-------------------|
| `apple_health` | `src/ingestion/real/apple_health.py` |
| `google_fit` | `src/ingestion/real/google_fit.py` |
| `ble` | `src/ingestion/real/ble_adapter.py` |
| `fhir` | `src/integrations/clinical/clinical_bridge.py` |
| `tcn` | `src/clinical_intelligence/temporal_model.py` |

## Banco de dados

PostgreSQL via `DATABASE_URL` no `.env` (veja `.env.example`):

```
postgresql://user:password@localhost/health_agg
```

### Migrações Alembic

```bash
cp .env.example .env
alembic upgrade head        # aplicar schema
alembic revision --autogenerate -m "descricao"  # nova migração
```