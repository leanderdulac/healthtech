"""Testes de quality gates do datalake."""

from __future__ import annotations

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.quality.quality_gates import QualityGateRunner


def test_gate_bronze_to_silver_empty():
    runner = QualityGateRunner(LakehouseConfig())
    report = runner.gate_bronze_to_silver(pd.DataFrame(), pd.DataFrame())
    assert report.passed is False
    assert report.total_records == 0


def test_gate_bronze_to_silver_ok():
    runner = QualityGateRunner(LakehouseConfig())
    bronze = pd.DataFrame({
        "signal_confidence": [0.9, 0.8, 0.7, 0.95],
    })
    silver = pd.DataFrame({
        "quality_score": [0.9, 0.85, 0.8],
    })
    report = runner.gate_bronze_to_silver(bronze, silver)
    assert report.checks["bronze_has_data"] is True
    assert report.checks["silver_produced"] is True
    assert report.checks["reasonable_retention"] is True
    assert report.passed is True


def test_gate_silver_to_gold_requires_aggregations():
    runner = QualityGateRunner(LakehouseConfig())
    silver = pd.DataFrame({"patient_id": ["p1", "p2"]})
    report = runner.gate_silver_to_gold(
        silver,
        gold_hourly=pd.DataFrame({"h": [1]}),
        gold_daily=pd.DataFrame(),
    )
    assert report.checks["gold_daily_produced"] is False
    assert report.passed is False
