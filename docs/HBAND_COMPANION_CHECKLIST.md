# Checklist: Companion Android HBand → Healthtech

Guia prático para copiar/adaptar o demo **VpBluetoothSDK** do repositório
[HBandSDK/Android_Ble_SDK](https://github.com/HBandSDK/Android_Ble_SDK) e enviar
telemetria para a API Healthtech.

Contrato OpenAPI: [`docs/openapi/hband-wearable.yaml`](openapi/hband-wearable.yaml)  
Normalizer Python: `src/ingestion/real/hband_normalizer.py`  
Schemas: `src/ingestion/real/hband_schemas.py`

---

## Status do backend (repo)

O lado **servidor** já está pronto para o companion. O trabalho restante é o app Android.

| Capacidade backend | Status | Onde |
|--------------------|--------|------|
| Contrato OpenAPI HBand/Veepoo | ✅ | `docs/openapi/hband-wearable.yaml` |
| Normalizer + adapter Bronze | ✅ | `src/ingestion/real/hband_*` |
| Registry fonte `hband` | ✅ | ingestão real |
| `POST /api/v1/wearables/ingest` + matriz de alertas | ✅ | monólito + `saude_responsiva_secure` |
| Auth `X-API-Key` / scopes | ✅ | F19 + secure factory |
| Testes de contrato normalizer | ✅ | `tests/test_hband_normalizer.py` |
| App companion (BLE → HTTP) | ⬜ pendente | este checklist (sprints A–D) |
| Esboço Sprint A (Kotlin stubs) | ✅ | [`companion-android/`](../companion-android/) |
| Device físico + AARs | ⬜ pendente | hardware / SDK fabricante |

---

## 0. Pré-requisitos

| Item | Status |
|------|--------|
| Android Studio + SDK API 19+ (target 31+) | ☐ |
| Kotlin plugin (SDK ≥ 2.1.38.15) | ☐ |
| AARs em `libs/`: vpprotocol, vpbluetooth, gson, JL_*, abpartool | ☐ |
| Nordic mcumgr + scanner (Gradle) | ☐ |
| Device HBand/Veepoo físico ou empréstimo do fabricante | ☐ |
| `INGEST_API_KEY` e URL da API (secure ou full) | ☐ backend ready; preencher no app |
| `patient_id` estável por usuário (ex.: `PAT-HBAND-001`) | ☐ |

---

## 1. Activities do demo a reutilizar

Caminho base no SDK:

`android_sdk_source/Demo/VpBluetoothSDK/app/src/main/java/com/timaimee/vpdemo/activity/`

| Prioridade | Activity / classe | Função no companion | Checklist |
|------------|-------------------|---------------------|-----------|
| **P0** | `MainActivity` | Scan BLE, permissões (Android 12+), `connectDevice` | ☐ Copiar fluxo de permissões |
| **P0** | `OperaterActivity` | Hub: `confirmDevicePwd`, `syncPersonInfo`, medições | ☐ Extrair só o necessário |
| **P0** | `Oprate.java` | Constantes de operação (HR/BP/SpO2/temp) | ☐ Referência de strings |
| **P0** | Listeners em `OperaterActivity` (HR/SpO2/temp/BP) | → JSON `realtime_ingest` | ☐ Mapear para OpenAPI |
| **P1** | `OriginalDataLogActivity` | `readOriginData*` / OriginData3 5 min | ☐ Sync batch diário |
| **P1** | Sleep via `OperaterActivity` / `readSleepData` | → `sleep_batch` | ☐ |
| **P1** | `readSportStep` | → `sport_snapshot` | ☐ |
| **P2** | `JH58PPGOptTestActivity` | PPG MODE1/2 + realtime green light | ☐ `ppg_stream` + BMO |
| **P2** | `EcgDetectActivity` | ECG (se SKU suportar) | ☐ Opcional |
| **P3** | `OadActivity` / DFU | OTA firmware | ☐ Fora do MVP clínico |
| **P3** | `UiUpdateCustomActivity` / Server dial | Watch face | ☐ Não necessário |
| **P3** | `TextImagePushActivity` / alarmes | UX device | ☐ Fora do MVP |

### Dependências de service no Manifest (do README HBand)

```xml
<service android:name="com.inuker.bluetooth.library.BluetoothService" />
<!-- OTA opcional -->
```

Permissões: `BLUETOOTH_*` (API 31+), location se API ≤ 30, `INTERNET` (upload API).

---

## 2. Sequência obrigatória de conexão

Implementar **nesta ordem** (serializado — sem paralelo):

| # | SDK | Companion | ☐ |
|---|-----|-----------|---|
| 1 | `VPOperateManager.getMangerInstance(appContext)` | Init em `Application` | ☐ |
| 2 | `startScanDevice()` | UI lista devices | ☐ |
| 3 | `connectDevice(mac, …)` | Aguardar connect | ☐ |
| 4 | `bleNotifyResponse` OK | Só então seguir | ☐ |
| 5 | `confirmDevicePwd("0000", …)` | Guardar `FunctionDeviceSupportData` | ☐ |
| 6 | `syncPersonInfo(height, weight, age, sex)` | Calorias/passos corretos | ☐ |
| 7 | Cache `originProtocolVersion`, `watchday` | Enviar em `device` do envelope | ☐ |
| 8 | `registerConnectStatusListener` | Reconnect + flush fila | ☐ |

**Não** chamar `startDetectHeart` e `readOriginData` ao mesmo tempo.

---

## 3. Mapeamento SDK → HTTP

### 3.1 Realtime → `POST /api/v1/wearables/ingest`

| Listener / campo SDK | JSON API |
|----------------------|----------|
| `IHeartDataListener` → `HeartData.data` | `heart_rate` |
| `ISpo2hDataListener` → `value` | `spo2` |
| `ITemptureDetectDataListener` → current/base | `skin_temp` |
| `IBPDetectDataListener` → high/low | Bronze via normalizer (`blood_pressure_*`); opcional no body |
| `onGreenLightDataReport` | `ppg_signal` |
| MAC / serial | `device_id` (prefixo `HBAND-` recomendado) |
| ISO now | `timestamp` |

Headers:

```http
X-API-Key: <INGEST_API_KEY>
Content-Type: application/json
```

### 3.2 Histórico → batch ou arquivo + adaptador

| SDK | Envelope `message_type` | Backend |
|-----|-------------------------|---------|
| `IOriginData3Listener.onOriginFiveMinuteListDataChange` | `origin_batch` | `HBandNormalizer.from_origin_batch` |
| `ISleepDataListener` | `sleep_batch` | `from_sleep_batch` |
| `ISportDataListener` | `sport_snapshot` | `from_sport` |
| PPG raw history | `ppg_raw_history` / stream | `from_ppg_stream` + BMO |

Arquivos offline (debug): JSON/JSONL em `HBAND_PAYLOAD_PATH` → `HBandCompanionAdapter`.

### 3.3 Capabilidades (pós-pwd)

Enviar uma vez após pareamento (`device_capabilities`):

- `heart_detect`, `bp`, `spo2`, `temperature`, `precision_sleep`
- `origin_protocol_version`, `watchday`

---

## 4. Módulos Kotlin/Java sugeridos no app

```
app/
├── ble/
│   ├── HbandConnectionManager.kt   # scan/connect/pwd/personInfo
│   ├── HbandRealtimeCollector.kt   # detect HR/SpO2/temp/BP/PPG
│   └── HbandHistorySync.kt         # origin + sleep + sport
├── net/
│   ├── HealthtechApiClient.kt      # OkHttp + X-API-Key
│   └── Dtos.kt                     # espelha OpenAPI
├── queue/
│   └── OutboxStore.kt              # Room: offline → retry batch
└── ui/
    ├── ScanActivity
    └── SyncStatusActivity
```

---

## 5. Checklist de implementação (MVP)

### Sprint A — Conectar e um vital

| Tarefa | ☐ |
|--------|---|
| Demo compila com AARs oficiais | ☐ |
| Parear device de teste (pwd + personInfo) | ☐ |
| `startDetectHeart` → log BPM | ☐ |
| POST ingest com HR + `device_id` | ☐ |
| Receber 200 da API secure/full | ☐ |
| Tratar 401/403 (chave/escopo) | ☐ |

### Sprint B — Multi-métrica + offline

| Tarefa | ☐ |
|--------|---|
| SpO2 + temp na mesma sessão (serial) | ☐ |
| Outbox local se rede falhar | ☐ |
| `batch-ingest` a cada N amostras | ☐ |
| `readOriginDataSingleDay(0, …)` → origin_batch | ☐ |
| Validar Bronze com `HBandCompanionAdapter` + pytest | ☐ |

### Sprint C — PPG / sinal

| Tarefa | ☐ |
|--------|---|
| Realtime green light (~25 Hz) em buffer 2–8 s | ☐ |
| Enviar `ppg_signal` no ingest | ☐ |
| Opcional: `POST /api/v1/signal/bmo-analysis` | ☐ |
| Accel junto no `raw` para artefato de movimento | ☐ |

### Sprint D — Produção

| Tarefa | ☐ |
|--------|---|
| Secrets: API URL + key em BuildConfig / encrypted prefs | ☐ |
| LGPD: consentimento + unlink device | ☐ |
| Telemetria de erros SDK (disconnect, busy) | ☐ |
| Testes em 2+ firmwares / chips (Nordic vs Goodix) | ☐ |
| Documentar model SKU suportados | ☐ |

---

## 6. Testes de contrato (backend)

```bash
# Unitários do normalizer
pytest tests/test_hband_normalizer.py -v

# Ingest manual (API local)
curl -s -X POST http://localhost:8080/api/v1/wearables/ingest \
  -H "X-API-Key: $INGEST_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id":"PAT-HBAND-001",
    "device_id":"HBAND-AA:BB:CC:DD:EE:FF",
    "heart_rate":78,
    "spo2":97,
    "skin_temp":33.4,
    "ppg_signal":[120,125,130,128,122,118,121,127],
    "filter_type":"BMO"
  }'
```

Fixture de envelope origin:

```json
{
  "message_type": "origin_batch",
  "schema_version": "1.0.0",
  "payload": {
    "patient_id": "PAT-HBAND-001",
    "device": {
      "device_id": "HBAND-TEST-001",
      "vendor": "hband",
      "origin_protocol_version": 3,
      "watchday": 7
    },
    "day_offset": 0,
    "samples": [
      {
        "timestamp": "2026-08-06T08:00:00Z",
        "package_number": 1,
        "rate_value": 72,
        "spo2_value": 98,
        "hrv": 44,
        "step_value": 120,
        "high_value": 118,
        "low_value": 76,
        "base_temperature": 33.2
      }
    ]
  }
}
```

---

## 7. Riscos operacionais

| Risco | Mitigação |
|-------|-----------|
| Operações paralelas no BLE | Fila única no `HbandConnectionManager` |
| PA de pulseira ≠ clínico | `signal_confidence` ↓; flag em raw |
| Protocol 0/1/2 vs 3/5 | Branch no listener OriginData vs OriginData3 |
| GATT genérico no servidor | **Não usar**; só HTTP do companion |
| Bateria baixa em BP 60s | Checar battery antes de `startDetectBP` |

---

## 8. Referências

- [Android_Ble_SDK README](https://github.com/HBandSDK/Android_Ble_SDK)
- [DeepWiki — Health Monitoring](https://deepwiki.com/HBandSDK/Android_Ble_SDK/4-health-monitoring-features)
- [DeepWiki — Origin / historical](https://deepwiki.com/HBandSDK/Android_Ble_SDK/4.6-historical-health-data-retrieval)
- [DeepWiki — PPG](https://deepwiki.com/HBandSDK/Android_Ble_SDK/4.3-ppg-testing-and-raw-data-acquisition)
- Demo: `JH58PPGOptTestActivity`, `OriginalDataLogActivity`, `OperaterActivity`
