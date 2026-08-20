# One-pager — Arquitetura do Companion Mobile (HBand → Healthtech)

**Objetivo:** app Android que pareia pulseira **HBand/Veepoo** via BLE, coleta vitais e envia telemetria autenticada para a API Healthtech (Bronze + alertas).

**Critério de sucesso (MVP):** `startDetectHeart` → HTTP **200** em `POST /api/v1/wearables/ingest`.

**Client pronto:** módulo Gradle [`:client`](client/) + Postman em [`postman/`](postman/). Base debug: `http://10.0.2.2:8080`. Produção: `HEALTHTECH_BASE_URL` no `local.properties`.

| Fonte da verdade | Caminho / URL |
|------------------|---------------|
| Contrato OpenAPI | [`docs/openapi/hband-wearable.yaml`](../docs/openapi/hband-wearable.yaml) |
| Checklist detalhado | [`docs/HBAND_COMPANION_CHECKLIST.md`](../docs/HBAND_COMPANION_CHECKLIST.md) |
| Sprint A (tarefas) | [`SPRINT_A.md`](SPRINT_A.md) |
| Stubs Kotlin | [`sprint-a/`](sprint-a/) |
| SDK BLE | [HBandSDK/Android_Ble_SDK](https://github.com/HBandSDK/Android_Ble_SDK) |

---

## 1. Ambientes e base URLs

| Env | Base URL | Quando usar |
|-----|----------|-------------|
| **Secure (prod mobile)** | `HEALTHTECH_BASE_URL` no `local.properties` | App em produção / QA — enxuto, scopes, rate limit |
| **Full (opcional)** | URL do serviço `APP_MODE=full` | Só se precisar dashboard/WS/`anomaly_detection` no response |
| **Local (emulador)** | `http://10.0.2.2:8080` | Dev com API no host |
| **Local (device físico)** | `http://<IP-LAN-do-PC>:8080` | Dev com telefone na mesma rede |

**Probe público (sem auth):**

```http
GET {BASE_URL}/api/health
```

BuildConfig / `local.properties` (nunca commitar a chave):

```properties
HEALTHTECH_BASE_URL=http://10.0.2.2:8080
HEALTHTECH_INGEST_API_KEY=
HEALTHTECH_PATIENT_ID=PAT-HBAND-001
```

---

## 2. Diagrama de fluxo (visão única)

```
┌─────────────┐   BLE    ┌──────────────────┐
│  HBand /    │◄────────►│  Companion App   │
│  Veepoo     │          │  (Android)       │
└─────────────┘          └────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              ┌─────────┐  ┌──────────┐  ┌────────────┐
              │ UI      │  │ Outbox   │  │ ApiClient  │
              │ telas   │  │ (Room)   │  │ OkHttp     │
              └─────────┘  └────┬─────┘  └─────┬──────┘
                                │ flush        │ HTTPS
                                └──────┬───────┘
                                       ▼
                    ┌──────────────────────────────────┐
                    │  Cloud Run Secure API            │
                    │  X-API-Key → wearables:write     │
                    │  /api/v1/wearables/*             │
                    │  /api/v1/signal/* (Sprint C)     │
                    └──────────────────────────────────┘
                                       │
                                       ▼
                              Bronze / alertas / FHIR
```

**Regra BLE:** sequência **serial** — nunca `startDetectHeart` e `readOriginData*` em paralelo.

```
init → scan → connect → bleNotify OK → confirmDevicePwd("0000")
     → syncPersonInfo → (ready) → detect vitals | history sync
```

---

## 3. Telas (IA / navegação)

| Tela | Sprint | Responsabilidade |
|------|--------|------------------|
| **Onboarding / Consentimento** | D (mínimo em A: stub) | LGPD: o que é coletado, para onde vai, revogar |
| **Scan** | A | Lista BLE, permissões Android 12+, conectar MAC |
| **Pairing / Ready** | A | pwd + personInfo; mostra `device_id` = `HBAND-{MAC}` |
| **Live vitals** | A–C | HR (A); + SpO2/temp/BP (B); + PPG buffer (C) |
| **Sync status** | B | Fila outbox, último HTTP code, contagem pendente/falha |
| **Histórico local** | B | Últimas N leituras (Room) + “forçar sync” |
| **Settings** | D | Base URL (debug), patient_id, desparear, purge local |
| **Erro auth** | A | 401/403 amigável — chave/escopo sem logar a key |

Fluxo feliz Sprint A:

```
Scan → Pairing → Live vitals (HR) → badge “enviado 200”
                    └─ falha rede → outbox (B) / toast (A)
```

---

## 4. Módulos do app

```
app/
├── ble/
│   ├── HbandConnectionManager   # scan/connect/pwd/personInfo/reconnect
│   ├── HbandRealtimeCollector   # HR / SpO2 / temp / BP / PPG
│   └── HbandHistorySync         # OriginData3, sleep, sport (B)
├── net/
│   ├── HealthtechApiClient      # OkHttp + timeouts + X-API-Key
│   └── Dtos                     # espelha OpenAPI (WearableIngestRequest…)
├── queue/
│   ├── OutboxStore              # Room: pending → sending → sent | dead
│   └── OutboxWorker             # WorkManager: flush batch sob rede
├── domain/
│   ├── PatientSession           # patient_id estável
│   └── DeviceProfile            # MAC, firmware, origin_protocol_version
├── security/
│   └── SecretStore              # EncryptedSharedPreferences / Keystore
└── ui/
    ├── ScanScreen
    ├── LiveVitalsScreen
    └── SyncStatusScreen
```

Stubs já no repo: `sprint-a/.../ble/*`, `net/HealthtechApiClient.kt`, `net/Dtos.kt`.

---

## 5. Auth e segurança

| Item | Decisão |
|------|---------|
| Esquema | Header `X-API-Key` (não Bearer JWT no MVP) |
| Escopo ingest | `wearables:write` (`INGEST_API_KEY`) |
| Escopo leitura | `wearables:read` (latest/history — se o app mostrar servidor) |
| Admin / LGPD server | `admin` — **não** no app do paciente; backend/ops |
| Onde guardar key | Encrypted prefs / secrets CI; **nunca** git, logcat ou analytics |
| patient_id | Estável por usuário (`PAT-…`); padrão debug `PAT-HBAND-001` |
| TLS | Só HTTPS em prod; certificate pinning opcional no D |
| Anti-vazamento | Mascarar key em logs; não anexar body com PII em crash reports |

```http
X-API-Key: <INGEST_API_KEY>
Content-Type: application/json
```

| HTTP | Significado no app |
|------|--------------------|
| 200 | OK — marcar outbox sent |
| 401 | Chave ausente/inválida → tela reconfigurar |
| 403 | Escopo insuficiente |
| 422 | Payload inválido — **não** reenviar sem corrigir (dead letter) |
| 429 | Rate limit — backoff exponencial |
| 5xx / rede | Retry com jitter; manter na outbox |

---

## 6. Endpoints por sprint

### Sprint A — Conectar + 1 vital (HR)

| Método | Path | Auth | Uso no app |
|--------|------|------|------------|
| GET | `/api/health` | público | Smoke na abertura / settings |
| POST | `/api/v1/wearables/ingest` | write | Cada HR (debounce 2–5 s) |

Body mínimo:

```json
{
  "patient_id": "PAT-HBAND-001",
  "device_id": "HBAND-AA:BB:CC:DD:EE:FF",
  "heart_rate": 78.0,
  "filter_type": "BMO",
  "timestamp": "2026-08-09T18:00:00Z"
}
```

DoD: HTTP 200 com device físico ou stub SDK + API secure.

### Sprint B — Multi-métrica + offline + histórico

| Método | Path | Auth | Uso |
|--------|------|------|-----|
| POST | `/api/v1/wearables/ingest` | write | SpO2, temp, BP (campos no mesmo schema) |
| POST | `/api/v1/wearables/batch-ingest` | write | Flush outbox / OriginData3 (≤ 200 readings) |
| GET | `/api/v1/wearables/patient/{id}/latest` | read | Tela “última no servidor” (opcional) |
| GET | `/api/v1/wearables/patient/{id}/history` | read | Comparar local vs servidor (opcional) |

SDK serial: SpO2/temp/BP **depois** de ready; OriginData em janela sem detect realtime.

### Sprint C — PPG / sinal

| Método | Path | Auth | Uso |
|--------|------|------|-----|
| POST | `/api/v1/wearables/ingest` | write | `ppg_signal` + vitais |
| POST | `/api/v1/signal/bmo-analysis` | read | Buffer ~2–8 s green light (~25 Hz); **sem** patient se só análise |

### Sprint D — Produção / LGPD

| Método | Path | Auth | Uso |
|--------|------|------|-----|
| DELETE | `/api/v1/patient/{id}/anonymize` | admin | **Não** no app paciente; fluxo ops ou backend com consent |
| — | Unlink local | — | Apagar Room, desparear BLE, limpar prefs |
| — | Consentimento | — | UI + flag local + (futuro) audit server |

---

## 7. Fila offline (Outbox)

```
Evento BLE / sample
       │
       ▼
  Validar ranges (HR 20–250, SpO2 50–100, …)
       │
       ▼
  INSERT outbox (status=pending, payload JSON, created_at)
       │
       ▼
  WorkManager (rede OK + backoff)
       │
       ├─ 1 item  → POST /ingest
       └─ N items → POST /batch-ingest (chunks ≤ 200)
       │
       ├─ 200 → status=sent
       ├─ 422 → status=dead + motivo (não loop)
       └─ rede/5xx/429 → pending + next_attempt_at
```

Políticas:

| Política | Valor sugerido |
|----------|----------------|
| Debounce realtime | 2–5 s por tipo de vital |
| Chunk batch | 50–200 readings |
| Retries | 5–10 com expo backoff (cap 15 min) |
| Dead letter | UI em Sync status + export JSON debug |
| Reconnect BLE | `registerConnectStatusListener` + 1 POST pendente em memória (A) / Room (B) |
| Ordem | FIFO por `timestamp` do sample |

---

## 8. Mapeamento SDK → JSON (resumo)

| SDK | Campo API / envelope |
|-----|----------------------|
| `HeartData.data` | `heart_rate` |
| SpO2 listener | `spo2` |
| Temp listener | `skin_temp` |
| BP high/low | normalizer / raw (Bronze) |
| MAC | `device_id` = `HBAND-{MAC}` |
| Green light PPG | `ppg_signal` |
| OriginData3 5 min | batch `readings[]` ou envelope `origin_batch` |
| Sleep / sport | `sleep_batch` / `sport_snapshot` (normalizer) |
| Pós-pwd caps | `device_capabilities` (uma vez) |

Detalhe completo: checklist §3 + OpenAPI schemas `HBandRealtimeIngestApi`, `WearableBatchIngest`.

---

## 9. Estados e erros (máquina mínima)

```
App:  Idle → Scanning → Connecting → Ready → Measuring → (background sync)
BLE:  Disconnected → Connecting → Connected → Authenticated → Streaming
Net:  Online | Offline | Degraded (429/5xx)
Auth: Valid | MissingKey | Forbidden
```

UI deve sempre mostrar: estado BLE + contagem outbox + último código HTTP.

---

## 10. Roadmap e DoD por sprint

| Sprint | Entrega | DoD |
|--------|---------|-----|
| **A** | Parear + HR + POST ingest | 200 na API secure; 401/403 na UI |
| **B** | SpO2/temp + Room outbox + batch + OriginData dia 0 | Sync após airplane mode; Bronze ok em teste |
| **C** | PPG buffer + opcional BMO | `ppg_signal` aceito; análise opcional 200 |
| **D** | Secrets, consent, unlink, multi-firmware | Key criptografada; checklist prod; 2+ SKUs |

Fora do MVP: OTA/DFU, watch face, ECG (se SKU), WebSocket full.

---

## 11. Checklist rápido de planejamento (PO / eng)

- [ ] Escolher **secure** como base URL default do app
- [ ] Provisionar `INGEST_API_KEY` (e opcional read key) no Secret Manager / CI
- [ ] Definir `patient_id` por conta (hoje: fixo debug)
- [ ] Importar AARs Veepoo + permissões BLE 12+
- [ ] Implementar Sprint A sobre stubs `companion-android/sprint-a`
- [ ] Smoke: `GET /api/health` + `POST .../ingest` com curl antes do device
- [ ] Política offline (B) antes de piloto de campo
- [ ] Texto LGPD + fluxo unlink antes de store/piloto clínico

---

## 12. Smoke sem device (copiar/colar)

```bash
export BASE=https://healthtech-secure-api-5794833455.us-central1.run.app
export INGEST_API_KEY=...   # mesma do Cloud Run

curl -sS "$BASE/api/health"

curl -sS -X POST "$BASE/api/v1/wearables/ingest" \
  -H "X-API-Key: $INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id":"PAT-HBAND-001",
    "device_id":"HBAND-SMOKE",
    "heart_rate":78,
    "filter_type":"BMO"
  }'
```

No monorepo: `python run_online_smoke.py --skip-vertex --also-secure`.

---

## 13. Decisões fixas (para não reabrir discussão)

1. **API mobile = Secure Cloud Run**, não o monólito full.
2. **Contrato = OpenAPI HBand**; DTOs Kotlin alinhados a `HBandRealtimeIngestApi`.
3. **Auth = API key no header**; JWT/OAuth fica para uma v2 de conta de paciente.
4. **Offline-first a partir do B**; A pode ser best-effort + toast.
5. **BLE serializado**; outbox desacopla rede do stack BLE.
6. **Admin/anonymize fora do app do usuário final.**

---

*Documento de planejamento. Implementação detalhada: `SPRINT_A.md` + `docs/HBAND_COMPANION_CHECKLIST.md`.*
