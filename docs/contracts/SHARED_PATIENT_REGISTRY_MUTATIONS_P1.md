# CONTRATO CORE — Cadastro compartilhado (mutações) P1

**Status:** **DRAFT** (esqueleto para workshop — **não** implementar como CONFIRMED)  
**Revisão:** 2026-09-24 — inconsistências de review (compatibilidade, dedup, PATCH, território, idempotência, merge, links/consents) resolvidas **no papel**; status permanece DRAFT  
**Autoridade proposta:** Leandro França de Mello (`leanderdulac`) — HealthTech Core  
**Consumidores:** Next2U Web (Rafael), tablet ACS (**TBD**), app paciente (**TBD**)  
**OpenAPI:** [shared-patient-registry-mutations-p1.yaml](./shared-patient-registry-mutations-p1.yaml)  
**Issue:** [#12](https://github.com/leanderdulac/healthtech/issues/12)  
**Depende de (CONFIRMED):**
- [PATIENT_TERRITORY_AUTHZ_P0.md](./PATIENT_TERRITORY_AUTHZ_P0.md)
- [AUTHORIZED_PATIENT_ENUMERATION_P0.md](./AUTHORIZED_PATIENT_ENUMERATION_P0.md)
- [NEXT2U_INTEGRATION_P0_PATIENT_READS.md](./NEXT2U_INTEGRATION_P0_PATIENT_READS.md)

Este arquivo e o YAML são a **mesma** proposta. Em conflito de redação, o YAML vence para tipos/códigos HTTP; este markdown vence para semântica (território, idempotência, merge, PATCH).

## Objetivo

Um único `patient_id` canônico no Core para Web, ACS e app paciente: criar, editar, pesquisar, deduplicar, vincular território/ACS/cuidador, consentimentos e anexos — com versão e conflito de escrita concorrente.

## Fora de escopo deste DRAFT

- Autenticação do profissional / ACS / paciente (Identity / IdP — frente 2).
- OS / visita / offline ACS (frentes 3–4).
- Cálculo oficial de risco (frente 6) — só pode **referenciar** `patient_id` + `registry_version`.
- Implementação runtime das mutações (PR separado **depois** de CONFIRMED).
- Promover este contrato a CONFIRMED.

## Princípios

1. **Core é fonte de verdade** do cadastro e do território ativo (`municipality_id` + `ubs_id`).
2. Credencial BFF→Core continua `X-API-Key` de **serviço**. Identidade humana fica no BFF.
3. `ubs_id` ≡ `health_unit_id` (igualdade de string) — igual P0.
4. Território indefinido **pode** existir no cadastro, mas **não** entra na enumeração autorizada P0.
5. `POST` de criação / merge / anexo exige `Idempotency-Key`. `PATCH` e `PUT` de cadastro exigem `If-Match: {registry_version}`.
6. Conflito de **versão** → **409** `registry_version_mismatch` com representação atual. Reuso de chave de idempotência com payload diferente → **409** `idempotency_key_reuse` (não é replay).
7. Dedup **sugere** candidatos; **merge** é explícito e auditado (nunca automático).
8. Campos P1 são **aditivos**. Clientes P0 ignoram desconhecidos; o Core **não** remove nem renomeia campos CONFIRMED.

---

## 1. Compatibilidade de dados com P0

GET ` /api/v1/patients` e `GET /api/v1/patients/{patient_id}` permanecem o contrato **CONFIRMED** P0. P1 **estende** o objeto, não o substitui.

### 1.1 Campos P0 (estáveis — não remover)

| Campo | GET operacional hoje |
| --- | --- |
| `patient_id` | string, 3–64, `^[A-Za-z0-9\-_]+$` |
| `display_name` | string ou null |
| `phone` | string ou null |
| `caregiver_phone` | string ou null (telefone; **não** é identidade) |
| `programs` | array de string (sempre presente; `[]` se vazio) |
| `diseases` | array de string (sempre presente; `[]` se vazio) |
| `isolation_social` | boolean (nunca null no GET) |
| `is_demo` | boolean (default `false`) |
| `municipality_id` | string ou null |
| `ubs_id` | string ou null (`≡ health_unit_id`) |
| `created_at` / `updated_at` | date-time |

Envelope da listagem (inalterado): `items` **e** `patients` são o **mesmo** array; `total` / `limit` / `offset` com authz-before-page.

### 1.2 Campos P1 (aditivos; ausentes/null até haver dado)

`registry_version`, `cpf_fingerprint` (nunca CPF cru), `birth_date`, `sex`, `address`, `links`, `clinical_flags`, `consent_summary`.

`registry_version` **não** é obrigatório para um cliente P0 validar o GET. Em respostas P1-aware o Core **sempre** devolve um valor opaco (também no `ETag`):

- linhas só-P0: versão **sintetizada** a partir de `updated_at` + `patient_id` (estável até a primeira mutação P1);
- após qualquer escrita P1: versão **monotônica** nova a cada mutação de cadastro (não de anexo).

Assim o `PATCH` inicial de uma linha Slice 3 não exige coluna nova no banco antes do workshop.

### 1.3 Dono de cada conceito (evita campos duplicados)

| Conceito | Campo canônico | Não usar como SoT |
| --- | --- | --- |
| Programas / carteira | `programs` (P0) | `links.program_enrollments` **não existe** em escrita; se um GET ecoar, é alias read-only de `programs` |
| Telefone do cuidador | `caregiver_phone` (P0) | — |
| Identidade do cuidador | `links.caregiver_subject_id` | não gravar login cru |
| ACS responsável | `links.acs_agent_id` | — |
| Bandeiras clínicas livres | `clinical_flags` (objeto) | não misturar com `diseases` / `programs` |
| Consentimento | `GET/PUT …/consents`; `consent_summary` no Patient é **projeção** | não PATCH-ar consent via `PatientPatchRequest` |

`clinical_flags` entra em **create e patch** (o YAML anterior omitia no create).

### 1.4 `patient_id`

Workshop ainda decide UUID vs prefixo territorial. Até lá, o DRAFT fecha só o fio do contrato:

- omitido no `POST` → Core **emite** um id no charset P0;
- enviado → sugestão; Core pode recusar (`400` formato / `409` `duplicate_patient_id`);
- merge **não** reutiliza o id aposentado.

---

## 2. Checagem de duplicata (nunca auto-merge)

Três superfícies distintas:

| Superfície | Faz | Não faz |
| --- | --- | --- |
| `POST /patients` | Recusa colisão **forte** | Não devolve o existente como 201 |
| `POST /patients/search` | Busca operacional (nome/fone/fingerprint) | Não substitui `GET /patients` territorial |
| `POST /patients/dedup/candidates` | Rankeia suspeitos | **Nunca** funde |

### 2.1 Colisão forte na criação

Fingerprint **não vazio** igual a outro cadastro **ativo** (não aposentado):

| Situação | HTTP | `conflict_code` | Corpo |
| --- | --- | --- | --- |
| Duplicata **visível** no conjunto autorizado do caller | **409** | `duplicate_fingerprint` | `existing_patient_id` + `current` se autorizado |
| Duplicata **fora** do conjunto autorizado | **409** | `duplicate_fingerprint` | **sem** `existing_patient_id` / `current` (não vaza território) |
| `patient_id` sugerido já existe (ativo) | **409** | `duplicate_patient_id` | id pedido; sem PII extra |
| `patient_id` é aposentado por merge | **409** | `already_merged` | `survivor_patient_id` |

Colisão **fraca** (nome+data, fone) **não** bloqueia o `POST`. O BFF deve chamar `dedup/candidates` **antes** se o produto quiser aviso.

### 2.2 Dedup

- Âncora = `patient_id` existente **ou** payload equivalente a create (sem persistir).
- Resposta: candidatos com `score` 0..1 e `reasons[]`.
- Candidatos passam pelo **mesmo** filtro autorizado de `GET /patients` (authz-before-rank). Admin sem território pode ver o cadastro operacional global (igual P0 §2.4.8) — isso **não** é total Next2U.
- Aposentados por merge **não** aparecem.

---

## 3. Semântica de edição

### 3.1 `PATCH /patients/{id}`

JSON merge das chaves enviadas:

| Envio | Efeito |
| --- | --- |
| chave **omitida** | inalterado |
| escalar / objeto **`null`** | limpa (volta ao vazio/null do GET P0) |
| array enviado | **substitui** o array inteiro (`[]` limpa) |
| `array: null` | **400** (use `[]`) |
| `links` presente | substitui o objeto `links` inteiro (mesmo contrato do `PUT /links`) |
| chave desconhecida | **400** |
| `consent_summary` / `consents` | **400** — usar `PUT /consents` |
| `programs` vs `links` | só `programs` no PATCH de Patient; programas **não** via `links` |

`If-Match` é **obrigatório**. Valor = `registry_version` / `ETag` do último GET. Sem header → **428**. Versão velha → **409** `registry_version_mismatch` com `current` (Patient completo).

`PATCH` **não** cria Patient. Id inexistente → **404**. Id aposentado → **410** `already_merged`.

### 3.2 `PUT /links` vs `PATCH.links`

Equivalentes: ambos substituem `acs_agent_id`, `caregiver_subject_id`, `caregiver_relationship`. Não aceitam `program_enrollments`. Incrementam `registry_version`.

### 3.3 `PUT /consents`

**Upsert por `purpose`**, não wipe do conjunto:

- itens enviados atualizam só aqueles `purpose`;
- purpose omitido permanece;
- revogar = `status=revoked` (não omitir);
- `purpose` fora do enum → **400**;
- dois itens com o mesmo `purpose` no body → **400**.

`If-Match` = `registry_version` do Patient (não há versão paralela de consent). Sucesso incrementa `registry_version`. Se o body trouxer `registry_version`, tem de coincidir com o header ou **400**.

### 3.4 Anexos e versão

`POST /attachments` **não** incrementa `registry_version` (evita 409 em PATCH só porque houve upload). O evento entra em `GET /history` com `actor_type` e `summary`.

---

## 4. Permissões territoriais

Herdam P0. Core **não** recebe JWT profissional. BFF **não** recalcula território.

### 4.1 Escopos de chave (proposta; workshop ainda escolhe o split)

| Escopo | Superfície |
| --- | --- |
| `wearables:read` | GET P0 (continua) até existir `patients:read` |
| `patients:write` | POST create, PATCH, PUT links, POST attachments, GET history |
| `patients:merge` | POST merge (**não** incluso em `write`) |
| `patients:consent` | GET/PUT consents |
| `admin` | igual P0: pode operar sem recorte territorial |

Chave sem o escopo → **403**. Sem chave → **401**.

### 4.2 Recorte (não-admin)

Mesma gramática P0: query `territory` / `municipality_id` / `ubs_id` (união, `ubs_id` órfão → **400**).

| Recurso | Regra |
| --- | --- |
| `GET /patients` | CONFIRMED: authz-before-page; indefinido fora; fail-closed → página vazia |
| `POST /patients/search` e `…/dedup/candidates` | **o mesmo** recorte **antes** de rankear. Sem restrição (allow-list finita **ou** território) → `hits`/`candidates` vazios, **não** cadastro global |
| `POST /patients` | território do body, se **definido**, tem de pertencer à união enviada; indefinido **pode** cadastrar e **não** entra na enumeração P0 |
| PATCH / PUT / attachments / consents / history | o Patient alvo tem de ser visível sob o mesmo recorte (ou allow-list). Fora → **404** (preferido, igual detalhe P0) — não 403 que confirma existência |
| `POST …/merge` | **sobrevivente e duplicata** visíveis no recorte. Territórios definidos **distintos** → **409** `territory_mismatch` (não há “ganhador” automático de UBS) |

Allow-list finita (`ALLOWED_PATIENT_IDS`) é `AND` adicional, igual P0. Wildcard `*` / `ALL` **sem** território **não** autoriza enumeração nem search/dedup.

### 4.3 Mudança de território no PATCH

Enviar só um de `municipality_id` / `ubs_id` como null (ou blank) deixa o território **indefinido** (P0 §2.2). O Patient some da enumeração autorizada na **próxima** página (snapshot). O BFF recomeça de `offset=0`.

---

## 5. Retries e idempotência

### 5.1 Onde `Idempotency-Key` é obrigatório

`POST /patients`, `POST /patients/{id}/merge`, `POST /patients/{id}/attachments`.

- Header obrigatório, 8–128 chars. Ausente → **400**.
- Janela proposta: **24 h** (workshop pode mudar).
- Fingerprint da operação = `método + path + corpo JSON canônico` (sem o header).
- **Mesma** chave + **mesmo** fingerprint → **replay**: status e corpo **originais**; header `Idempotent-Replayed: true`. **Não** é 409.
- Mesma chave + fingerprint **diferente** (ainda na janela) → **409** `idempotency_key_reuse` (sem `current` Patient).
- Expirada → trata como nova.

`POST /patients` bem-sucedido na primeira vez: **201**. Replay: também **201** + `Idempotent-Replayed`.

### 5.2 Onde o retry é `If-Match` (sem Idempotency-Key)

`PATCH` Patient, `PUT /links`, `PUT /consents`.

Fluxo: 409 versão → GET → reaplicar delta → novo `If-Match`. Replay cego do mesmo PATCH sem reler é **incorreto**.

`If-Match: *` **não** é aceito (evita overwrite cego) → **400**.

### 5.3 O que **não** é 409 de idempotência

O YAML inicial listava `idempotency_replay` como conflito. Isso era inconsistente: replay **bem-sucedido** é 2xx. Removido.

---

## 6. Merge de cadastros

`POST /api/v1/patients/{patient_id}/merge` — `{patient_id}` do path é o **sobrevivente**. Body: `duplicate_patient_id` (aposentado) + `reason` (≥3).

Nunca automático. Exige `patients:merge` + `Idempotency-Key` + `If-Match` do sobrevivente. `duplicate_registry_version` no body é **recomendado**; se enviado e velho → **409** `merge_race`.

### 6.1 Efeito

| Recurso | Regra DRAFT |
| --- | --- |
| Sobrevivente | permanece; `registry_version` incrementa |
| Duplicata | **aposentada** (não apagada). GET → **410** `already_merged` + `survivor_patient_id`. Fora de listagem, search e dedup |
| Wearables | `reassign_wearables` default **true** → devices da duplicata passam a `patient_id` do sobrevivente |
| Trabalho aberto (OS/visita) | `reassign_open_work` default **false** — frentes 3–4 ainda não existem; órfãos ficam **TBD** de workshop |
| `programs` / `diseases` / `clinical_flags` | união; no conflito de escalar (nome, fone, sexo, fingerprint) **vence o sobrevivente** |
| Território | se ambos definidos e iguais, mantém; se só um definido, copia o definido para o sobrevivente; se ambos definidos e **diferentes** → **409** `territory_mismatch` (não mergeia) |
| `links` | sobrevivente vence; slot null no sobrevivente pode ser preenchido pelo da duplicata |
| Consents | por `purpose`: se o sobrevivente é `unknown`/ausente, copia o da duplicata; senão sobrevivente vence |
| Anexos | metadados da duplicata passam a apontar para o sobrevivente |
| Histórico | evento `merge` nos dois ids; leituras seguintes do aposentado só 410 |

Não há “des-merge” neste DRAFT.

Replay idempotente de merge já concluído (mesmo par sobrevivente/duplicata): **200** + `Idempotent-Replayed` com o `MergeResult` original.

Merge já feito com **outro** sobrevivente → **409** `already_merged`.

---

## 7. Links e consents

### 7.1 Links

`PUT /api/v1/patients/{id}/links` substitui só o bloco ACS/cuidador. Resposta: Patient completo + `ETag`.

`caregiver_phone` **não** muda neste PUT (usar PATCH). `programs` **não** muda neste PUT.

### 7.2 Consents

Propósitos fechados: `care`, `telemetry`, `messaging_sm_click`, `research`, `caregiver_share`.

Status: `granted` | `denied` | `revoked` | `unknown`.

`GET` devolve `ConsentList` (`items` + `registry_version` ecoado do Patient). Patient.GET. `consent_summary` é o mesmo conjunto sem `evidence` / `note`.

`PUT` exige `patients:consent`. Sem esse escopo, `patients:write` **não** basta (proposta; workshop confirma o split).

---

## Endpoints (proposta)

| Método | Path | Função | Retry |
| --- | --- | --- | --- |
| `POST` | `/api/v1/patients` | Criar → `patient_id` | `Idempotency-Key` |
| `PATCH` | `/api/v1/patients/{patient_id}` | Atualizar cadastro | `If-Match` |
| `GET` | `/api/v1/patients` / `/{id}` | Já CONFIRMED P0 (+ campos aditivos) | — |
| `POST` | `/api/v1/patients/search` | Pesquisa cadastral **no conjunto autorizado** | — |
| `POST` | `/api/v1/patients/dedup/candidates` | Candidatos de duplicata | — |
| `POST` | `/api/v1/patients/{patient_id}/merge` | Fundir duplicata no sobrevivente do path | `Idempotency-Key` + `If-Match` |
| `PUT` | `/api/v1/patients/{patient_id}/links` | ACS / cuidador | `If-Match` |
| `GET`/`PUT` | `/api/v1/patients/{patient_id}/consents` | Consentimentos (PUT = upsert por purpose) | `If-Match` no PUT |
| `GET`/`POST` | `/api/v1/patients/{patient_id}/attachments` | Metadados + URL assinada | `Idempotency-Key` no POST |
| `GET` | `/api/v1/patients/{patient_id}/history` | Histórico de versões / merge / anexos | — |

## Workshop — decisões ainda abertas

Estas **não** foram fechadas aqui (bloqueiam CONFIRMED, não o alinhamento interno do DRAFT):

- [ ] Quem gera `patient_id` (Core UUID vs prefixo territorial)? — DRAFT só fixou charset + Core emite se omitido
- [ ] CPF: só fingerprint no Core ou vault separado?
- [ ] Merge: papel autorizador humano; wearables/visitas órfãs se `reassign_open_work=false`
- [ ] Anexos: bucket + retenção LGPD?
- [ ] Escopos: confirmar split `patients:write` / `patients:merge` / `patients:consent` vs só `wearables:read`
- [ ] ACS/app paciente: mesma surface via BFF ou subset?

## Critério para promover a CONFIRMED

OpenAPI revisada por Core + Rafael + dono ACS; smoke staging com 2 writers concorrentes (409 de **versão**, e replay 2xx de idempotência); seed Slice 3 alinhado (GET aditivo + `ETag` sintetizado); BFF não recalcula território.

## Histórico desta revisão (não promove status)

| Antes (PR #13) | Depois (esta revisão DRAFT) |
| --- | --- |
| `Patient.registry_version` required no GET compartilhado com P0 | Campo **aditivo**; ETag sintetizado em linhas só-P0 |
| `409` misturava replay de idempotência e fingerprint | Replay = 2xx + `Idempotent-Replayed`; 409 só `idempotency_key_reuse` / colisões / versão / merge |
| Search/dedup sem recorte territorial | Mesmo fail-closed / authz-before-rank que P0 |
| `links.program_enrollments` vs `programs` | `programs` é SoT; links não escrevem programas |
| PATCH omitia `clinical_flags` no create; `sex` sem enum | Create/patch alinhados; null vs `[]` documentado |
| Merge sem 410 / território / consents | Sobrevivente no path; 410 no aposentado; `territory_mismatch`; regras de projeção |
| PUT consents = “upsert” sem dizer se wipe | Upsert por `purpose`; wipe proibido |
| Anexos vs `If-Match` | Upload **não** bumpa `registry_version` |
