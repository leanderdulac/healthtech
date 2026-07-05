"""
Contrato base para adaptadores de ingestão real de wearables.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.datalake.schemas.bronze import BronzeTelemetryRecord


@dataclass
class AdapterResult:
    """Resultado padronizado de um adaptador de ingestão."""

    source: str
    records: List[BronzeTelemetryRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return len(self.records) > 0 and not self.errors

    @property
    def count(self) -> int:
        return len(self.records)


class TelemetryAdapter(ABC):
    """Interface para fontes reais de telemetria wearable."""

    source_name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Indica se o adaptador está configurado e pronto."""

    @abstractmethod
    def fetch_records(
        self,
        patient_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> AdapterResult:
        """Coleta registros brutos e retorna BronzeTelemetryRecord normalizados."""

    def describe(self) -> Dict[str, Any]:
        return {
            "source": self.source_name,
            "available": self.is_available(),
        }