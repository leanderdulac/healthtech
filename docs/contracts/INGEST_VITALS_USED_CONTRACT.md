# `clinical_alerts.vitals_used` / `context_informed` — contrato do ingest (PR #22)

**Status:** DRAFT (PR #22, revisão Rafael — 2ª rodada: proveniência) · **Endpoint:** `POST /api/v1/wearables/ingest`
e `batch-ingest` (secure e monólito), também persistido no frame e devolvido em
`GET /api/v1/wearables/patient/{id}/history|latest` (campo `clinical_alerts`).
**Fonte:** `src/clinical_intelligence/alert_ingest.py::assess_ingest_alerts`
(cópia vendida em `saude_responsiva_secure/_vendor_src/`, sincronizada por
`scripts/sync_secure_vendor.py --check`).

## Por que mudou

Antes da PR #22, `vitals_used` era `full["vitals"] or VitalSnapshot.to_feature_dict()`:
o vetor de **features de ML com 22 chaves**, todas `float` e **nunca nulas**, com
**valores de treino imputados** quando o sinal não chegou (PA 120/80, SpO2 98,
temp 36,5, glicose 100, sono 8 h…). Uma leitura só com FC 72 + SpO2 88 aparecia
como "PA 120/80, temp 36,5" — informação que o cliente nunca enviou. No secure,
o phantom heurístico ainda injetava PA 83,9/63,9 (`reliable=True`) e disparava
regras de PA baixa.

Desde a PR #22:

* `vitals_used` = **só vitais medidos** que a matriz usou (10 chaves, `null` quando ausentes).
* `context_informed` (novo, aditivo) = as **12 chaves que saíram**, restauradas **sem imputação**:
  valor só quando derivado de dado efetivamente recebido **e medido na leitura atual**
  (e, para comparações, de um valor medido comparável no histórico enviado); caso
  contrário `null`. Phantom/estimativa nunca aparece nem influencia estes campos, nem
  no modo demo em dev autorizado. Sinal presente mas **não consumido** pelo cálculo
  da matriz sai `null` (nunca um default como `false` apresentado como conhecido).
  Proveniência campo a campo na seção
  [Proveniência de `context_informed`](#proveniência-de-context_informed-campo-a-campo).

## Campos — antes (22) vs depois

Legenda: **Antes** = tipo/default imputado no legado; **Depois** = onde está e tipo.

| # | Chave legado | Antes (tipo · imputado se ausente) | Depois | Tipo depois | Origem do valor depois |
|---|---|---|---|---|---|
| 1 | `pas` | float · 120.0 | `vitals_used.pas` | float \| null | `blood_pressure_sys` medido (phantom só no modo demo dev) |
| 2 | `pad` | float · 80.0 | `vitals_used.pad` | float \| null | `blood_pressure_dia` medido (idem) |
| 3 | `hr` | float · 70.0 | `vitals_used.hr` | float \| null | `heart_rate` (obrigatório no ingest → sempre presente) |
| 4 | `spo2` | float · 98.0 | `vitals_used.spo2` | float \| null | `spo2` |
| 5 | `temp_c` | float · 36.5 | `vitals_used.temp_c` | float \| null | `body_temp_c` ou `skin_temp` (tratamento de `skin_temp` **inalterado**, aguardando decisão de contrato) |
| 6 | `glucose_mgdl` | float · 100.0 | `vitals_used.glucose_mgdl` | float \| null | `glucose_mgdl` medido |
| 7 | `steps_drop_pct` | float · 0.0 (e 5.0 fixo no ingest) | `vitals_used.steps_drop_pct` | float \| null | `steps_drop_pct` |
| 8 | `sleep_worsen_pct` | float · 0.0 (e 5.0 fixo no ingest) | `vitals_used.sleep_worsen_pct` | float \| null | `sleep_worsen_pct` |
| 9 | `hr_baseline_rise` | float · 0.0 (heurística por atividade) | `vitals_used.hr_baseline_rise` | float \| null | `hr_baseline_rise` ou FC − `basal.hr` |
| 10 | `spo2_drop_points` | float · 0.0 | `vitals_used.spo2_drop_points` | float \| null | `spo2_drop_points` ou `basal.spo2` − SpO2 |
| 11 | `consciousness_altered` | float 0/1 · 0.0 | `context_informed.consciousness_altered` | bool \| null | chave `consciousness_altered` enviada |
| 12 | `map_approx` | float · (PAS+2·PAD)/3 com 120/80 | `context_informed.map_approx` | float \| null | só com PAS **e** PAD medidas |
| 13 | `pulse_pressure` | float · PAS−PAD com 120/80 | `context_informed.pulse_pressure` | float \| null | só com PAS **e** PAD medidas |
| 14 | `consecutive_valid` | float · 1.0 | `context_informed.consecutive_valid` | int \| null | só com par **medido** comparável atual × `previous_reading` (SpO2 ou glicose medida); senão `null` |
| 15 | `rest` | float 0/1 · 0.0 | `context_informed.rest` | bool \| null | chave `rest` ou `activity_level` medido (<20 ⇒ repouso) |
| 16 | `fasting` | float 0/1 · 0.0 | `context_informed.fasting` | bool \| null | `fasting`, `preprandial` (raiz) ou `_hband.fasting` — `_hband.preprandial` **não** é consumido ⇒ `null` |
| 17 | `steps_interrupted` | float 0/1 · 0.0 | `context_informed.steps_interrupted` | bool \| null | `steps_interrupted` (raiz ou `_hband`) ou `fall_suspected` (raiz) — `_hband.fall_suspected` ⇒ `null` |
| 18 | `sleep_hours` | float · 8.0 | `context_informed.sleep_hours` | float \| null | chave `sleep_hours` |
| 19 | `steps_drop_days` | float · 0.0 | `context_informed.steps_drop_days` | int \| null | chave `steps_drop_days` |
| 20 | `pas_rise_vs_basal` | float · 0.0 | `context_informed.pas_rise_vs_basal` | float \| null | PAS medida − `basal.pas` |
| 21 | `pas_drop_vs_basal` | float · 0.0 | `context_informed.pas_drop_vs_basal` | float \| null | `basal.pas` − PAS medida |
| 22 | `glucose_delta` | float · 0.0 | `context_informed.glucose_delta` | float \| null | glicose **medida** atual − glicose de `previous_reading` (nunca phantom) |

Resumo da mudança de tipo: legado `Dict[str, float]` (22 chaves, nunca `null`) →
`vitals_used: Dict[str, float | null]` (10 chaves fixas) + `context_informed:
Dict[str, bool | int | float | null]` (12 chaves fixas, ordem estável). Nenhuma chave
some do payload `clinical_alerts` como um todo; o que muda é (a) a localização de
12 chaves e (b) `null` no lugar de valores inventados. Booleanos passaram de
`0.0/1.0` para `true/false`.

Outros campos relacionados em `clinical_alerts.source_meta` (PR #22):
`bp_source`/`glucose_source` ∈ `measured | phantom | absent` (antes `unknown` como
default), `bp_reliable`/`glucose_reliable` = `false` sem medida (antes `true`),
`phantom_vitals_enabled: bool` (novo). `phantom_data` na raiz do frame é `{}` fora
do modo demo.

### Observação (pré-existente, fora do escopo da PR #22)

O schema secure aceita `at_rest`, `fasting_or_preprandial`,
`steps_drop_consecutive_days`, `consecutive_count`, `hourly_steps_available`,
`abrupt_steps_stop`, `inactivity_rest_of_active_period`, `pas_drop_mmhg`, etc.,
mas `vitals_from_ingest_context` lê as chaves `rest`, `fasting`, `steps_drop_days`,
`steps_interrupted`… Esses aliases do schema **não** chegam à matriz (nem antes
nem depois desta PR) e por isso também não aparecem em `context_informed`. Mapear
os aliases muda o comportamento das regras e fica para uma PR própria.

## Proveniência de `context_informed` (campo a campo)

Regras gerais (revisão Rafael, 2ª rodada — implementadas em
`alert_ingest.CONTEXT_SOURCES`, `context_signal_present`, `_measured_consecutive`
e `context_informed`):

1. **Só dado recebido e medido na leitura atual.** PA/glicose só contam se
   `source_meta.bp_source` / `glucose_source` == `measured`. Phantom/estimativa
   nunca entra, **nem em dev com `ALERT_ALLOW_PHANTOM_VITALS=1` autorizado**.
2. **Comparações exigem par medido comparável.** Campo de comparação só tem valor se
   a leitura atual tem o sinal medido **e** o histórico enviado (`basal`/`baseline`
   ou `previous_reading`/`previous_vitals`) tem o mesmo sinal. Caso contrário `null`.
3. **Presente == consumido.** "Informado" significa: alguma das fontes que o
   **cálculo da matriz consome** (tabela única `CONTEXT_SOURCES`, usada pelo
   cálculo e pelo exportador) veio não-nula. Sinal enviado mas não consumido
   (ex.: `_hband.preprandial`, `_hband.fall_suspected`, aliases do schema como
   `fasting_or_preprandial`, `at_rest`, `consecutive_count`,
   `steps_drop_consecutive_days`) ⇒ `null`.
4. **`null` = desconhecido.** Nunca `false`/`0`/`1` por default. `false`/`0`
   só quando o cliente enviou explicitamente esse valor numa fonte consumida
   (ou, para `rest`, quando `activity_level` medido ≥ 20).

Notação: "raiz" = chave no corpo do ingest (`raw_telemetry`); `_hband.x` = chave em
`_hband`/`hband` do payload. Precedência = ordem da coluna (semântica `a or b or c`
do cálculo legado, inalterada).

| Campo | Tipo | Fonte(s) consumidas (precedência) | Valor quando | `null` quando |
|---|---|---|---|---|
| `consciousness_altered` | bool \| null | `_hband.consciousness_altered`, raiz `consciousness_altered` | alguma fonte não-nula | nenhuma fonte enviada |
| `map_approx` | float \| null | PAS e PAD **medidas** (`blood_pressure_sys`/`_dia`, raiz ou `_hband`) | `bp_source=measured` e PAS **e** PAD presentes: (PAS+2·PAD)/3 | PA ausente, só PAS ou só PAD, ou PA phantom |
| `pulse_pressure` | float \| null | idem | idem: PAS − PAD | idem |
| `consecutive_valid` | int (1\|2) \| null | SpO2 atual (medida) × `previous_reading.spo2`; glicose atual **medida** × `previous_reading.glucose_mgdl`/`glucose` (ou `previous_vitals`) | há ≥1 par medido comparável: `2` se algum par dentro da tolerância (SpO2 ±1; glicose ±15 mg/dL), senão `1` | sem `previous_reading`, ou sem par comparável (ex.: histórico só com FC; histórico com glicose e leitura atual sem glicose medida; glicose atual phantom) |
| `rest` | bool \| null | raiz `rest`, `_hband.rest`; ou `activity_level` medido (< 20 ⇒ `true`) | alguma fonte não-nula ou `activity_level` enviado | nada disso enviado (`at_rest` do schema não é consumido) |
| `fasting` | bool \| null | raiz `fasting`, raiz `preprandial`, `_hband.fasting` | alguma fonte não-nula | nenhuma dessas; **`_hband.preprandial` e `fasting_or_preprandial` não são consumidos ⇒ `null`** |
| `steps_interrupted` | bool \| null | raiz `steps_interrupted`, `_hband.steps_interrupted`, raiz `fall_suspected` | alguma fonte não-nula | nenhuma dessas (`_hband.fall_suspected`, `abrupt_steps_stop` ⇒ `null`) |
| `sleep_hours` | float \| null | raiz `sleep_hours`, `_hband.sleep_hours` | alguma fonte não-nula e numérica | não enviado |
| `steps_drop_days` | int \| null | raiz `steps_drop_days`, `_hband.steps_drop_days` | alguma fonte não-nula | não enviado (`steps_drop_consecutive_days` não é consumido) |
| `pas_rise_vs_basal` | float \| null | PAS **medida** × `basal.pas`/`basal.blood_pressure_sys` (`basal`/`baseline` raiz ou `_hband.basal`) | PA medida e PAS basal enviada: PAS − basal | PA ausente/phantom, ou basal sem PAS |
| `pas_drop_vs_basal` | float \| null | idem | idem: basal − PAS | idem |
| `glucose_delta` | float \| null | glicose **medida** × `previous_reading.glucose_mgdl`/`glucose` | glicose medida e glicose anterior enviada: atual − anterior | glicose ausente/phantom, ou histórico sem glicose |

Notas:

* **Modo demo (dev autorizado):** as *regras* continuam podendo usar phantom
  (inclusive para confirmar a 2ª leitura com glicose phantom — comportamento de dev
  inalterado); `context_informed` não reflete isso de propósito (proveniência
  medida). Em produção/Cloud Run o phantom é impossível e, quando há par medido,
  `context_informed.consecutive_valid` == valor usado pelas regras (teste
  `test_c_without_phantom_export_matches_rule_input`).
* **Histórico (`previous_reading`/`basal`)** é tratado como valor medido
  informado pelo cliente; o servidor não reidrata histórico próprio.
* `vitals_used` **inalterado** nesta rodada.
* Testes: `tests/test_context_informed_provenance.py` — (a) glicose phantom 250 ×
  anterior 250 em dev autorizado ⇒ `consecutive_valid`/`glucose_delta` `null`, nenhum
  phantom em `context_informed`; (b) `_hband.preprandial=true` ⇒ `fasting` `null`
  (cálculo não consome; regra inalterada) + toda fonte declarada é consumida e
  exportada; (c) histórico sem medida comparável ⇒ comparações `null`.

## Proposta para sair de DRAFT

Critérios propostos (a validar com Rafael) para promover este contrato a
**ACEITO**:

1. **Revisão clínica** (Rafael) da tabela de proveniência acima, em especial:
   tolerâncias da 2ª leitura (SpO2 ±1 pp, glicose ±15 mg/dL) e se `rest` derivado
   de `activity_level` < 20 deve continuar valendo como "informado".
2. **Decisão sobre aliases do schema** (`fasting_or_preprandial`, `at_rest`,
   `consecutive_count`, `steps_drop_consecutive_days`, `_hband.preprandial`,
   `_hband.fall_suspected`): mapear para o cálculo (muda comportamento das regras,
   PR própria com testes de matriz) **ou** documentar como não suportados no
   OpenAPI. Até lá permanecem `null`.
3. **Decisão de `skin_temp`** (aguardando Rafael) refletida em `vitals_used.temp_c`.
4. **OpenAPI**: publicar `vitals_used` e `context_informed` (todas as chaves
   anuláveis, ordem estável) em `docs/openapi/hband-wearable.yaml`.
5. **Consumidores**: reconfirmar o levantamento abaixo na data da promoção
   (nenhum lê `vitals_used` hoje).
6. **Piloto**: revisão no-traffic (`pilot-comp`) com smokes verdes
   (ingest sintético ⇒ `context_informed` todo `null`; `_hband.preprandial` ⇒
   `fasting` `null`) e logs sem `phantom`.
7. Ao promover: trocar status para **ACEITO**, registrar data/SHA e remover esta seção.

## Modo phantom/demo (isolamento)

Estimativas (PA/glicose phantom, defaults de sono/passos/FC-basal) só rodam com
**ambos**: `ALERT_ALLOW_PHANTOM_VITALS=1` **e** `ENVIRONMENT`/`APP_ENV` em
`development|dev|local|test|testing` (nenhum dos dois pode ser
`production|prod|staging`), **e** fora do Cloud Run (`K_SERVICE`, `K_REVISION`,
`K_CONFIGURATION`, `CLOUD_RUN_JOB` ausentes). Em qualquer outro caso o flag e o
parâmetro `allow_phantom_vitals=True` são ignorados (fail-closed) e o log emite
uma vez `WARNING phantom_vitals=blocked reason=… requested_via=env|param`. A imagem
secure define `ENVIRONMENT=production` e roda no Cloud Run ⇒ phantom impossível.

## Consumidores de `vitals_used` / campos da resposta do ingest

Levantamento em 2026-09-26 (core `leanderdulac/healthtech` na PR #22; somente
leitura: `rafaeldepaulafigo-web/next2u-web@0f3ee93`,
`rafaeldepaulafigo-web/next2u-acs-tablet@eabbe8b`, `leanderdulac/HBand-@f35d12b`).

| Repo | Arquivo | Usa | Quebra? |
|---|---|---|---|
| healthtech | `tests/test_ingest_no_vital_imputation.py`, `tests/test_phantom_vitals_isolation.py` | `vitals_used`, `context_informed`, `source_meta` | Não (testes da própria mudança) |
| healthtech | `src/api_server.py`, `src/api_monolith_runtime.py`, `saude_responsiva_secure/app/services/signal_core.py`, `run_e2e_smoke.py` | chamam `assess_ingest_alerts` e repassam `clinical_alerts` inteiro | Não (não leem `vitals_used`) |
| healthtech | `dashboard/app.js` | `raw_telemetry`, `cleaned_telemetry`, `phantom_data` (`phantomOr(..., null)`) | Não: `phantom_data = {}` vira `null` na UI de PA/glicose (antes mostrava PA phantom) |
| healthtech | `companion-android/.../net/dto/Models.kt`, `.../ui/MainScreen.kt` (`ClinicalAlertBlock`) | `clinical_alerts` como `Map<String, Any?>`: `is_true_alert`, `severity`, `primary_alert_name`, `primary_rule_id`, `care_line`, `decision` | Não (não lê `vitals_used`; mapa genérico tolera chave nova) |
| HBand- | `app/src/main/java/com/example/data/model/WearableData.kt` (`IngestResponse`), `.../net/HealthtechRepository.kt`, `.../data/remote/HealthTechApiService.kt` | POST ingest; `IngestResponse(success, message, id, processedAt)` via Moshi | Não (ignora `clinical_alerts`) |
| next2u-web | `src/server/healthtech/wearables.ts`, `paths.ts`, `client.ts` | `GET /wearables/patient/{id}/latest` e `/wearables/devices`; parser de latest devolve só `{status:'available'}` | Não (não lê `clinical_alerts`/`vitals_used`) |
| next2u-acs-tablet | — | nenhuma chamada ao ingest/HealthTech Core | Não |

Nenhum consumidor conhecido lê `vitals_used`; a mudança é compatível para todos
os clientes levantados. Clientes futuros devem tratar todas as chaves de
`vitals_used` e `context_informed` como anuláveis.
