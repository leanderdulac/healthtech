"""Testes de agregação diária (pandas) sem PostgreSQL."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

AGG_ROOT = Path(__file__).resolve().parents[1] / "health-aggregator"
sys.path.insert(0, str(AGG_ROOT))

from database import Base  # noqa: E402
from models import HealthRecord  # noqa: E402
from aggregator import HealthAggregator  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_normalize_and_save_and_daily_aggregate(db_session):
    records = [
        {
            "timestamp": "2026-07-01T08:00:00+00:00",
            "steps": 4000,
            "heart_rate_bpm": 70,
            "calories_burned": 200,
            "spo2": 98,
            "sleep_duration_min": 0,
        },
        {
            "timestamp": "2026-07-01T20:00:00+00:00",
            "steps": 3000,
            "heart_rate_bpm": 80,
            "calories_burned": 150,
            "spo2": 97,
            "sleep_duration_min": 420,
        },
    ]
    HealthAggregator.normalize_and_save(db_session, records, "apple", "user-1")

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 2, tzinfo=timezone.utc)
    daily = HealthAggregator.get_daily_aggregate(db_session, "user-1", start, end)

    assert len(daily) == 1
    assert daily[0]["steps"] == 7000
    assert daily[0]["heart_rate_bpm"] == 75.0
    assert "overall_score" in daily[0]

    schemas = HealthAggregator.daily_to_schema(daily)
    assert schemas[0].total_steps == 7000
