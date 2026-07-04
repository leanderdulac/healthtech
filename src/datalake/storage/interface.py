from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Optional

import pandas as pd

from src.datalake.schemas.base import DataLayer


class LakehouseStore(ABC):
    """Contrato de persistência do lakehouse — abstrai BigQuery/GCS/Parquet local."""

    @abstractmethod
    def write_bronze(self, df: pd.DataFrame, partition_date: date) -> int:
        ...

    @abstractmethod
    def write_silver(self, df: pd.DataFrame, partition_date: date) -> int:
        ...

    @abstractmethod
    def write_gold(
        self,
        table: str,
        df: pd.DataFrame,
        partition_date: Optional[date] = None,
    ) -> int:
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def list_partitions(self, layer: DataLayer, table: Optional[str] = None) -> List[str]:
        ...

    @abstractmethod
    def get_lineage(self) -> pd.DataFrame:
        ...