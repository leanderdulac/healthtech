# Health Aggregator

API REST que agrega telemetria wearable, dados clínicos FHIR e predições TCN do projeto Healthtech em uma visão unificada por paciente.

## Estrutura

```
health-aggregator/
├── main.py          # FastAPI — endpoints REST
├── models.py        # SQLAlchemy ORM
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
uvicorn main:app --reload --port 8090
```

Documentação interativa: http://localhost:8090/docs

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |
| GET/POST | `/patients` | Listar / criar pacientes |
| GET | `/patients/{id}/summary` | Visão unificada (telemetria + clínico + TCN) |
| GET | `/patients/{id}/telemetry` | Leituras agregadas |
| GET | `/patients/{id}/clinical` | Último snapshot FHIR |
| GET | `/patients/{id}/prediction` | Última predição TCN |
| POST | `/aggregate` | Executar agregação multi-fonte |
| GET | `/runs` | Histórico de agregações |

## Exemplo — agregação completa

```bash
curl -X POST http://localhost:8090/aggregate \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "PAT-APPLE-001",
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