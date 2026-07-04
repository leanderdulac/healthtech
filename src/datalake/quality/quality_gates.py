from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DataLayer


@dataclass
class QualityReport:
    layer: DataLayer
    passed: bool
    total_records: int
    valid_records: int
    invalid_records: int
    coverage_ratio: float
    checks: Dict[str, bool] = field(default_factory=dict)
    messages: List[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return self.valid_records / self.total_records


class QualityGateRunner:
    """Portões de qualidade entre camadas do lakehouse."""

    def __init__(self, config: LakehouseConfig):
        self.config = config

    def gate_bronze_to_silver(self, bronze_df: pd.DataFrame, silver_df: pd.DataFrame) -> QualityReport:
        checks: Dict[str, bool] = {}
        messages: List[str] = []

        total = len(bronze_df)
        valid_bronze = bronze_df[bronze_df.get("signal_confidence", 1.0) >= 0.5] if not bronze_df.empty else bronze_df
        checks["bronze_has_data"] = total > 0
        checks["silver_produced"] = len(silver_df) > 0

        if total > 0:
            retention = len(silver_df) / total
            checks["reasonable_retention"] = 0.05 <= retention <= 1.0
            if not checks["reasonable_retention"]:
                messages.append(f"Retenção bronze→silver atípica: {retention:.2%}")

        if not silver_df.empty and "quality_score" in silver_df.columns:
            avg_quality = silver_df["quality_score"].mean()
            checks["min_avg_quality"] = avg_quality >= self.config.min_quality_score
            if not checks["min_avg_quality"]:
                messages.append(f"Qualidade média silver abaixo do limiar: {avg_quality:.2f}")

        passed = all(checks.values()) if checks else False
        return QualityReport(
            layer=DataLayer.SILVER,
            passed=passed,
            total_records=total,
            valid_records=len(valid_bronze),
            invalid_records=total - len(valid_bronze),
            coverage_ratio=len(silver_df) / max(total, 1),
            checks=checks,
            messages=messages,
        )

    def gate_silver_to_gold(
        self,
        silver_df: pd.DataFrame,
        gold_hourly: pd.DataFrame,
        gold_daily: pd.DataFrame,
    ) -> QualityReport:
        checks: Dict[str, bool] = {}
        messages: List[str] = []

        total = len(silver_df)
        checks["silver_has_data"] = total > 0
        checks["gold_hourly_produced"] = len(gold_hourly) > 0
        checks["gold_daily_produced"] = len(gold_daily) > 0

        if not gold_daily.empty and "coverage_24h" in gold_daily.columns:
            min_cov = gold_daily["coverage_24h"].min()
            checks["min_coverage_24h"] = min_cov >= self.config.min_coverage_ratio_24h * 0.5
            if not checks["min_coverage_24h"]:
                messages.append(f"Cobertura 24h mínima baixa: {min_cov:.2%}")

        passed = all(checks.values()) if checks else False
        return QualityReport(
            layer=DataLayer.GOLD,
            passed=passed,
            total_records=total,
            valid_records=total,
            invalid_records=0,
            coverage_ratio=1.0,
            checks=checks,
            messages=messages,
        )