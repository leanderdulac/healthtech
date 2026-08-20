# Caminho crítico vs laboratório

O repositório mistura um **produto operacional** (companion → ingest → alertas → dashboard)
com um **laboratório de pesquisa** (BMO, hemodinâmica 3D, RAG/USP, TCN Vertex).

CI leve e o app Android só precisam do caminho crítico. Módulos de laboratório
continuam no repo, mas não bloqueiam o produto.

## Caminho crítico (produto)

```
HBand ou simulador BLE
  → companion-android (client Retrofit + outbox)
  → POST /api/v1/wearables/ingest   (saude_responsiva_secure)
  → clinical_alerts (matriz de regras + FP)
  → GET /api/v1/connections/status
  → dashboard (painel de conexões)
```

| Superfície | Onde |
|------------|------|
| Contrato OpenAPI | `docs/openapi/hband-wearable.yaml` |
| Ingest + scopes | `saude_responsiva_secure/app/api/wearables.py` |
| Matriz clínica | `src/clinical_intelligence/alert_matrix_rules.py` |
| Status app/device | `saude_responsiva_secure/app/services/connection_status.py` |
| Companion | `companion-android/app` + `companion-android/client` |
| Dashboard conexões | `dashboard/index.html` + `dashboard/app.js` |
| Testes | `pytest -m critical` |
| Vendor da imagem secure | `python scripts/sync_secure_vendor.py` |

## Laboratório (não bloqueia o produto)

| Área | Entry / módulo | Marker pytest |
|------|----------------|---------------|
| TCN + Vertex serving | `run_vertex_deploy.py`, `tests/test_tcn_server.py` | `research` |
| BMO / VMO | `src/signal_processing/bmo_analysis.py` | `research` |
| Hemodinâmica 3D | `src/hemodynamics/` | `research` |
| Caos / fuzzy / ghost | `src/clinical_intelligence/pipeline.py` | `research` |
| RAG / Chroma / teses USP | `src/ml_pipeline/slm_search_engine.py`, `run_usp_scraper.py` | — |
| Ontologia FHIR USP | `src/ontology/` | — |

Pesos (`.pkl`, `.pt`, `.joblib`) e `data/chroma_db/` **não são versionados**.
Treine localmente (`run_alert_matrix_training.py`, `run_temporal_training.py`).
A matriz de alertas funciona só com regras se o classificador ML não estiver no disco.

## Como rodar

```bash
# produto (o que o CI exige)
pytest tests/ -m critical -v
cd saude_responsiva_secure && PYTHONPATH=. pytest test_security.py -v

# laboratório (opcional; TCN pula sem torch)
pytest tests/ -m research -v

# tudo que a suite leve cobre
pytest tests/ -v
```
