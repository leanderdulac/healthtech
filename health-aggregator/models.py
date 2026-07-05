import uuid

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from database import Base


class HealthRecord(Base):
    __tablename__ = "health_records"

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(String, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True)
    source = Column(String, index=True)  # google, samsung, apple, fhir, tcn
    timestamp = Column(DateTime, default=func.now())
    date = Column(String, index=True)  # YYYY-MM-DD para agregação

    steps = Column(Integer, default=0)
    heart_rate_bpm = Column(Float, default=None)
    hrv = Column(Float, default=None)
    spo2 = Column(Float, default=None)
    calories_burned = Column(Float, default=0)
    sleep_duration_min = Column(Integer, default=0)
    weight = Column(Float, default=None)
    body_fat = Column(Float, default=None)

    raw_data = Column(JSON)


class AggregationRun(Base):
    __tablename__ = "aggregation_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, nullable=True)
    sources_json = Column(Text, default="[]")
    records_count = Column(Integer, default=0)
    status = Column(String(32), default="pending")
    detail_json = Column(Text, default="{}")
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)