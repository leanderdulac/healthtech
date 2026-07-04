import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.ingestion.device_registry import DeviceRegistry
from src.datalake.quality.validators import TelemetryValidator
from src.datalake.schemas.bronze import BronzeTelemetryRecord
from src.datalake.storage.interface import LakehouseStore

logger = logging.getLogger(__name__)


class TelemetryIngestor:
    """
    Ingestão Bronze — recebe streams de telemetria e persiste no lakehouse.
    Aplica validação inicial e particiona por data de evento.
    """

    def __init__(
        self,
        store: LakehouseStore,
        config: LakehouseConfig,
        device_registry: Optional[DeviceRegistry] = None,
    ):
        self.store = store
        self.config = config
        self.validator = TelemetryValidator(config)
        self.device_registry = device_registry or DeviceRegistry(config)

    def ingest_stream(self, records: List[BronzeTelemetryRecord]) -> Dict[str, int]:
        if not records:
            return {"total": 0, "valid": 0, "invalid": 0, "partitions": 0}

        validated_rows = []
        valid_count = 0
        invalid_count = 0

        for record in records:
            result = self.validator.validate_bronze(record)
            record.quality_flags = result.flags
            row = record.to_dict()

            if result.is_valid:
                valid_count += 1
                validated_rows.append(row)
            else:
                invalid_count += 1
                row["rejection_reason"] = result.reason or "quality_gate_failed"
                validated_rows.append(row)

        df = pd.DataFrame(validated_rows)
        partitions_written = self._write_by_partition(df)

        logger.info(
            "Ingestão Bronze: %d total, %d válidos, %d inválidos, %d partições",
            len(records), valid_count, invalid_count, partitions_written,
        )
        return {
            "total": len(records),
            "valid": valid_count,
            "invalid": invalid_count,
            "partitions": partitions_written,
        }

    def _write_by_partition(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0

        partitions = defaultdict(list)
        for _, row in df.iterrows():
            partition = row.get("partition_date") or str(date.today())
            partitions[partition].append(row.to_dict())

        written = 0
        for partition_str, rows in partitions.items():
            partition_date = date.fromisoformat(partition_str)
            partition_df = pd.DataFrame(rows)
            self.store.write_bronze(partition_df, partition_date)
            written += 1

        return written