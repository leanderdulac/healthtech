-- 003_wearable_event_time_indexes.sql
-- Índices da ordenação real (COALESCE(measured_at, received_at)), para a
-- última leitura por paciente ou aparelho não ordenar a tabela inteira.
-- Aditivo e idempotente. CREATE INDEX (não CONCURRENTLY) cabe na transação
-- de apply_schema(); a escrita trava só enquanto o índice é construído.

CREATE INDEX IF NOT EXISTS ix_wearable_readings_patient_event
    ON wearable_readings (
        patient_id,
        (COALESCE(measured_at, received_at)) DESC,
        received_at DESC,
        created_at DESC
    );

CREATE INDEX IF NOT EXISTS ix_wearable_readings_device_event
    ON wearable_readings (
        device_id,
        (COALESCE(measured_at, received_at)) DESC,
        received_at DESC
    );
