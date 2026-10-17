-- 002_wearable_device_label.sql
-- Cloud SQL: healthtech-pg (project healthtech-gcp-2026)
-- Aditiva e idempotente: coluna nullable, sem default, sem rewrite da tabela.
-- Revisões antigas continuam funcionando (INSERT com lista explícita de colunas).
-- Apply: PYTHONPATH=. python -m app.services.durable_readings
--     or python scripts/apply_wearable_readings_migration.py
-- Rollback (só se necessário): ALTER TABLE wearable_readings DROP COLUMN IF EXISTS device_label;

ALTER TABLE wearable_readings ADD COLUMN IF NOT EXISTS device_label TEXT;

COMMENT ON COLUMN wearable_readings.device_label IS
    'Apelido legível do aparelho que enviou (ex.: iPhone de LFM). Opcional, até 64 caracteres.';
