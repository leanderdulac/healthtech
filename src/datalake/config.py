from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LakehouseConfig:
    """Configuração central do lakehouse de telemetria."""

    base_path: Path = field(default_factory=lambda: Path("data/lakehouse"))
    project_id: str = "healthtech-local"
    dataset: str = "telemetry_datalake"

    # Janelas de reconciliação e agregação
    reconciliation_window_seconds: int = 5
    gold_hourly_window: str = "1h"
    gold_daily_window: str = "1D"

    # Limites fisiológicos para validação
    hr_min_valid: int = 30
    hr_max_valid: int = 220
    spo2_min_valid: int = 70
    spo2_max_valid: int = 100
    hrv_min_valid: int = 5
    hrv_max_valid: int = 250

    # Qualidade mínima aceitável (0-1)
    min_quality_score: float = 0.6
    min_coverage_ratio_24h: float = 0.85

    @property
    def bronze_path(self) -> Path:
        return self.base_path / "bronze"

    @property
    def silver_path(self) -> Path:
        return self.base_path / "silver"

    @property
    def gold_path(self) -> Path:
        return self.base_path / "gold"

    @property
    def metadata_path(self) -> Path:
        return self.base_path / "_metadata"

    def ensure_directories(self) -> None:
        for path in (
            self.bronze_path,
            self.silver_path,
            self.gold_path,
            self.metadata_path,
        ):
            path.mkdir(parents=True, exist_ok=True)