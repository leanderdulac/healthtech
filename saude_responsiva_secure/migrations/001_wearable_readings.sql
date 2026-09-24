-- 001_wearable_readings.sql
-- Cloud SQL: healthtech-pg (project healthtech-gcp-2026)
-- Idempotent. Same DATABASE_URL as enrollments / GET /api/v1/patients.
-- Apply: PYTHONPATH=. python -m app.services.durable_readings
--     or python scripts/apply_wearable_readings_migration.py

CREATE TABLE IF NOT EXISTS wearable_readings (
    reading_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    value DOUBLE PRECISION,
    unit TEXT,
    measured_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    client_reading_id TEXT,
    idempotency_key TEXT,
    natural_patient_id TEXT,
    natural_device_id TEXT,
    natural_measured_at TIMESTAMPTZ,
    natural_metric_type TEXT,
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    frame JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE wearable_readings IS
    'Leituras de wearable persistidas. Dedup via índices únicos parciais.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_wearable_readings_client_reading
    ON wearable_readings (patient_id, client_reading_id)
    WHERE client_reading_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_wearable_readings_idempotency
    ON wearable_readings (patient_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_wearable_readings_natural
    ON wearable_readings (
        natural_patient_id,
        natural_device_id,
        natural_measured_at,
        natural_metric_type
    )
    WHERE natural_measured_at IS NOT NULL
      AND natural_patient_id IS NOT NULL
      AND natural_device_id IS NOT NULL
      AND natural_metric_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_wearable_readings_patient_time
    ON wearable_readings (patient_id, received_at DESC);

CREATE INDEX IF NOT EXISTS ix_wearable_readings_device_time
    ON wearable_readings (device_id, received_at DESC);
