# Sprint A — Conectar e um vital (HR)

**Objetivo:** app companion pareia a HBand, lê **frequência cardíaca** e envia
`POST /api/v1/wearables/ingest` com `X-API-Key`. Critério de pronto: **HTTP 200**
da API full ou secure.

Contrato: [`docs/openapi/hband-wearable.yaml`](../docs/openapi/hband-wearable.yaml)  
Cliente HTTP: [`client/`](client/) (módulo Gradle `:client`)  
BLE: [`app/src/main/java/com/healthtech/companion/ble/`](app/src/main/java/com/healthtech/companion/ble/)

O módulo Gradle histórico `:sprint-a` (v3.1.0) foi unificado em `:app` + `:client`.
Os AARs Veepoo vivem em [`app/libs/`](app/libs/). `SprintAActivityNotes.kt` foi
removido (era só pseudo-código).

---

## Critério de pronto (DoD)

Legenda: **código** = implementado no repo; **device** = falta provar com pulseira
física / API real neste ambiente.

- [x] Demo/app **código**: AARs oficiais Veepoo em `app/libs/` (vpprotocol + vpbluetooth)
      e `implementation(fileTree("libs"))`. Assemble local ainda depende do Android SDK.
- [x] Scan BLE + connect + `confirmDevicePwd("0000")` + `syncPersonInfo` — **código**
      em `HbandProtocolClient` (UI lista MACs). **Device:** handshake num VE30/HBand.
- [x] `startDetectHeart` → callback BPM — **código** (`STATE_HEART_NORMAL` 20–250).
      **Device:** logcat/UI com pulseira no pulso.
- [x] Simulador BLE → ingest `ingest_source=ble_sim` → **200** (caminho HTTP; precisa API + key)
- [ ] `HbandSdkTransport` + AARs Veepoo → ingest `ingest_source=ble_hband` → **200**
      — **código** (`ingestLive` + `TelemetryDispatch`); **device** não exercitado aqui.
- [x] `HealthtechRepository.ingest` → **código** com `heart_rate` + `device_id` (`HBAND-{MAC}`)
- [x] 401/403 exibidos na UI (card dedicado + `AuthUiMessages`) — **código**;
      **device/API:** precisa chave inválida contra o server.
- [x] `patient_id` estável (`PAT-HBAND-001` em debug via BuildConfig / `local.properties`)

---

## Ordem de implementação (não paralelizar BLE)

```
Application
  └─ CompanionSession (dono único do HbandProtocolClient)
       └─ Ve30TelemetryService (foreground; mesmo session, sem 2º manager)
UI Scan
  └─ startScanDevice → lista MACs
  └─ connectDevice(mac)
       └─ bleNotifyResponse OK
            └─ confirmDevicePwd
                 └─ syncPersonInfo
                      └─ startDetectHeart
                           └─ onHeartData → TelemetryDispatch → Api.ingest
                      └─ (Sprint B) stopDetect* → readOriginData3 → batch-ingest → startDetectHeart
```

**Proibido:** chamar `startDetectHeart` e `readOriginData*` ao mesmo tempo.
O botão **Histórico flash** pausa a FC, lê OriginData3 e retoma.

---

## Mapa SDK → HTTP (mínimo Sprint A)

| SDK | JSON ingest |
|-----|-------------|
| `HeartData.data` (BPM) | `heart_rate` — só se 20–250; **sem default 72** |
| MAC do device | `device_id` (`HBAND-` + MAC; prefixo legado `VE30-` é reescrito) |
| ISO-8601 now | `timestamp` (opcional) |
| BuildConfig | `patient_id` (`PAT-HBAND-001` debug) |

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
4. Manifest: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, `INTERNET`; service Bluetooth do SDK
   + `Ve30TelemetryService` (`foregroundServiceType=connectedDevice`).

### A2 — Config e rede (sem BLE)

1. Cliente HTTP: módulo `:client` (`HealthtechRepository`), não o stub `HealthtechApiClient`.
2. Teste unitário/manual: POST com BPM fake → 200 (`Smoke 78`).
3. Simular chave errada → 401 e card vermelho na UI.

```bash
# validação server-side (monorepo)
python run_online_smoke.py --skip-vertex
```

### A3 — Conexão BLE (com device)

1. `HbandProtocolClient` com `VPOperateManager`.
2. UI: lista de scan + toque para conectar (não só o último MAC).
3. Fluxo serial: connect → pwd → personInfo → `startDetectHeart`.

### A4 — Heart detect + ingest

1. Após `onReady`, `startDetectHeart`.
2. No listener, debounce 3 s e `TelemetryDispatch.buildRealtime` (pula se não houver FC real).
3. Logar `response.code` e trecho do body (`anomaly_detection` no full).

### A5 — Hardening mínimo

1. Não logar API key.
2. Reconnect: `registerConnectStatusListener` + outbox para POST retryable.
3. Foreground service após ready; para no disconnect/destroy.
4. `stopAllSensors` para HR + SpO2 + temp + PA + HRV.

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

- SpO2 / temp / BP **em tempo real** (serial; hoje só OriginData3 no botão histórico)
- Outbox Room + WorkManager (hoje: fila em memória)
- PPG + BMO (Sprint C) — buffer ordenado já existe (`PpgBuffer`)
- LGPD unlink / secrets encrypted (Sprint D)

---

## Referências

- [HBandSDK Android_Ble_SDK](https://github.com/HBandSDK/Android_Ble_SDK)
- Demo: `OperaterActivity`, listeners de HR
- Backend tests: `tests/test_hband_normalizer.py`, `tests/test_wearable_api.py`
