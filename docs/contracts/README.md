# HealthTech Core — contratos

| Documento | Status |
| --- | --- |
| [WEARABLE_INGEST_IDEMPOTENCY.md](./WEARABLE_INGEST_IDEMPOTENCY.md) | **CONFIRMED** — dedup / idempotência de `POST /wearables/ingest` e `batch-ingest` |
| [INGEST_VITALS_USED_CONTRACT.md](./INGEST_VITALS_USED_CONTRACT.md) | **DRAFT** — `clinical_alerts.vitals_used` (22→10, sem imputação) + `context_informed` + isolamento do phantom (PR #22) |
| [PATIENT_TERRITORY_AUTHZ_P0.md](./PATIENT_TERRITORY_AUTHZ_P0.md) | **CONFIRMED** — território Patient para authz Next2U P0 |
| [NEXT2U_INTEGRATION_P0_PATIENT_READS.md](./NEXT2U_INTEGRATION_P0_PATIENT_READS.md) | Guia de integração Next2U (Rafael) |
| [AUTHORIZED_PATIENT_ENUMERATION_P0.md](./AUTHORIZED_PATIENT_ENUMERATION_P0.md) | **CONFIRMED** — enumeração autorizada (authz-before-page) + devices por Patient |
| [SHARED_PATIENT_REGISTRY_MUTATIONS_P1.md](./SHARED_PATIENT_REGISTRY_MUTATIONS_P1.md) + [shared-patient-registry-mutations-p1.yaml](./shared-patient-registry-mutations-p1.yaml) | **DRAFT** — cadastro compartilhado (mutação / dedup / consent / anexo) |
