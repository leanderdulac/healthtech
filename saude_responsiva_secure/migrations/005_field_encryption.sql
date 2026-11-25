-- 005_field_encryption.sql
-- Cloud SQL: healthtech-pg (project healthtech-gcp-2026)
--
-- NÃO entra no boot da API (não está em MIGRATION_NAMES).
-- Aplicar só com o OK do Leandro, via:
--   BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \
--   python scripts/backfill_field_encryption.py --apply-schema
--
-- Aditiva e idempotente. Não apaga leitura nem cadastro.
-- O frame/extra de wearable_readings e o índice cego usam as colunas
-- que já existem. Este arquivo só acrescenta o ciphertext dos vitais
-- de snapshot e dos vínculos device→paciente.

ALTER TABLE wearable_device_last_vitals ADD COLUMN IF NOT EXISTS spo2_enc TEXT;
ALTER TABLE wearable_device_last_vitals ADD COLUMN IF NOT EXISTS steps_enc TEXT;
ALTER TABLE wearable_device_last_vitals ADD COLUMN IF NOT EXISTS blood_pressure_sys_enc TEXT;
ALTER TABLE wearable_device_last_vitals ADD COLUMN IF NOT EXISTS blood_pressure_dia_enc TEXT;

COMMENT ON COLUMN wearable_device_last_vitals.spo2_enc IS
    'SpO2 cifrado (enc1 AES-256-GCM). A coluna numérica fica NULL quando esta está preenchida.';
COMMENT ON COLUMN wearable_device_last_vitals.steps_enc IS
    'Passos cifrados (enc1). A coluna numérica fica NULL quando esta está preenchida.';
COMMENT ON COLUMN wearable_device_last_vitals.blood_pressure_sys_enc IS
    'Pressão sistólica cifrada (enc1).';
COMMENT ON COLUMN wearable_device_last_vitals.blood_pressure_dia_enc IS
    'Pressão diastólica cifrada (enc1).';

ALTER TABLE device_patient_overrides ADD COLUMN IF NOT EXISTS device_id_enc TEXT;
ALTER TABLE device_patient_overrides ADD COLUMN IF NOT EXISTS patient_id_enc TEXT;

COMMENT ON COLUMN device_patient_overrides.device_id_enc IS
    'device_id reversível (enc1). A PK passa a ser o índice cego bi1.';
COMMENT ON COLUMN device_patient_overrides.patient_id_enc IS
    'patient_id reversível (enc1). A coluna patient_id passa a ser o índice cego bi1.';
