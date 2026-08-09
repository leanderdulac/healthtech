# Companion Android HBand → Healthtech

Esqueleto e guias para o app companion que fala com a pulseira **HBand/Veepoo**
via BLE e envia telemetria para a API Healthtech.

| Doc | Conteúdo |
|-----|----------|
| [`SPRINT_A.md`](SPRINT_A.md) | Sprint A — conectar + 1 vital (HR) + POST ingest |
| [`docs/HBAND_COMPANION_CHECKLIST.md`](../docs/HBAND_COMPANION_CHECKLIST.md) | Checklist completo (backend ready) |
| [`docs/openapi/hband-wearable.yaml`](../docs/openapi/hband-wearable.yaml) | Contrato OpenAPI |

## Status

| Camada | Status |
|--------|--------|
| Backend API (ingest, alertas, auth) | ✅ pronto em Cloud Run |
| Contrato OpenAPI + normalizer Python | ✅ |
| Stubs Kotlin Sprint A (este diretório) | ✅ esboço |
| Integração AARs Veepoo / device físico | ⬜ depende do SDK + hardware |

## Como usar este esboço

1. Crie um projeto Android (API 31+, Kotlin) no Android Studio.
2. Copie `sprint-a/src/main/java/com/healthtech/companion/**` para o módulo `app`.
3. Coloque os AARs oficiais em `app/libs/` (veja checklist).
4. Configure `local.properties` ou `BuildConfig`:

```properties
HEALTHTECH_BASE_URL=https://healthtech-responsive-5794833455.us-central1.run.app
HEALTHTECH_INGEST_API_KEY=ht_ingest_live_key_2026_safe_token_32c
HEALTHTECH_PATIENT_ID=PAT-HBAND-001
```

5. Siga [`SPRINT_A.md`](SPRINT_A.md) tarefa a tarefa.

## Smoke da API (sem device)

```bash
# a partir da raiz do monorepo
python run_online_smoke.py --skip-vertex
curl -sS -X POST "$CLOUD_RUN_URL/api/v1/wearables/ingest" \
  -H "X-API-Key: $INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"PAT-HBAND-001","device_id":"HBAND-SMOKE","heart_rate":78}'
```
