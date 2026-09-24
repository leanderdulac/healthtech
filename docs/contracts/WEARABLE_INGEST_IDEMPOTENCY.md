# CONTRATO CORE — Idempotência da ingestão de wearables

**Status:** **CONFIRMED**  
**Data:** 2026-09-24  
**Autoridade:** Leandro França de Mello (`leanderdulac`) — owner/maintainer HealthTech Core  
**Consumidor:** Next2U patient Android (`leanderdulac/HBand-`) e companion in-repo  
**Superfície:** `saude_responsiva_secure` — `POST /api/v1/wearables/ingest` e `POST /api/v1/wearables/batch-ingest`  
**OpenAPI:** [`docs/openapi/hband-wearable.yaml`](../openapi/hband-wearable.yaml)

Reenvio da mesma leitura (fila Room + WorkManager, retry após 401/5xx/timeout) **não** cria um segundo registro. Já armazenado conta como sucesso: o client **deve** marcar a linha como synced.

Auth **não muda**: `X-API-Key` com escopo `wearables:write`. Chave de leitura → **403**. Sem chave → **401**.

---

## 1. Como o client deve enviar

| Mecanismo | Onde | Quando usar |
| --- | --- | --- |
| `client_reading_id` | body da leitura | **Recomendado.** UUID estável da linha Room / outbox. Não mude entre retries. |
| `Idempotency-Key` | header HTTP | Opcional. No ingest unitário também identifica a leitura. No batch, cacheia a **request** inteira. Use um id estável do flush (não um UUID novo a cada tentativa). |
| `timestamp` + `device_id` | body | Fallback (chave natural) quando o client ainda não envia id. Envie o instante da **medição**, não o do retry. |
| `metric_type` | body | Opcional. Distingue HR vs SpO2 no mesmo instante. Se omitido, o Core deriva dos campos enviados. |

Clients atuais **sem** estes campos continuam válidos (compatível). Sem `client_reading_id`, sem header e sem `timestamp` do client, o Core **não** deduplica — o instante de recepção não é estável entre retries.

Precedência da chave de uma leitura:

1. `client_reading_id`
2. `Idempotency-Key` (ingest unitário)
3. natural: `patient_id` + `device_id` + timestamp canónico UTC + tipo de métrica

O Core **indexa todas as chaves aplicáveis** da primeira escrita. Um retry que passe a enviar `client_reading_id` ainda casa com a leitura gravada só pela chave natural.

Formato dos ids: `1–128` caracteres `[A-Za-z0-9._:-]` (UUID com hífen é válido).  
`Idempotency-Key` inválido → **400**. `client_reading_id` inválido → **422**.

First write wins. O mesmo id com payload diferente devolve o registro original (`duplicate`), sem 409.

---

## 2. `POST /api/v1/wearables/ingest`

Escopo: `wearables:write`. HTTP **200** tanto para escrita nova quanto para replay.

Campos novos no body (todos opcionais): `client_reading_id`, `metric_type`.

Campos novos na resposta (não-quebrantes):

| Campo | Semântica |
| --- | --- |
| `ingest_status` | `accepted` (primeira persistência) ou `duplicate` (já existia) |
| `duplicate` | `true` se `ingest_status=duplicate` |
| `client_reading_id` | eco do id do client, quando enviado |
| `reading_id` | id interno do registro persistido |

O restante do frame (`patient_id`, `raw_telemetry`, `phantom_data`, `anomaly_detection`, …) permanece.

O client trata **200 + (`accepted` \| `duplicate`)** como synced. Não reenfileirar.

---

## 3. `POST /api/v1/wearables/batch-ingest`

Alias estável: `POST /api/v1/wearables/ingest/batch`.

Duplicatas **parciais** são resolvidas por item. Envelope antigo permanece (`status`, `patient_id`, `processed_count`, `latest_result`). Campos novos:

| Campo | Semântica |
| --- | --- |
| `processed_count` | `accepted + duplicate` — itens que o client pode marcar synced |
| `accepted_count` | primeira persistência |
| `duplicate_count` | já armazenados |
| `rejected_count` | falha de processamento do item (raro; validação Pydantic do lote ainda é 422) |
| `status` | `success` se `rejected_count=0`; `partial` se algum item falhou |
| `results[]` | um objeto por leitura, na ordem do request |

Item de `results[]`:

```json
{
  "index": 0,
  "status": "accepted",
  "client_reading_id": "room-uuid-001",
  "result": { "patient_id": "PAT-001", "ingest_status": "accepted", "...": "..." }
}
```

`status` do item: `accepted` | `duplicate` | `rejected`.  
Em `rejected` vem `error` e não vem `result`.

`Idempotency-Key` no batch: se a mesma chave + mesmo `patient_id` já produziu resposta, o Core devolve o envelope cacheado sem reprocessar. Itens individuais continuam a usar `client_reading_id` / chave natural — um segundo flush só com o restante da fila (header novo) não recria os já gravados.

Clients antigos que só olham `200` + `processed_count` continuam corretos: duplicata conta no `processed_count`.

---

## 4. GET latest / history

Forma inalterada. Campos novos no frame persistido (`reading_id`, `client_reading_id`, `metric_type`) são opcionais e não-quebrantes. `ingest_status` é da resposta de ingest, não um requisito de GET.

---

## 5. Auth (inalterado)

| Request | Resultado |
| --- | --- |
| Sem `X-API-Key` | **401** |
| Chave `wearables:read` (READ) em POST ingest / batch | **403** |
| Chave `wearables:write` (INGEST) | **200** (ou 422 de validação) |

---

## 6. Como o app Android deve usá-lo

1. Cada linha Room ganha um UUID no insert (`client_reading_id`). Nunca gere outro no retry.
2. Envie também `timestamp` da medição e `device_id`.
3. WorkManager: `200` com `ingest_status` `accepted` ou `duplicate` → `synced`.
4. Preferir `POST /api/v1/wearables/batch-ingest` no flush. Reconciliar por `results[i].status`.
5. Header `Idempotency-Key` opcional = id estável daquele chunk de flush (ex. hash ordenado dos `client_reading_id`), **não** um UUID por tentativa.
6. 401/403: não marcar synced (chave). 5xx / rede: manter na fila; o retry é seguro.

Exemplo unitário:

```http
POST /api/v1/wearables/ingest
X-API-Key: <INGEST_API_KEY>
Idempotency-Key: 8f3a2c1e-4b0d-4a11-9c22-flush-chunk-01
Content-Type: application/json

{
  "patient_id": "PAT-HBAND-001",
  "device_id": "HBAND-AA:BB:CC:DD:EE:FF",
  "timestamp": "2026-09-24T12:00:00Z",
  "heart_rate": 78.0,
  "spo2": 97.0,
  "client_reading_id": "8f3a2c1e-4b0d-4a11-9c22-111111111111",
  "ingest_source": "ble_hband"
}
```
