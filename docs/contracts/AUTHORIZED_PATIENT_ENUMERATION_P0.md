# CONTRATO CORE — Enumeração autorizada de Patient (P0)

**Status:** **CONFIRMED**  
**Data:** 2026-09-16  
**Autoridade:** Leandro França de Mello (`leanderdulac`) — owner/maintainer HealthTech Core  
**Consumidor:** Next2U Web Profissional (`rafaeldepaulafigo-web/next2u-web` Issue #30)  
**Pedido Core:** [Issue #6](https://github.com/leanderdulac/healthtech/issues/6)  
**Território:** [PATIENT_TERRITORY_AUTHZ_P0.md](./PATIENT_TERRITORY_AUTHZ_P0.md) — **CONFIRMED**  
**Integração:** [NEXT2U_INTEGRATION_P0_PATIENT_READS.md](./NEXT2U_INTEGRATION_P0_PATIENT_READS.md)

Este documento publica a **capacidade server-side** que o BFF Next2U precisa para fechar o gate P0 de listagem (Slice 3 / gate #30): autorização **antes** de `limit`/`offset`/`total`.

O Core **não** autentica profissionais. A credencial continua sendo `X-API-Key` de serviço (`wearables:read`). O BFF resolve `patient:read` / assignment / identidade e envia só os **escopos territoriais** que já autorizou.

---

## 1. Capacidade escolhida

Extensão de **`GET /api/v1/patients`** (mesmo path). Sem endpoint novo.

A restrição (allow-list finita **e/ou** escopos territoriais) entra no **acesso a dados / SQL** **antes** de `LIMIT`/`OFFSET`.  
`total` é o `COUNT` do conjunto já restrito — **nunca** `COUNT(*)` global de enrollments.

Devices: parâmetro `patient_id` em **`GET /api/v1/wearables/devices`**, aplicado **antes** da paginação e dos `counts`.

---

## 2. `GET /api/v1/patients` — enumeração autorizada

### 2.1 Autenticação

| Header | Valor |
| --- | --- |
| `X-API-Key` | chave de serviço com escopo `wearables:read` |

Não enviar `professional_id`, Auth0 subject, assignment nem capability ao Core.

### 2.2 Query params

| Param | Repetível | Semântica |
| --- | --- | --- |
| `limit` | não | página, 1–200, default 50 |
| `offset` | não | deslocamento no **conjunto já filtrado**, default 0 |
| `territory` | sim | `{municipality_id}` = escopo **municipal** (todas as UBS); `{municipality_id}:{ubs_id}` = escopo **UBS**. `ubs_id` ≡ `health_unit_id` (igualdade de string). |
| `municipality_id` | sim | atalho de escopo municipal; se houver `ubs_id`, pareamento **por índice** |
| `ubs_id` | sim | atalho de escopo UBS; exige `municipality_id` correspondente |

União de múltiplos escopos: `OR` no servidor, **sem duplicar** Patient.

Exemplos:

```
GET /api/v1/patients?territory=mun-a:ubs-1&limit=50&offset=0
GET /api/v1/patients?territory=mun-a&territory=mun-b:ubs-9
GET /api/v1/patients?municipality_id=mun-a&ubs_id=ubs-1
GET /api/v1/patients?municipality_id=mun-a&municipality_id=mun-b
```

`ubs_id` sem `municipality_id` correspondente → **400**.

### 2.3 Resposta

```json
{
  "items": [ { "patient_id": "...", "municipality_id": "...", "ubs_id": "...", "...": "..." } ],
  "patients": [ "…mesmo array que items…" ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

| Campo | Semântica |
| --- | --- |
| `items` | página do conjunto **autorizado** (canônico para Next2U) |
| `patients` | alias estável do mesmo array (compatível com o runtime operacional) |
| `total` | `\|conjunto autorizado\|` — **não** é a população global |
| `limit` / `offset` | eco dos params; `offset` aplica-se **depois** do filtro |

Cada item inclui `municipality_id` e `ubs_id` (território ativo atual, ou indefinido — mas indefinido **não entra** na enumeração autorizada).

### 2.4 Invariantes (obrigatórias)

1. **Authz-before-page.** Allow-list e/ou território no `WHERE` (ou equivalente) **antes** de `LIMIT`/`OFFSET`. Filtrar a página recebida no cliente **não** é a semântica deste contrato.
2. **`total` autorizado.** `total` = cardinalidade do conjunto filtrado. Nunca o `COUNT(*)` global.
3. **Território definido.** Paciente com `municipality_id` ou `ubs_id` ausente / `null` / blank **não entra** no conjunto autorizado (fail-closed, igual a [PATIENT_TERRITORY_AUTHZ_P0.md](./PATIENT_TERRITORY_AUTHZ_P0.md) §2.2).
4. **Fail-closed sem restrição.** Chave **não-admin** sem allow-list finita **e** sem escopo territorial → `{ "items": [], "patients": [], "total": 0, ... }`. Não vaza página global. `ALLOWED_PATIENT_IDS=*` / `ALL` **sem** território também é vazio (wildcard não é enumeração autorizada).
5. **Allow-list.** `ALLOWED_PATIENT_IDS` finita (CSV) é `AND` adicional no SQL. Interseção com território, se ambos existirem.
6. **Ordenação estável.** `updated_at DESC, patient_id ASC`. O mesmo filtro + `offset` percorre o conjunto sem “furar” IDs não autorizados.
7. **Mudança de território entre páginas.** A página é um **snapshot**. Se o território ativo de um Patient mudar entre requests, ele pode entrar/sair do conjunto; o cliente **não** deve inferir completude temporal. Recomeçar de `offset=0` após mutação conhecida.
8. **Admin.** Escopo `admin` sem params territoriais pode listar o cadastro operacional global (dashboard). Isso **não** é total autorizado para o browser Next2U. Com `territory` / `municipality_id`, o admin usa a mesma via autorizada.

### 2.5 O que o BFF Next2U deve fazer

1. Resolver assignments ativos do profissional (`municipality_id`, `health_unit_id`).
2. Pedir a enumeração com a união desses escopos (`territory=mun:ubs` e/ou `territory=mun`).
3. Usar `items` + `total` como a lista/página profissional. **Não** refiltrar a página. **Não** varrer offsets globais. **Não** expor `total` de uma chamada sem território.

---

## 3. `GET /api/v1/wearables/devices` — cobertura por Patient

### 3.1 Query

| Param | Semântica |
| --- | --- |
| `patient_id` | se presente, restringe a frota **àquele** Patient **antes** de `limit`/`offset`/`counts` |
| `limit` / `offset` | paginam o conjunto já filtrado |
| `q`, `online`, `include_latest` | inalterados (aplicados depois do `patient_id`) |

A rota Next2U `GET /api/wearables/devices?patient_id=` mapeia para este param. O BFF continua exigindo `patient:read` + `wearable:read` no assignment **antes** de chamar o Core.

Sem `patient_id`, a resposta descreve a **frota** (`coverage=fleet`). Esses `counts` **não** são metadados autorizados por Patient — o BFF **não** deve expô-los como totais profissionais.

### 3.2 Resposta com `patient_id`

```json
{
  "devices": [ { "device_id": "...", "patient_id": "PAT-1", "...": "..." } ],
  "counts": { "total": 2, "online": 1, "offline": 1 },
  "limit": 200,
  "offset": 0,
  "coverage": "patient",
  "patient_id": "PAT-1"
}
```

| Garantia | Semântica |
| --- | --- |
| Completude | `coverage=patient` = conjunto **completo** de devices conhecidos daquele `patient_id` na frota operacional (depois filtrado por `q`/`online` se enviados). `counts.total` é só desse conjunto. |
| Vazio | Patient autorizado sem device → `devices: []`, `counts.total: 0` (**200**, não 404). Não revela devices de outros Patients. |
| Paginação | Se houver mais devices que `limit`, `offset` percorre **esse** conjunto. Default `limit=200` cobre a frota típica de um Patient. |
| Authz | `patient_id` fora da allow-list da chave (e não-admin) → **403**. Paciente inexistente / sem device → **200** vazio (não distingue cadastro). |
| Detalhe | `GET /api/v1/wearables/patient/{id}/latest` permanece **404** se não houver telemetria (já contratado). |

---

## 4. Fronteira de identidade (CONFIRMED)

- Core **não** recebe identidade profissional.
- `patient:read` / `wearable:read` / assignment continuam no BFF Next2U / Identity.
- Território do Patient: fonte de verdade = Core (`municipality_id` + `ubs_id`).
- `ubs_id` ≡ `health_unit_id`.

---

## 5. Erros / disponibilidade

| Caso | HTTP |
| --- | --- |
| Sem `X-API-Key` / chave inválida | 401 |
| Chave sem `wearables:read` | 403 |
| `ubs_id` órfão / território malformado | 400 |
| `DATABASE_URL` ausente ou Cloud SQL inalcançável | **503** (inalterado) |
| Patient `{id}` inexistente | 404 |

---

## 6. Resposta formal ao pedido Next2U (Issue #6 / gate #30)

1. Filtragem territorial antes da paginação → **CONFIRMED** (`GET /api/v1/patients` §2)  
2. `total` do conjunto filtrado → **CONFIRMED**  
3. Escopo UBS, municipal e união de múltiplos escopos → **CONFIRMED**  
4. Ordenação estável / território entre páginas → **CONFIRMED** (§2.4 itens 6–7)  
5. Devices por Patient com cobertura e metadados do próprio conjunto → **CONFIRMED** (`?patient_id=` §3)

Documento canônico: este arquivo em `docs/contracts/AUTHORIZED_PATIENT_ENUMERATION_P0.md`.
