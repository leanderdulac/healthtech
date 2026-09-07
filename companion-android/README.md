# Healthtech Companion (Android MVP)

App Android nativo que se conecta à **Secure API** do monorepo Healthtech:
testa saúde da API, envia frequência cardíaca (`POST /ingest`), consulta
`latest` / `history`, mantém **outbox offline** e pode **simular BLE**.

```
companion-android/
├── app/                    ← UI Compose + simulador BLE + gancho HBand SDK
├── client/                 ← biblioteca Gradle (Retrofit, DTOs, outbox)
├── postman/                ← collections HTTP
├── sprint-a/               ← ponteiro histórico (código vive em app/ e client/)
└── docs → ../docs/openapi/hband-wearable.yaml
```

Fonte de verdade de rede: **módulo `:client`**. O app depende dele — não copie `net/`.

## Requisitos

- Android Studio Ladybug / Koala+ (ou Hedgehog)
- JDK 17
- Emulador API 26+ ou device USB
- API key com escopo `wearables:write` (a sua, via `local.properties` ou a UI)

## Abrir e rodar

1. **Android Studio** → *Open* → pasta `companion-android/`
2. Aguarde o Gradle sync
3. Copie config:

```bash
cp local.properties.example local.properties
# Studio preenche sdk.dir
# HEALTHTECH_BASE_URL=http://10.0.2.2:8080
# cole a chave (wearables:write) em HEALTHTECH_INGEST_API_KEY — nunca commitar
```

4. Rode a configuração **app** (▶️)

### Base URL

| Ambiente | Base URL |
|----------|----------|
| Emulador → API no PC (default debug) | `http://10.0.2.2:8080` |
| Device físico → API no PC | `http://<IP-LAN-do-PC>:8080` |
| Cloud Run secure | defina `HEALTHTECH_BASE_URL` no `local.properties` (não há default de produção no APK) |
| Logs GCP (mobile) | [`docs/CLOUD_LOGGING_MOBILE.md`](../docs/CLOUD_LOGGING_MOBILE.md) |

API local:

```bash
cd saude_responsiva_secure
export PYTHONPATH=. ENVIRONMENT=development APP_MODE=secure
# defina INGEST_API_KEY no .env — a mesma que você cola no app
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Telas / ações do MVP

| UI | API / comportamento |
|----|---------------------|
| **Testar** | `GET /api/health` |
| **Enviar ingest** | `POST /api/v1/wearables/ingest` (`ingest_source=companion_manual`) |
| **Simular BLE** | HR periódico com `ingest_source=ble_sim` (não é pulseira física) |
| **HBand SDK** | Gancho Veepoo — recusa fingir pairing se os AARs não estão no APK |
| **Latest / History** | `GET .../patient/{id}/latest` e `/history` |
| **Outbox flush** | enfileira + `batch-ingest` se N>1 |

Alertas clínicos na UI são **apoio à decisão**, não protocolo mandatório.

## BLE

O scan lista **todos** os BLE próximos. A leitura de FC só funciona depois do handshake Veepoo:

`connect → notify OK → senha 0000 → syncPersonInfo → startDetectHeart`

Só o estado `STATE_HEART_NORMAL` com BPM 20–250 é enviado à API. Medição em curso, pulseira fora do pulso ou BPM 0 são ignorados.

1. Aceite Bluetooth + localização.
2. **Escanear** → pulseiras aparecem no topo (badge “pulseira?”).
3. Toque na **pulseira**, não em fone/TV.
4. Vista o device. Se o relógio pedir confirmação, toque nele.
5. GATT SIG é fallback para bandas que expõem 0x180D (HBand em geral **não** expõe).

## Build CLI (opcional)

```bash
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/Android/Sdk
cd companion-android
./gradlew :app:assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```
