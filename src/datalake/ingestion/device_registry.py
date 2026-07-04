import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DeviceBinding, DeviceType


class DeviceRegistry:
    """Registro mestre de dispositivos pareados por paciente."""

    def __init__(self, config: LakehouseConfig):
        self._path = config.metadata_path / "device_registry.json"
        self._bindings: Dict[str, List[DeviceBinding]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        for patient_id, bindings in data.items():
            self._bindings[patient_id] = [
                DeviceBinding(
                    patient_id=b["patient_id"],
                    device_id=b["device_id"],
                    device_type=DeviceType(b["device_type"]) if isinstance(b["device_type"], str) else b["device_type"],
                    vendor=b["vendor"],
                    firmware_version=b["firmware_version"],
                    paired_at=datetime.fromisoformat(b["paired_at"]),
                    is_primary=b.get("is_primary", True),
                    metadata=b.get("metadata", {}),
                )
                for b in bindings
            ]

    def register(self, binding: DeviceBinding) -> None:
        self._bindings.setdefault(binding.patient_id, [])
        existing = {b.device_id for b in self._bindings[binding.patient_id]}
        if binding.device_id not in existing:
            self._bindings[binding.patient_id].append(binding)

    def register_batch(self, bindings: List[DeviceBinding]) -> None:
        for binding in bindings:
            self.register(binding)
        self._persist()

    def get_devices(self, patient_id: str) -> List[DeviceBinding]:
        return self._bindings.get(patient_id, [])

    def get_primary_device(self, patient_id: str) -> Optional[DeviceBinding]:
        devices = self.get_devices(patient_id)
        return next((d for d in devices if d.is_primary), devices[0] if devices else None)

    def list_patients(self) -> List[str]:
        return list(self._bindings.keys())

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            pid: [
                {
                    "patient_id": b.patient_id,
                    "device_id": b.device_id,
                    "device_type": b.device_type.value if hasattr(b.device_type, "value") else b.device_type,
                    "vendor": b.vendor,
                    "firmware_version": b.firmware_version,
                    "paired_at": b.paired_at.isoformat(),
                    "is_primary": b.is_primary,
                    "metadata": b.metadata,
                }
                for b in bindings
            ]
            for pid, bindings in self._bindings.items()
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)