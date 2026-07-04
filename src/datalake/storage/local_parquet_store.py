import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DataLayer
from src.datalake.storage.interface import LakehouseStore

logger = logging.getLogger(__name__)


class LocalParquetStore(LakehouseStore):
    """Implementação local em Parquet particionado por data."""

    LAYER_TABLES = {
        DataLayer.BRONZE: "telemetry_raw",
        DataLayer.SILVER: "telemetry_curated",
    }

    def __init__(self, config: LakehouseConfig):
        self.config = config
        self.config.ensure_directories()
        self._lineage_path = config.metadata_path / "lineage.jsonl"

    def _layer_path(self, layer: DataLayer, table: Optional[str] = None) -> Path:
        if layer in (DataLayer.BRONZE, DataLayer.SILVER):
            table_name = table or self.LAYER_TABLES[layer]
            base = self.config.bronze_path if layer == DataLayer.BRONZE else self.config.silver_path
            return base / table_name
        return self.config.gold_path / (table or "default")

    def _partition_path(self, layer: DataLayer, partition_date: date, table: Optional[str] = None) -> Path:
        return self._layer_path(layer, table) / f"partition_date={partition_date.isoformat()}"

    def _append_lineage(self, event: dict) -> None:
        event["recorded_at"] = datetime.utcnow().isoformat()
        with open(self._lineage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def write_bronze(self, df: pd.DataFrame, partition_date: date) -> int:
        return self._write_partitioned(DataLayer.BRONZE, df, partition_date)

    def write_silver(self, df: pd.DataFrame, partition_date: date) -> int:
        return self._write_partitioned(DataLayer.SILVER, df, partition_date)

    def write_gold(
        self,
        table: str,
        df: pd.DataFrame,
        partition_date: Optional[date] = None,
    ) -> int:
        if df.empty:
            return 0

        if partition_date:
            target = self._partition_path(DataLayer.GOLD, partition_date, table)
        else:
            target = self._layer_path(DataLayer.GOLD, table)

        target.mkdir(parents=True, exist_ok=True)
        file_path = target / f"data_{datetime.utcnow().strftime('%H%M%S%f')}.parquet"
        df.to_parquet(file_path, index=False)

        self._append_lineage({
            "layer": DataLayer.GOLD.value,
            "table": table,
            "partition_date": partition_date.isoformat() if partition_date else None,
            "rows": len(df),
            "path": str(file_path),
            "operation": "write",
        })
        logger.info("Gold %s: %d registros em %s", table, len(df), file_path)
        return len(df)

    def _write_partitioned(self, layer: DataLayer, df: pd.DataFrame, partition_date: date) -> int:
        if df.empty:
            return 0

        target = self._partition_path(layer, partition_date)
        target.mkdir(parents=True, exist_ok=True)
        file_path = target / f"batch_{datetime.utcnow().strftime('%H%M%S%f')}.parquet"
        df.to_parquet(file_path, index=False)

        self._append_lineage({
            "layer": layer.value,
            "table": self.LAYER_TABLES[layer],
            "partition_date": partition_date.isoformat(),
            "rows": len(df),
            "path": str(file_path),
            "operation": "write",
        })
        logger.info("%s: %d registros em %s", layer.value, len(df), file_path)
        return len(df)

    def read_layer(
        self,
        layer: DataLayer,
        table: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        patient_id: Optional[str] = None,
        patient_ids: Optional[List[str]] = None,
        partition_dates: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        base = self._layer_path(layer, table)
        if not base.exists():
            return pd.DataFrame()

        files = list(base.rglob("*.parquet"))
        if not files:
            return pd.DataFrame()

        if partition_dates:
            files = [
                f for f in files
                if any(f"partition_date={d}" in str(f) for d in partition_dates)
            ]

        if not files:
            return pd.DataFrame()

        df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)

        if patient_id:
            df = df[df["patient_id"] == patient_id]
        elif patient_ids:
            df = df[df["patient_id"].isin(patient_ids)]

        time_col = self._resolve_time_column(layer, df)
        if time_col and (start_time or end_time):
            df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
            if start_time:
                df = df[df[time_col] >= pd.Timestamp(start_time, tz="UTC")]
            if end_time:
                df = df[df[time_col] <= pd.Timestamp(end_time, tz="UTC")]

        return df.reset_index(drop=True)

    @staticmethod
    def _resolve_time_column(layer: DataLayer, df: pd.DataFrame) -> Optional[str]:
        candidates = {
            DataLayer.BRONZE: ["timestamp_utc"],
            DataLayer.SILVER: ["window_start"],
            DataLayer.GOLD: ["hour_bucket", "summary_date", "window_start"],
        }
        for col in candidates.get(layer, []):
            if col in df.columns:
                return col
        return None

    def list_partitions(self, layer: DataLayer, table: Optional[str] = None) -> List[str]:
        base = self._layer_path(layer, table)
        if not base.exists():
            return []
        return sorted({
            p.name.replace("partition_date=", "")
            for p in base.rglob("partition_date=*")
            if p.is_dir()
        })

    def get_lineage(self) -> pd.DataFrame:
        if not self._lineage_path.exists():
            return pd.DataFrame()
        records = []
        with open(self._lineage_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return pd.DataFrame(records)