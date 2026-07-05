from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint

from database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String(64), unique=True, index=True, nullable=False)
    display_name = Column(String(128), default="")
    birth_year = Column(Integer, nullable=True)
    risk_factor = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TelemetryRecord(Base):
    __tablename__ = "telemetry_records"
    __table_args__ = (UniqueConstraint("event_id", name="uq_event_id"),)

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(32), nullable=False, index=True)
    patient_id = Column(String(64), index=True, nullable=False)
    source = Column(String(32), nullable=False)
    metric_type = Column(String(32), nullable=False)
    metric_value = Column(Float, nullable=False)
    unit = Column(String(16), default="")
    vendor = Column(String(32), default="")
    timestamp_utc = Column(DateTime, index=True, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)


class ClinicalSnapshot(Base):
    __tablename__ = "clinical_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String(64), index=True, nullable=False)
    conditions_json = Column(Text, default="[]")
    medications_json = Column(Text, default="[]")
    fhir_live = Column(Integer, default=0)
    synced_at = Column(DateTime, default=datetime.utcnow)


class PredictionSnapshot(Base):
    __tablename__ = "prediction_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String(64), index=True, nullable=False)
    prob_6h = Column(Float, default=0.0)
    prob_24h = Column(Float, default=0.0)
    prob_72h = Column(Float, default=0.0)
    horizon_at_risk = Column(String(8), default="")
    conformal_json = Column(Text, default="{}")
    modo = Column(String(64), default="")
    predicted_at = Column(DateTime, default=datetime.utcnow)


class AggregationRun(Base):
    __tablename__ = "aggregation_runs"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(String(64), index=True, nullable=True)
    sources_json = Column(Text, default="[]")
    telemetry_count = Column(Integer, default=0)
    status = Column(String(32), default="pending")
    detail_json = Column(Text, default="{}")
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)