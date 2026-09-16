# Integração Next2U ← HealthTech Core — P0 leituras Patient/Wearables

**Para:** Rafael (implementação IAM Next2U)  
**De:** Core owner (`leanderdulac`)  
**Contrato de território:** [PATIENT_TERRITORY_AUTHZ_P0.md](./PATIENT_TERRITORY_AUTHZ_P0.md) — **CONFIRMED**

## Leituras Core confirmadas

| BFF Next2U | Core |
| --- | --- |
| `GET /api/patients` | `GET /api/v1/patients` |
| `GET /api/patients/{id}` | `GET /api/v1/patients/{id}` |
| `GET /api/wearables/patient/{id}/latest` | `GET /api/v1/wearables/patient/{id}/latest` |
| `GET /api/wearables/devices?patient_id=` | `GET /api/v1/wearables/devices` |

Credencial BFF→Core: `X-API-Key` de **serviço** (`wearables:read` / patients read conforme deploy). **Não** é identidade do profissional.

## Regra de autorização territorial (obrigatória)

```
territory_ok(patient):
  m = patient.municipality_id
  u = patient.ubs_id
  if m is null/missing/blank OR u is null/missing/blank:
    return False   # indefinido → fail-closed
  return True

in_scope(professional, patient):
  if not territory_ok(patient): return False
  # health_unit_id do assignment == ubs_id do patient (mesma string)
  return exists ACTIVE assignment of professional where
    assignment.municipality_id == patient.municipality_id
    AND assignment.health_unit_id == patient.ubs_id
  # (+ exceções de carteira se produto aprovar depois)
```

## Listagem

Capacidade server-side canônica: [AUTHORIZED_PATIENT_ENUMERATION_P0.md](./AUTHORIZED_PATIENT_ENUMERATION_P0.md).

- **Nunca** expor `total`/lista global do Core ao browser.
- Calcular `allowed` no **Core**: território definido ∩ escopos do assignment enviados como `territory` / `municipality_id`+`ubs_id`; paginar `allowed`; `total` = \|allowed\|.
- O BFF **não** filtra a página recebida e **não** varre offsets globais.
- Detalhe/latest: se não `in_scope` → **404** (preferido). Devices do Patient: `GET /api/v1/wearables/devices?patient_id=` (`coverage=patient`).

## Identity (Next2U)

- Guarda só profissional: binding, assignment (`municipality_id`, `health_unit_id`), capabilities.
- **Não** é fonte de verdade do território do paciente.
- Projeção local do território do Patient, se houver, é cache — Core vence.

## Respostas WhatsApp / ChatGPT

1. Território nos GETs Patient → **CONFIRMED** (ver PATIENT_TERRITORY_AUTHZ_P0.md §2)  
2. `ubs_id` ≡ `health_unit_id` → **CONFIRMED** (ver §3)

Implementar HANDOFF P0 com estas duas confirmações **e** a enumeração autorizada em AUTHORIZED_PATIENT_ENUMERATION_P0.md; remover “CORRECTION REQUIRED” / “BACKEND CONTRACT REQUIRED” para P09 / gate #30 nestes pontos.
