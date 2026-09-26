# `clinical_alerts.vitals_used` / `context_informed` — contrato do ingest (PR #22)

**Status:** DRAFT (PR #22, revisão Rafael) · **Endpoint:** `POST /api/v1/wearables/ingest`
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
  valor só quando derivado de dado efetivamente enviado pelo cliente (ou de PA/glicose
  **medidas**); caso contrário `null`. Phantom nunca aparece aqui, nem no modo demo.

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
| 14 | `consecutive_valid` | float · 1.0 | `context_informed.consecutive_valid` | int \| null | só se `previous_reading`/`previous_vitals` enviado |
| 15 | `rest` | float 0/1 · 0.0 | `context_informed.rest` | bool \| null | chave `rest` ou `activity_level` medido (<20 ⇒ repouso) |
| 16 | `fasting` | float 0/1 · 0.0 | `context_informed.fasting` | bool \| null | chave `fasting`/`preprandial` |
| 17 | `steps_interrupted` | float 0/1 · 0.0 | `context_informed.steps_interrupted` | bool \| null | chave `steps_interrupted`/`fall_suspected` |
| 18 | `sleep_hours` | float · 8.0 | `context_informed.sleep_hours` | float \| null | chave `sleep_hours` |
| 19 | `steps_drop_days` | float · 0.0 | `context_informed.steps_drop_days` | int \| null | chave `steps_drop_days` |
| 20 | `pas_rise_vs_basal` | float · 0.0 | `context_informed.pas_rise_vs_basal` | float \| null | PAS medida − `basal.pas` |
| 21 | `pas_drop_vs_basal` | float · 0.0 | `context_informed.pas_drop_vs_basal` | float \| null | `basal.pas` − PAS medida |
| 22 | `glucose_delta` | float · 0.0 | `context_informed.glucose_delta` | float \| null | glicose medida − `previous_reading.glucose_mgdl` |

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
