"""A frota não pode detoastar frame/extra de todas as leituras."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import durable_readings  # noqa: E402

INDEX_SQL = SECURE / "migrations" / "006_wearable_device_latest_index.sql"
INDEX_SCRIPT = ROOT / "scripts" / "create_device_latest_index.py"


@pytest.mark.critical
def test_fleet_queries_do_not_read_frame_in_bulk():
    ids_sql = durable_readings._PG_LATEST_IDS_BY_DEVICE
    labels_sql = durable_readings._PG_LATEST_LABEL_BY_DEVICE
    frames_sql = durable_readings._PG_FRAMES_BY_IDS
    assert "frame" not in ids_sql
    assert "extra" not in ids_sql
    assert "DISTINCT ON (device_id)" in ids_sql
    assert "COALESCE(measured_at, received_at) DESC" in ids_sql
    assert "extra" not in labels_sql
    assert "frame" not in labels_sql
    assert "device_label IS NOT NULL" in labels_sql
    assert "reading_id = ANY(:reading_ids)" in frames_sql
    assert "frame" in frames_sql
    index_sql = INDEX_SQL.read_text(encoding="utf-8")
    assert "CREATE INDEX CONCURRENTLY" in index_sql
    assert "ix_wearable_readings_device_latest" in index_sql
    assert "frame" not in index_sql.lower().split("include")[-1]
    assert "006_wearable_device_latest_index.sql" not in durable_readings.MIGRATION_NAMES
    boot = Path(durable_readings.__file__).read_text(encoding="utf-8")
    assert 'if "CONCURRENTLY" in chunk.upper()' in boot


def test_postgres_fleet_fetches_frame_only_for_latest_ids():
    calls = []

    class _Row:
        def __init__(self, **kwargs):
            self._mapping = kwargs

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class _Conn:
        def execute(self, statement, params=None):
            sql = str(statement)
            calls.append((sql, params))
            if "DISTINCT ON" in sql and "device_label" in sql and "reading_id" not in sql:
                assert "extra" not in sql
                return _Result([_Row(device_id="bi1.dev", device_label="Relogio sintetico")])
            if "DISTINCT ON" in sql:
                assert "frame" not in sql
                assert "extra" not in sql
                return _Result([_Row(reading_id="new", device_id="bi1.dev")])
            assert "ANY" in sql
            assert params is not None
            assert list(params["reading_ids"]) == ["new"]
            return _Result(
                [
                    _Row(
                        reading_id="new",
                        patient_id="bi1.pat",
                        device_id="bi1.dev",
                        device_label=None,
                        metric_type="heart_rate",
                        client_reading_id="c1",
                        extra={},
                        frame={
                            "patient_id": "PAT-FLEET",
                            "device_id": "DEV-SYN-FLEET",
                            "timestamp": "2026-11-25T18:00:00Z",
                            "raw_telemetry": {"heart_rate_bpm": 70},
                        },
                    )
                ]
            )

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    frames = durable_readings._pg_latest_frames_by_device(_Engine())
    assert len(calls) == 3
    assert "frame" not in calls[0][0]
    assert "extra" not in calls[0][0]
    assert "frame" in calls[1][0]
    assert list(calls[1][1]["reading_ids"]) == ["new"]
    assert "extra" not in calls[2][0]
    assert len(frames) == 1
    assert frames[0]["patient_id"] == "PAT-FLEET"
    assert frames[0]["device_id"] == "DEV-SYN-FLEET"
    assert frames[0]["device_label"] == "Relogio sintetico"
    assert frames[0]["raw_telemetry"]["heart_rate_bpm"] == 70


def test_latest_index_script_refuses_without_confirm():
    env = os.environ.copy()
    env.pop("CREATE_DEVICE_LATEST_INDEX_CONFIRM", None)
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, str(INDEX_SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "CREATE_DEVICE_LATEST_INDEX_CONFIRM" in result.stderr
    assert "DATABASE_URL=" not in result.stderr
