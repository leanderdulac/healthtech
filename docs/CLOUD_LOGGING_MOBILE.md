# Cloud Logging — tráfego do companion Android

Projeto: **`healthtech-gcp-2026`** · Região: **`us-central1`** · Serviço: **`healthtech-secure-api`**

## Console (abrir com filtro)

[Logs Explorer — mobile okhttp + wearables](https://console.cloud.google.com/logs/query;query=resource.type%3D%22cloud_run_revision%22%0Aresource.labels.service_name%3D%22healthtech-secure-api%22%0A%28httpRequest.userAgent%3A%22okhttp%22%20OR%20textPayload%3A%22okhttp%22%20OR%20httpRequest.requestUrl%3A%22wearables%22%29;project=healthtech-gcp-2026)

## Filtros prontos (colar no Logs Explorer)

### 1) Todo tráfego do app mobile (OkHttp)

```text
resource.type="cloud_run_revision"
resource.labels.service_name="healthtech-secure-api"
(
  httpRequest.userAgent:"okhttp"
  OR textPayload:"okhttp"
)
```

### 2) Só ingest de wearables

```text
resource.type="cloud_run_revision"
resource.labels.service_name="healthtech-secure-api"
(
  httpRequest.requestUrl:"/api/v1/wearables/ingest"
  OR textPayload:"/api/v1/wearables/ingest"
)
```

### 3) Rate limit 429 (outbox / rajadas)

```text
resource.type="cloud_run_revision"
resource.labels.service_name="healthtech-secure-api"
httpRequest.status=429
```

### 4) Auditoria da API (chave mascarada + path)

```text
resource.type="cloud_run_revision"
resource.labels.service_name="healthtech-secure-api"
textPayload:"api_access_audit"
```

### 5) Falhas de clinical_alerts / import

```text
resource.type="cloud_run_revision"
resource.labels.service_name="healthtech-secure-api"
(
  textPayload:"No module named"
  OR textPayload:"clinical_alerts"
  OR textPayload:"unavailable"
)
```

## CLI (`gcloud`)

```bash
# Últimas requisições do app
gcloud logging read \
  'resource.type="cloud_run_revision"
   resource.labels.service_name="healthtech-secure-api"
   httpRequest.userAgent:"okhttp"' \
  --project=healthtech-gcp-2026 \
  --limit=50 \
  --freshness=1d \
  --format='table(timestamp,httpRequest.requestMethod,httpRequest.status,httpRequest.requestUrl,httpRequest.latency)'

# Contagem de 429 na última hora
gcloud logging read \
  'resource.type="cloud_run_revision"
   resource.labels.service_name="healthtech-secure-api"
   httpRequest.status=429' \
  --project=healthtech-gcp-2026 \
  --limit=500 \
  --freshness=1h \
  --format='value(timestamp)' | wc -l
```

## O que o app envia (contrato)

| Item | Valor |
|------|--------|
| Base URL | `https://healthtech-secure-api-5794833455.us-central1.run.app` |
| Ingest | `POST /api/v1/wearables/ingest` |
| Health | `GET /api/health` |
| Auth | header `X-API-Key` = `INGEST_API_KEY` |
| User-Agent | `okhttp/4.12.0` |
| Patient típico | `PAT-HBAND-001` |
| Device típico | `HBAND-B57-89A4` |

## Rate limit (por quê 429?)

- Middleware: `PathRateLimitMiddleware` em `saude_responsiva_secure/app/security/rate_limit.py`
- Chave: `X-API-Key` (prefixo) **ou** IP
- Path `/api/v1/wearables/ingest`: **`RATE_LIMIT_INGEST`** (default atual **300/minute**)
- Streaming ~1 amostra / 4 s ≈ 15/min → bem abaixo do teto
- **429 aparece em rajadas** (flush de outbox com dezenas de `POST /ingest` em segundos, ou vários clientes com a mesma chave)

Mitigações no cliente:

1. Preferir `POST /api/v1/wearables/batch-ingest` no flush da outbox
2. Respeitar header `Retry-After` / corpo `retry_after_seconds`
3. Backoff exponencial em HTTP 429

## Verificar telemetria gravada

```bash
export BASE=https://healthtech-secure-api-5794833455.us-central1.run.app
export READ_API_KEY=...   # READ_API_KEY de produção

curl -sS -H "X-API-Key: $READ_API_KEY" \
  "$BASE/api/v1/wearables/patient/PAT-HBAND-001/latest" | jq .
```
