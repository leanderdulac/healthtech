"""Ingestão real de wearables (Apple / Google Fit / BLE / HBand).

Exports lazy: importar `hband_*` não puxa `requests`/Google Fit no CI.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "RealIngestionOrchestrator",
    "TelemetryAdapter",
    "AdapterResult",
    "HBandCompanionAdapter",
    "HBandNormalizer",
    "normalize_hband_payload",
]


def __getattr__(name: str) -> Any:
    if name in ("TelemetryAdapter", "AdapterResult"):
        from src.ingestion.real.base import AdapterResult, TelemetryAdapter

        return {"TelemetryAdapter": TelemetryAdapter, "AdapterResult": AdapterResult}[name]
    if name == "RealIngestionOrchestrator":
        from src.ingestion.real.orchestrator import RealIngestionOrchestrator

        return RealIngestionOrchestrator
    if name in ("HBandCompanionAdapter", "normalize_hband_payload"):
        from src.ingestion.real.hband_adapter import (
            HBandCompanionAdapter,
            normalize_hband_payload,
        )

        return {
            "HBandCompanionAdapter": HBandCompanionAdapter,
            "normalize_hband_payload": normalize_hband_payload,
        }[name]
    if name == "HBandNormalizer":
        from src.ingestion.real.hband_normalizer import HBandNormalizer

        return HBandNormalizer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
