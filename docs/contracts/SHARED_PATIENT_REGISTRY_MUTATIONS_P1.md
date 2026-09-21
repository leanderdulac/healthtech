# CONTRATO CORE — Cadastro compartilhado (mutações) P1

**Status:** **DRAFT** (esqueleto para workshop — **não** implementar como CONFIRMED)  
**Data:** 2026-09-21  
**Autoridade proposta:** Leandro França de Mello (`leanderdulac`) — HealthTech Core  
**Consumidores:** Next2U Web (Rafael), tablet ACS (**TBD**), app paciente (**TBD**)  
**OpenAPI:** [shared-patient-registry-mutations-p1.yaml](./shared-patient-registry-mutations-p1.yaml)  
**Depende de (CONFIRMED):**
- [PATIENT_TERRITORY_AUTHZ_P0.md](./PATIENT_TERRITORY_AUTHZ_P0.md)
- [AUTHORIZED_PATIENT_ENUMERATION_P0.md](./AUTHORIZED_PATIENT_ENUMERATION_P0.md)
- [NEXT2U_INTEGRATION_P0_PATIENT_READS.md](./NEXT2U_INTEGRATION_P0_PATIENT_READS.md)

## Objetivo

Um único `patient_id` canônico no Core para Web, ACS e app paciente: criar, editar, pesquisar, deduplicar, vincular território/ACS/cuidador, consentimentos e anexos — com versão e conflito de escrita concorrente.

## Fora de escopo deste DRAFT

- Autenticação do profissional / ACS / paciente (Identity / IdP — frente 2).
- OS / visita / offline ACS (frentes 3–4).
- Cálculo oficial de risco (frente 6) — só pode **referenciar** `patient_id` + `registry_version`.

## Princípios

1. **Core é fonte de verdade** do cadastro e do território ativo (`municipality_id` + `ubs_id`).
2. Credencial BFF→Core continua `X-API-Key` de **serviço**. Identidade humana fica no BFF.
3. `ubs_id` ≡ `health_unit_id` (igualdade de string) — igual P0.
4. Território indefinido **pode** existir no cadastro, mas **não** entra na enumeração autorizada P0.
5. POST exige `Idempotency-Key`; PATCH exige `If-Match: {registry_version}`.
6. Conflito de versão → **409** com representação atual.
7. Dedup **sugere** candidatos; **merge** é explícito e auditado (nunca automático).

## Endpoints (proposta)

| Método | Path | Função |
| --- | --- | --- |
| `POST` | `/api/v1/patients` | Criar → `patient_id` |
| `PATCH` | `/api/v1/patients/{patient_id}` | Atualizar; `If-Match` |
| `GET` | `/api/v1/patients` / `/{id}` | Já CONFIRMED P0 (+ `registry_version` no DRAFT) |
| `POST` | `/api/v1/patients/search` | Pesquisa cadastral |
| `POST` | `/api/v1/patients/dedup/candidates` | Candidatos de duplicata |
| `POST` | `/api/v1/patients/{patient_id}/merge` | Fundir duplicata |
| `PUT` | `/api/v1/patients/{patient_id}/links` | ACS / cuidador / programas |
| `GET`/`PUT` | `/api/v1/patients/{patient_id}/consents` | Consentimentos |
| `GET`/`POST` | `/api/v1/patients/{patient_id}/attachments` | Metadados + URL assinada |
| `GET` | `/api/v1/patients/{patient_id}/history` | Histórico de versões |

## Campos

**Hoje no GET operacional:** `patient_id`, `display_name`, `phone`, `caregiver_phone`, `programs`, `diseases`, `isolation_social`, `is_demo`, `municipality_id`, `ubs_id`, `created_at`, `updated_at`.

**P1 (proposta):** `registry_version`, `cpf_fingerprint` (nunca CPF cru), `birth_date`, `sex`, `address`, links ACS/cuidador, `clinical_flags`, resumo de consentimentos.

## Workshop — decisões obrigatórias

- [ ] Quem gera `patient_id` (Core UUID vs prefixo territorial)?
- [ ] CPF: só fingerprint no Core ou vault separado?
- [ ] Merge: papel autorizador; wearables/visitas órfãs?
- [ ] Anexos: bucket + retenção LGPD?
- [ ] Escopos: `patients:write` vs `patients:merge` vs `patients:consent`?
- [ ] ACS/app paciente: mesma surface via BFF ou subset?

## Critério para promover a CONFIRMED

OpenAPI revisada por Core + Rafael + dono ACS; smoke staging com 2 writers concorrentes (409); seed Slice 3 alinhado; BFF não recalcula território.
