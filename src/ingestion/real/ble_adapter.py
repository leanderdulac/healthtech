"""
Adaptador BLE genérico para frequência cardíaca (GATT 0x180D / 0x2A37).

Interface pronta para bleak; em ambiente sem hardware, usa stub simulado.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from src.datalake.schemas.base import DeviceType, MetricType, TelemetrySource
from src.ingestion.real.base import AdapterResult, TelemetryAdapter
from src.ingestion.real.normalizer import TelemetryNormalizer

logger = logging.getLogger(__name__)

try:
    import bleak  # noqa: F401
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False


class BLEHeartRateAdapter(TelemetryAdapter):
    """Coleta HR via BLE ou stub para desenvolvimento."""

    source_name = "ble_heart_rate"
    HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
    HR_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

    def __init__(
        self,
        device_address: Optional[str] = None,
        patient_id: Optional[str] = None,
        device_id: str = "ble-hr-sensor",
        stub_samples: int = 60,
    ):
        self.device_address = device_address or os.getenv("BLE_DEVICE_ADDRESS", "")
        self.patient_id = patient_id or os.getenv("BLE_PATIENT_ID", "PAT-BLE-001")
        self.device_id = device_id
        self.stub_samples = stub_samples
        self.normalizer = TelemetryNormalizer(default_vendor="ble_generic")
        self._use_stub = os.getenv("BLE_USE_STUB", "true").lower() in ("1", "true", "yes")

    def is_available(self) -> bool:
        if self._use_stub:
            return True
        return BLEAK_AVAILABLE and bool(self.device_address)

    def fetch_records(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> AdapterResult:
        pid = patient_id or self.patient_id

        if self._use_stub or not BLEAK_AVAILABLE or not self.device_address:
            records = self._stub_stream(pid, self.stub_samples)
            return AdapterResult(
                source=self.source_name,
                records=records,
                metadata={"mode": "stub", "samples": len(records)},
            )

        try:
            records = self._scan_and_read(pid)
            return AdapterResult(source=self.source_name, records=records, metadata={"mode": "ble"})
        except Exception as e:
            logger.exception("BLE falhou — fallback stub")
            records = self._stub_stream(pid, self.stub_samples)
            return AdapterResult(
                source=self.source_name,
                records=records,
                errors=[str(e)],
                metadata={"mode": "stub_fallback"},
            )

    def _stub_stream(self, patient_id: str, n: int) -> List:
        import random
        now = datetime.now(timezone.utc)
        records = []
        bpm = 72.0
        for i in range(n):
            bpm += random.uniform(-3, 3)
            bpm = max(45, min(160, bpm))
            ts = now.replace(microsecond=0)
            from datetime import timedelta
            ts = ts - timedelta(seconds=(n - i) * 5)
            records.append(self.normalizer.from_raw_reading(
                patient_id=patient_id,
                device_id=self.device_id,
                metric_type=MetricType.HEART_RATE,
                value=round(bpm, 1),
                timestamp=ts,
                vendor="ble_generic",
                device_type=DeviceType.CHEST_STRAP,
                source=TelemetrySource.DEVICE_STREAM,
                confidence=0.85,
                raw_payload={"mode": "stub", "sample_index": i},
            ))
        return records

    def _scan_and_read(self, patient_id: str) -> List:
        """Leitura BLE real — requer bleak e endereço configurado."""
        import asyncio

        async def _read():
            from bleak import BleakClient

            records = []
            async with BleakClient(self.device_address) as client:
                data = await client.read_gatt_char(self.HR_CHAR_UUID)
                bpm = self._parse_hr_measurement(data)
                records.append(self.normalizer.from_raw_reading(
                    patient_id=patient_id,
                    device_id=self.device_address,
                    metric_type=MetricType.HEART_RATE,
                    value=float(bpm),
                    timestamp=datetime.now(timezone.utc),
                    vendor="ble_generic",
                    device_type=DeviceType.CHEST_STRAP,
                    source=TelemetrySource.DEVICE_STREAM,
                    confidence=0.9,
                    raw_payload={"raw_bytes": list(data)},
                ))
            return records

        return asyncio.get_event_loop().run_until_complete(_read())

    @staticmethod
    def _parse_hr_measurement(data: bytes) -> int:
        if not data:
            return 0
        flags = data[0]
        if flags & 0x01:
            return int(data[1] | (data[2] << 8))
        return int(data[1])