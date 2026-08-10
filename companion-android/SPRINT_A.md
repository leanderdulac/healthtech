# Sprint A — Conectar e um vital (HR)

**Objetivo:** app companion pareia a HBand, lê **frequência cardíaca** e envia
`POST /api/v1/wearables/ingest` com `X-API-Key`. Critério de pronto: **HTTP 200**
da API full ou secure.

Contrato: [`docs/openapi/hband-wearable.yaml`](../docs/openapi/hband-wearable.yaml)  
Stubs: [`sprint-a/`](sprint-a/)

---

## Critério de pronto (DoD)

- [ ] Demo/app compila com AARs oficiais Veepoo
- [ ] Scan BLE + connect + `confirmDevicePwd("0000")` + `syncPersonInfo`
- [ ] `startDetectHeart` → callback com BPM no logcat
- [ ] `HealthtechApiClient.ingestRealtime` → **200** com `heart_rate` + `device_id`
- [ ] 401/403 exibidos na UI (chave inválida / escopo)
- [ ] `patient_id` estável (`PAT-HBAND-001` em debug)

---

## Ordem de implementação (não paralelizar BLE)

```
Application
  └─ HbandConnectionManager.init()
UI Scan
  └─ startScanDevice → lista MACs
  └─ connectDevice(mac)
       └─ bleNotifyResponse OK
            └─ confirmDevicePwd
                 └─ syncPersonInfo
                      └─ startDetectHeart
                           └─ onHeartData → ApiClient.ingest
```

**Proibido:** chamar `startDetectHeart` e `readOriginData*` ao mesmo tempo.

---

## Mapa SDK → HTTP (mínimo Sprint A)

| SDK | JSON ingest |
|-----|-------------|
| `HeartData.data` (BPM) | `heart_rate` |
| MAC do device | `device_id` (`HBAND-` + MAC) |
| ISO-8601 now | `timestamp` (opcional) |
| BuildConfig | `patient_id` |

Headers:

```http
X-API-Key: <INGEST_API_KEY>
Content-Type: application/json
```

Exemplo body:

```json
{
  "patient_id": "PAT-HBAND-001",
  "device_id": "HBAND-AA:BB:CC:DD:EE:FF",
  "heart_rate": 78.0,
  "filter_type": "BMO",
  "timestamp": "2026-08-09T18:00:00Z"
}
```

---

## Tarefas detalhadas

### A1 — Projeto e AARs

1. Android Studio → Empty Activity, `minSdk 26`, `targetSdk 34`, Kotlin.
2. Copiar AARs do HBandSDK (`vpbluetooth`, `vpprotocol`, gson, …) para `app/libs/`.
3. `implementation(fileTree("libs") { include("*.aar", "*.jar") })`.
4. Manifest: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, `INTERNET`; service Bluetooth do SDK.

### A2 — Config e rede (sem BLE)

1. Implementar `HealthtechApiClient` (stub em `sprint-a/.../net/`).
2. Teste unitário/manual: POST com BPM fake → 200.
3. Simular chave errada → 401 e mensagem na UI.

```bash
# validação server-side (monorepo)
python run_online_smoke.py --skip-vertex
```

### A3 — Conexão BLE (com device)

1. Preencher `HbandConnectionManager` com `VPOperateManager` (ver comentários no stub).
2. UI: lista de scan + botão Conectar.
3. Fluxo serial: connect → pwd → personInfo → cache de `FunctionDeviceSupportData`.

### A4 — Heart detect + ingest

1. `HbandRealtimeCollector.startHeart()`.
2. No listener, debounce 2–5 s e chamar `api.ingestRealtime(...)`.
3. Logar `response.code` e trecho do body (`anomaly_detection` no full).

### A5 — Hardening mínimo

1. Não logar API key.
2. Reconnect: `registerConnectStatusListener` + fila de 1 POST pendente.
3. Documentar SKU/firmware testado no PR.

---

## Ambientes

| Env | Base URL |
|-----|----------|
| full (prod) | `https://healthtech-responsive-5794833455.us-central1.run.app` |
| secure | `https://healthtech-secure-api-5794833455.us-central1.run.app` |
| local | `http://10.0.2.2:8080` (emulador → host) |

Chave de ingestão: use a mesma `INGEST_API_KEY` do Cloud Run (Secret Manager /
variável de ambiente). **Nunca** commite chaves no repositório.

---

## Fora do Sprint A (próximos)

- SpO2 / temp / BP (Sprint B)
- OriginData3 batch + outbox Room (Sprint B)
- PPG + BMO (Sprint C)
- LGPD unlink / secrets encrypted (Sprint D)

---

## Referências

- [HBandSDK Android_Ble_SDK](https://github.com/HBandSDK/Android_Ble_SDK)
- Demo: `OperaterActivity`, listeners de HR
- Backend tests: `tests/test_hband_normalizer.py`, `tests/test_wearable_api.py`
