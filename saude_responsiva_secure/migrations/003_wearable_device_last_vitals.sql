-- Snapshot O(1) do último SpO₂ / passos / pressão válidos por device.
-- Preenchido no ingest; a listagem da frota não precisa varrer wearable_readings.
CREATE TABLE IF NOT EXISTS wearable_device_last_vitals (
    device_id TEXT PRIMARY KEY,
    spo2 DOUBLE PRECISION,
    last_spo2_at TIMESTAMPTZ,
    steps DOUBLE PRECISION,
    last_steps_at TIMESTAMPTZ,
    blood_pressure_sys DOUBLE PRECISION,
    blood_pressure_dia DOUBLE PRECISION,
    last_bp_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL
);
