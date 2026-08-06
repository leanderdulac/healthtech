# Saúde Responsiva Secure API

API FastAPI endurecida para telemetria de wearables, análise de sinais (BMO/HRV) e operações admin, com foco em **segurança, escopos e conformidade LGPD**.

Pacote autocontido extraído/refatorado a partir do monólito `src/api_server.py` + `src/security/*`.

## Estrutura

```
saude_responsiva_secure/
├── app/
│   ├── main.py                 # App factory + middlewares + exception handlers
│   ├── config.py               # Settings (pydantic-settings)
│   ├── security/
│   │   ├── auth.py             # API Keys + scopes + autorização por paciente
│   │   ├── rate_limit.py       # slowapi
│   │   └── headers.py          # Security Headers middleware
│   ├── api/
│   │   ├── health.py
│   │   ├── wearables.py        # ingest / batch / latest / history
│   │   ├── signal.py           # BMO analysis / denoise / HRV
│   │   ├── admin.py            # search + reindex
│   │   └── lgpd.py             # purge / anonymize
│   ├── models/schemas.py
│   └── services/
│       ├── audit.py
│       ├── telemetry_store.py
│       └── signal_core.py
├── requirements.txt
├── Dockerfile
├── .env.example
├── test_security.py
└── README.md
```

## Controles de segurança

| Controle | Implementação |
|----------|---------------|
| Autenticação | Header `X-API-Key` com `hmac.compare_digest` (sem prefix matching) |
| Autorização | Escopos `wearables:write`, `wearables:read`, `admin` |
| Anti-IDOR | `ALLOWED_PATIENT_IDS` + `require_patient_access` |
| Rate limit | [slowapi](https://github.com/laurentS/slowapi) por chave/IP |
| Headers | HSTS, CSP, nosniff, X-Frame-Options, Referrer-Policy |
| Auditoria | Middleware JSON com `X-Request-ID` e chave mascarada |
| Validação | Pydantic v2 (limites fisiológicos, patient_id sanitizado) |
| LGPD | `DELETE /api/v1/patient/{id}/anonymize` (admin) |
| Docs | `/docs` e `/redoc` desabilitados em production |

## Instalação

```bash
cd saude_responsiva_secure
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edite SECRET_SALT, API_KEY / INGEST_API_KEY / READ_API_KEY
```

## Execução

```bash
# a partir de saude_responsiva_secure/
export PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Docker:

```bash
docker build -t saude-responsiva-secure .
docker run --rm -p 8080:8080 \
  -e ENVIRONMENT=production \
  -e SECRET_SALT="$(openssl rand -hex 32)" \
  -e API_KEY="$(openssl rand -hex 32)" \
  saude-responsiva-secure
```

## Endpoints principais

| Método | Path | Escopo |
|--------|------|--------|
| GET | `/api/health` | público |
| GET | `/api/status` | `admin` |
| POST | `/api/v1/wearables/ingest` | `wearables:write` |
| POST | `/api/v1/wearables/batch-ingest` | `wearables:write` |
| GET | `/api/v1/wearables/patient/{id}/latest` | `wearables:read` + paciente |
| GET | `/api/v1/wearables/patient/{id}/history` | `wearables:read` + paciente |
| POST | `/api/v1/signal/bmo-analysis` | `wearables:read` |
| POST | `/api/v1/signal/bmo-denoise` | `wearables:write` |
| POST | `/api/v1/signal/hrv/bmo-metrics` | `wearables:read` |
| POST | `/api/search` | `wearables:read` |
| POST | `/api/v1/admin/reindex` | `admin` |
| DELETE | `/api/v1/patient/{id}/anonymize` | `admin` |

### Exemplo de ingestão

```bash
curl -s -X POST http://localhost:8080/api/v1/wearables/ingest \
  -H "X-API-Key: $INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"PAT-001","heart_rate":78.0,"hrv_rmssd":42.0,"spo2":98.0}'
```

## Testes

```bash
cd saude_responsiva_secure
pip install pytest httpx
PYTHONPATH=. pytest test_security.py -v
```

Chaves de teste embutidas (somente `ENVIRONMENT=development`):

- `ht_ingest_test_key_32chars_long_token` → write  
- `ht_read_test_key_32chars_long_token` → read  
- `ht_admin_test_key_32chars_long_token` → admin  

## Relação com o monólito

| Este pacote | Monólito |
|-------------|----------|
| `app/main.create_app` | factory única (`APP_MODE=secure\|full`) |
| `app/security/*` | middlewares preferidos no full; `src/security/*` fallback |
| `app/api/*` | rotas enxutas (modo secure) |
| `src/api_monolith_runtime.py` | dashboard + WS + phantom (modo full) |
| `src/api_server.py` | entry thin → factory com `APP_MODE=full` |

```bash
# Secure (este diretório)
APP_MODE=secure uvicorn app.main:app --port 8080

# Full (repo raiz)
uvicorn src.api_server:app --port 8080

# Deploy
APP_MODE=secure ../deploy_to_gcp.sh   # serviço healthtech-secure-api
APP_MODE=full   ../deploy_to_gcp.sh   # serviço healthtech-responsive
```

## Variáveis de ambiente

Veja [`.env.example`](.env.example). Em **production**:

1. `AUTH_DISABLED` é ignorado se `true`
2. `SECRET_SALT` fraco aborta o startup
3. API keys fracas/curtas abortam o startup
4. CORS com `*` é rejeitado
