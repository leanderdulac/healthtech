"""
Adaptador HBand — ingere dumps JSON do companion Android (offline/file/API body).

Não fala BLE no servidor: o app mobile usa o HBandSDK e envia JSON.
Este adaptador normaliza arquivos/listas de envelopes para Bronze.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.ingestion.real.base import AdapterResult, TelemetryAdapter
from src.ingestion.real.hband_normalizer import HBandNormalizer

logger = logging.getLogger(__name__)


class HBandCompanionAdapter(TelemetryAdapter):
    """
    Lê payloads HBand de:
      - caminho de arquivo/dir (HBAND_PAYLOAD_PATH)
      - lista de dicts injetada (testes)
    """

    source_name = "hband_companion"

    def __init__(
        self,
        payload_path: Optional[str] = None,
        patient_id: Optional[str] = None,
        payloads: Optional[List[Dict[str, Any]]] = None,
    ):
        self.payload_path = payload_path or os.getenv("HBAND_PAYLOAD_PATH", "")
        self.patient_id = patient_id or os.getenv("HBAND_PATIENT_ID", "PAT-HBAND-001")
        self._payloads = payloads
        self.normalizer = HBandNormalizer()

    def is_available(self) -> bool:
        if self._payloads is not None:
            return len(self._payloads) > 0
        if not self.payload_path:
            return False
        p = Path(self.payload_path)
        return p.exists()

    def fetch_records(
        self,
        patient_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> AdapterResult:
        pid = patient_id or self.patient_id
        errors: List[str] = []
        envelopes = self._load_envelopes()
        if not envelopes:
            return AdapterResult(
                source=self.source_name,
                records=[],
                errors=["Nenhum payload HBand disponível"],
                metadata={"mode": "empty"},
            )

        all_records = []
        ingest_bodies = 0
        for env in envelopes:
            try:
                # Injeta patient_id se envelope não tiver
                env = self._ensure_patient(env, pid)
                records, body = self.normalizer.normalize_envelope(env)
                if start_time or end_time:
                    records = [
                        r
                        for r in records
                        if (not start_time or r.timestamp_utc >= start_time)
                        and (not end_time or r.timestamp_utc <= end_time)
                    ]
                all_records.extend(records)
                if body:
                    ingest_bodies += 1
            except Exception as exc:
                logger.warning("Envelope HBand ignorado: %s", exc)
                errors.append(str(exc))

        return AdapterResult(
            source=self.source_name,
            records=all_records,
            errors=errors,
            metadata={
                "mode": "json_file" if self.payload_path else "injected",
                "envelopes": len(envelopes),
                "ingest_bodies": ingest_bodies,
                "vendor": "hband",
            },
        )

    def _ensure_patient(self, env: Dict[str, Any], pid: str) -> Dict[str, Any]:
        payload = env.get("payload", env)
        if isinstance(payload, dict) and "patient_id" not in payload:
            payload = {**payload, "patient_id": pid}
            if "payload" in env:
                return {**env, "payload": payload}
            return payload
        return env

    def _load_envelopes(self) -> List[Dict[str, Any]]:
        if self._payloads is not None:
            return list(self._payloads)

        path = Path(self.payload_path)
        if not path.exists():
            return []

        if path.is_file():
            return self._parse_file(path)

        envelopes: List[Dict[str, Any]] = []
        for f in sorted(path.glob("**/*.{json,jsonl}")):
            envelopes.extend(self._parse_file(f))
        # pathlib glob brace may not work on all systems
        if not envelopes:
            for f in sorted(path.rglob("*.json")):
                envelopes.extend(self._parse_file(f))
            for f in sorted(path.rglob("*.jsonl")):
                envelopes.extend(self._parse_file(f))
        return envelopes

    def _parse_file(self, path: Path) -> List[Dict[str, Any]]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        if path.suffix == ".jsonl" or "\n{" in text:
            out = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
            return out
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return [data]


def normalize_hband_payload(
    payload: Union[Dict[str, Any], List[Dict[str, Any]]],
) -> AdapterResult:
    """Helper one-shot para testes e scripts."""
    items = payload if isinstance(payload, list) else [payload]
    adapter = HBandCompanionAdapter(payloads=items)
    return adapter.fetch_records()
