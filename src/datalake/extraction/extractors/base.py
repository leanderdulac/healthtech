from abc import ABC, abstractmethod

import pandas as pd

from src.datalake.extraction.filters import QueryFilters
from src.datalake.storage.interface import LakehouseStore


class BaseExtractor(ABC):
    """Contrato base para extractors especializados."""

    def __init__(self, store: LakehouseStore):
        self.store = store

    @abstractmethod
    def extract(self, filters: QueryFilters) -> pd.DataFrame:
        ...