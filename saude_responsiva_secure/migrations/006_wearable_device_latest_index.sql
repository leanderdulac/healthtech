-- 006_wearable_device_latest_index.sql
-- Cloud SQL: healthtech-pg (project healthtech-gcp-2026)
--
-- FORA do boot. CREATE INDEX CONCURRENTLY não pode rodar dentro da
-- transação de apply_schema (001–004). Não está em MIGRATION_NAMES.
--
-- A frota pede a última leitura por device_id (claro ou índice cego bi1.).
-- O índice cobre essa ordem sem abrir frame/extra (TOAST).
--
-- Aplicar com:
--   CREATE_DEVICE_LATEST_INDEX_CONFIRM=yes \
--   DATABASE_URL="$DATABASE_URL" \
--   python scripts/create_device_latest_index.py
--
-- Se a criação concorrente falhar no meio, o índice fica inválido:
--   DROP INDEX CONCURRENTLY IF EXISTS ix_wearable_readings_device_latest;
-- e rode o script de novo.

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_wearable_readings_device_latest
    ON wearable_readings (
        device_id,
        (COALESCE(measured_at, received_at)) DESC,
        received_at DESC
    )
    INCLUDE (reading_id, device_label);
