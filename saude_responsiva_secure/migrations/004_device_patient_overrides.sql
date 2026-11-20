-- 004_device_patient_overrides.sql
-- Cloud SQL: healthtech-pg (project healthtech-gcp-2026)
-- Aditiva e idempotente. Não apaga leituras.
-- Apply: python scripts/apply_wearable_readings_migration.py
-- Rollback da tabela (só se necessário, após remover o código):
--   ALTER TABLE wearable_readings DROP COLUMN IF EXISTS reported_patient_id;
--   DROP TABLE IF EXISTS device_patient_overrides;

CREATE TABLE IF NOT EXISTS device_patient_overrides (
    device_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    motivo TEXT
);

COMMENT ON TABLE device_patient_overrides IS
    'Vínculo canônico device→paciente. Prevalece sobre o patient_id enviado pelo app na ingestão e na frota/detalhe.';

COMMENT ON COLUMN device_patient_overrides.device_id IS
    'Identificador canônico do aparelho (MAC em maiúsculas quando aplicável).';

COMMENT ON COLUMN device_patient_overrides.patient_id IS
    'patient_id canônico que deve ser gravado e exibido.';

COMMENT ON COLUMN device_patient_overrides.created_by IS
    'Quem gravou o vínculo (chave mascarada; nunca a chave completa).';

COMMENT ON COLUMN device_patient_overrides.motivo IS
    'Motivo operacional do vínculo (sem dados clínicos).';

CREATE INDEX IF NOT EXISTS ix_device_patient_overrides_patient
    ON device_patient_overrides (patient_id);

ALTER TABLE wearable_readings ADD COLUMN IF NOT EXISTS reported_patient_id TEXT;

COMMENT ON COLUMN wearable_readings.reported_patient_id IS
    'patient_id enviado pelo app quando um vínculo canônico foi aplicado. Nulo se não houve override.';
