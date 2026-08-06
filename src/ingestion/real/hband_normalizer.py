"""
HBandNormalizer — OriginData3 / sleep / sport / PPG / realtime → Bronze + ingest API.

Converte payloads do companion Android (HBand/Veepoo SDK) para:
  1. Lista de BronzeTelemetryRecord (lakehouse)
  2. Dict compatível com POST /api/v1/wearables/ingest (stream)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from src.datalake.schemas.base import DeviceType, MetricType, TelemetrySource
from src.datalake.schemas.bronze import BronzeTelemetryRecord
from src.ingestion.real.hband_schemas import (
    HBandMessageType,
    HBandOriginBatch,
    HBandOriginSample,
    HBandPPGStreamChunk,
    HBandRealtimeIngest,
    HBandSleepBatch,
    HBandSleepRecord,
    HBandSportSnapshot,
)
from src.ingestion.real.normalizer import TelemetryNormalizer

logger = logging.getLogger(__name__)

VENDOR = "hband"

# sleep_line char → stage code numérico (Bronze sleep_stage)
_SLEEP_STAGE_MAP_STD = {"0": 0.0, "1": 1.0, "2": 2.0}  # light, deep, awake
_SLEEP_STAGE_MAP_PREC = {
    "0": 0.0,  # deep
    "1": 1.0,  # light
    "2": 2.0,  # REM
    "3": 3.0,  # insomnia
    "4": 4.0,  # awake
}


def _parse_ts(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    s = value.strip().replace("Z", "+00:00")
    # Device format: yyyy-MM-dd HH:mm:ss
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            logger.warning("Timestamp HBand inválido '%s' — usando now()", value)
            return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class HBandNormalizer:
    """Normaliza payloads HBand/Veepoo para Bronze e API de wearables."""

    def __init__(self, default_confidence: float = 0.9):
        self.default_confidence = default_confidence
        self._base = TelemetryNormalizer(default_vendor=VENDOR)

    # ------------------------------------------------------------------
    # Realtime → API ingest dict
    # ------------------------------------------------------------------

    def to_wearable_ingest(
        self, payload: Union[HBandRealtimeIngest, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Converte realtime HBand para body de POST /api/v1/wearables/ingest."""
        if isinstance(payload, dict):
            payload = HBandRealtimeIngest.model_validate(payload)

        hr = payload.heart_rate
        if hr is None:
            # API exige heart_rate — usar placeholder neutro se só SpO2/temp
            hr = 0.0

        body: Dict[str, Any] = {
            "patient_id": payload.patient_id,
            "device_id": payload.device.device_id,
            "timestamp": payload.timestamp or datetime.now(timezone.utc).isoformat(),
            "heart_rate": float(hr) if hr and hr >= 20 else 70.0,
            "filter_type": payload.filter_type or "BMO",
        }
        if payload.spo2 is not None:
            body["spo2"] = payload.spo2
        if payload.skin_temp is not None:
            body["skin_temp"] = payload.skin_temp
        if payload.hrv_rmssd is not None:
            body["hrv_rmssd"] = payload.hrv_rmssd
        if payload.activity_level is not None:
            body["activity_level"] = payload.activity_level
        if payload.ppg_signal:
            body["ppg_signal"] = payload.ppg_signal

        # Extensões no raw (API monólito ignora campos extras se strict; usamos raw)
        body["_hband"] = {
            "vendor": payload.device.vendor or VENDOR,
            "model": payload.device.model,
            "firmware_version": payload.device.firmware_version,
            "blood_pressure_sys": payload.blood_pressure_sys,
            "blood_pressure_dia": payload.blood_pressure_dia,
            "respiratory_rate": payload.respiratory_rate,
            "battery_level": payload.battery_level,
            "signal_confidence": payload.signal_confidence,
            "sdk_source": payload.sdk_source,
            "raw": payload.raw or {},
        }
        if hr is None or (payload.heart_rate is not None and payload.heart_rate < 20):
            body["_hband"]["hr_placeholder"] = True
        return body

    # ------------------------------------------------------------------
    # Realtime → Bronze records
    # ------------------------------------------------------------------

    def from_realtime(
        self, payload: Union[HBandRealtimeIngest, Dict[str, Any]]
    ) -> List[BronzeTelemetryRecord]:
        if isinstance(payload, dict):
            payload = HBandRealtimeIngest.model_validate(payload)

        ts = _parse_ts(payload.timestamp)
        conf = (
            payload.signal_confidence
            if payload.signal_confidence is not None
            else self.default_confidence
        )
        device_id = payload.device.device_id
        pid = payload.patient_id
        base_raw = {
            "sdk_source": payload.sdk_source,
            "model": payload.device.model,
            "firmware": payload.device.firmware_version,
            **(payload.raw or {}),
        }

        pairs: List[Tuple[MetricType, float, Dict[str, Any]]] = []
        if payload.heart_rate is not None and payload.heart_rate >= 20:
            pairs.append((MetricType.HEART_RATE, payload.heart_rate, base_raw))
        if payload.spo2 is not None:
            pairs.append((MetricType.SPO2, payload.spo2, base_raw))
        if payload.skin_temp is not None:
            pairs.append((MetricType.SKIN_TEMP, payload.skin_temp, base_raw))
        if payload.hrv_rmssd is not None:
            pairs.append((MetricType.HRV, payload.hrv_rmssd, base_raw))
        if payload.activity_level is not None:
            pairs.append((MetricType.STRESS_INDEX, payload.activity_level, base_raw))
        if payload.blood_pressure_sys is not None:
            pairs.append(
                (MetricType.BLOOD_PRESSURE_SYS, payload.blood_pressure_sys, base_raw)
            )
        if payload.blood_pressure_dia is not None:
            pairs.append(
                (MetricType.BLOOD_PRESSURE_DIA, payload.blood_pressure_dia, base_raw)
            )
        if payload.respiratory_rate is not None:
            pairs.append(
                (MetricType.RESPIRATORY_RATE, payload.respiratory_rate, base_raw)
            )

        records: List[BronzeTelemetryRecord] = []
        for metric, value, raw in pairs:
            records.append(
                self._base.from_raw_reading(
                    patient_id=pid,
                    device_id=device_id,
                    metric_type=metric,
                    value=float(value),
                    timestamp=ts,
                    vendor=payload.device.vendor or VENDOR,
                    device_type=DeviceType.FITNESS_BAND,
                    source=TelemetrySource.DEVICE_STREAM,
                    confidence=conf,
                    battery_level=payload.battery_level,
                    raw_payload={**raw, "ppg_len": len(payload.ppg_signal or [])},
                )
            )
        return records

    # ------------------------------------------------------------------
    # Origin batch (histórico 5 min)
    # ------------------------------------------------------------------

    def from_origin_batch(
        self, batch: Union[HBandOriginBatch, Dict[str, Any]]
    ) -> List[BronzeTelemetryRecord]:
        if isinstance(batch, dict):
            batch = HBandOriginBatch.model_validate(batch)

        records: List[BronzeTelemetryRecord] = []
        for sample in batch.samples:
            records.extend(
                self._origin_sample_to_records(
                    sample,
                    patient_id=batch.patient_id,
                    device_id=batch.device.device_id,
                    vendor=batch.device.vendor or VENDOR,
                    day_offset=batch.day_offset or 0,
                    protocol=batch.device.origin_protocol_version,
                )
            )
        return records

    def _origin_sample_to_records(
        self,
        sample: HBandOriginSample,
        *,
        patient_id: str,
        device_id: str,
        vendor: str,
        day_offset: int,
        protocol: Optional[int],
    ) -> List[BronzeTelemetryRecord]:
        ts = _parse_ts(sample.timestamp)
        raw = {
            "origin": True,
            "package_number": sample.package_number,
            "day_offset": day_offset,
            "origin_protocol_version": protocol,
            "sport_value": sample.sport_value,
            "ppg_data_len": len(sample.ppg_data or []),
            "ecg_data_len": len(sample.ecg_data or []),
            **(sample.raw or {}),
        }
        conf = self.default_confidence
        # Protocolo legado / PA de pulseira → confiança um pouco menor
        if protocol is not None and protocol < 3:
            conf = min(conf, 0.85)

        mapping: List[Tuple[Optional[float], MetricType]] = [
            (sample.rate_value, MetricType.HEART_RATE),
            (sample.spo2_value, MetricType.SPO2),
            (sample.hrv, MetricType.HRV),
            (sample.step_value, MetricType.STEPS),
            (sample.high_value, MetricType.BLOOD_PRESSURE_SYS),
            (sample.low_value, MetricType.BLOOD_PRESSURE_DIA),
            (sample.respiration_rate, MetricType.RESPIRATORY_RATE),
            (
                sample.base_temperature
                if sample.base_temperature is not None
                else sample.temperature,
                MetricType.SKIN_TEMP,
            ),
        ]
        if sample.sport_value is not None:
            # Normaliza intensidade bruta para 0–100 aproximado
            intensity = min(100.0, float(sample.sport_value) / 655.35)
            mapping.append((intensity, MetricType.STRESS_INDEX))

        out: List[BronzeTelemetryRecord] = []
        for value, metric in mapping:
            if value is None:
                continue
            if metric == MetricType.HEART_RATE and (value < 20 or value > 250):
                continue
            if metric == MetricType.SPO2 and (value < 50 or value > 100):
                continue
            out.append(
                self._base.from_raw_reading(
                    patient_id=patient_id,
                    device_id=device_id,
                    metric_type=metric,
                    value=float(value),
                    timestamp=ts,
                    vendor=vendor,
                    device_type=DeviceType.FITNESS_BAND,
                    source=TelemetrySource.BATCH_SYNC,
                    confidence=conf,
                    raw_payload=raw,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Sleep
    # ------------------------------------------------------------------

    def from_sleep_batch(
        self, batch: Union[HBandSleepBatch, Dict[str, Any]]
    ) -> List[BronzeTelemetryRecord]:
        if isinstance(batch, dict):
            batch = HBandSleepBatch.model_validate(batch)

        records: List[BronzeTelemetryRecord] = []
        for rec in batch.records:
            records.extend(
                self._sleep_to_records(
                    rec,
                    patient_id=batch.patient_id,
                    device_id=batch.device.device_id,
                    vendor=batch.device.vendor or VENDOR,
                )
            )
        return records

    def _sleep_to_records(
        self,
        rec: HBandSleepRecord,
        *,
        patient_id: str,
        device_id: str,
        vendor: str,
    ) -> List[BronzeTelemetryRecord]:
        ts = _parse_ts(rec.date)
        raw = {
            "sleep": True,
            "sleep_quality": rec.sleep_quality,
            "wake_count": rec.wake_count,
            "deep_min": rec.deep_sleep_time_min,
            "light_min": rec.light_sleep_time_min,
            "all_min": rec.all_sleep_time_min,
            "sleep_line": rec.sleep_line,
            "sleep_down": rec.sleep_down,
            "sleep_up": rec.sleep_up,
            "precision_sleep": rec.precision_sleep,
            **(rec.raw or {}),
        }
        out: List[BronzeTelemetryRecord] = []
        if rec.all_sleep_time_min is not None:
            # Usa quality como valor principal se existir; senão duração total
            stage_val = float(
                rec.sleep_quality
                if rec.sleep_quality is not None
                else rec.all_sleep_time_min
            )
            out.append(
                self._base.from_raw_reading(
                    patient_id=patient_id,
                    device_id=device_id,
                    metric_type=MetricType.SLEEP_STAGE,
                    value=stage_val,
                    timestamp=ts,
                    vendor=vendor,
                    device_type=DeviceType.FITNESS_BAND,
                    source=TelemetrySource.BATCH_SYNC,
                    confidence=self.default_confidence,
                    raw_payload=raw,
                )
            )
        # Expande sleep_line em amostras discretas (amostragem leve: 1 valor a cada 12 chars ≈ 1h se 5min)
        if rec.sleep_line:
            stage_map = (
                _SLEEP_STAGE_MAP_PREC if rec.precision_sleep else _SLEEP_STAGE_MAP_STD
            )
            step = 12 if not rec.precision_sleep else 60
            for i in range(0, len(rec.sleep_line), step):
                ch = rec.sleep_line[i]
                if ch not in stage_map:
                    continue
                out.append(
                    self._base.from_raw_reading(
                        patient_id=patient_id,
                        device_id=device_id,
                        metric_type=MetricType.SLEEP_STAGE,
                        value=stage_map[ch],
                        timestamp=ts,
                        vendor=vendor,
                        device_type=DeviceType.FITNESS_BAND,
                        source=TelemetrySource.BATCH_SYNC,
                        confidence=0.85,
                        raw_payload={**raw, "sleep_line_index": i, "char": ch},
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Sport
    # ------------------------------------------------------------------

    def from_sport(
        self, snap: Union[HBandSportSnapshot, Dict[str, Any]]
    ) -> List[BronzeTelemetryRecord]:
        if isinstance(snap, dict):
            snap = HBandSportSnapshot.model_validate(snap)

        ts = _parse_ts(snap.timestamp)
        raw = {
            "sport": True,
            "calc_type": snap.calc_type,
            **(snap.raw or {}),
        }
        out: List[BronzeTelemetryRecord] = []
        pid, did = snap.patient_id, snap.device.device_id
        vendor = snap.device.vendor or VENDOR
        if snap.step is not None:
            out.append(
                self._base.from_raw_reading(
                    patient_id=pid,
                    device_id=did,
                    metric_type=MetricType.STEPS,
                    value=float(snap.step),
                    timestamp=ts,
                    vendor=vendor,
                    device_type=DeviceType.FITNESS_BAND,
                    source=TelemetrySource.DEVICE_STREAM,
                    confidence=self.default_confidence,
                    raw_payload=raw,
                )
            )
        if snap.distance_km is not None:
            out.append(
                self._base.from_raw_reading(
                    patient_id=pid,
                    device_id=did,
                    metric_type=MetricType.DISTANCE_KM,
                    value=float(snap.distance_km),
                    timestamp=ts,
                    vendor=vendor,
                    device_type=DeviceType.FITNESS_BAND,
                    source=TelemetrySource.DEVICE_STREAM,
                    confidence=self.default_confidence,
                    raw_payload=raw,
                )
            )
        if snap.kcal is not None:
            out.append(
                self._base.from_raw_reading(
                    patient_id=pid,
                    device_id=did,
                    metric_type=MetricType.CALORIES,
                    value=float(snap.kcal),
                    timestamp=ts,
                    vendor=vendor,
                    device_type=DeviceType.FITNESS_BAND,
                    source=TelemetrySource.DEVICE_STREAM,
                    confidence=self.default_confidence,
                    raw_payload=raw,
                )
            )
        return out

    # ------------------------------------------------------------------
    # PPG stream → realtime-like + bronze HR proxy optional
    # ------------------------------------------------------------------

    def from_ppg_stream(
        self, chunk: Union[HBandPPGStreamChunk, Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], List[BronzeTelemetryRecord]]:
        """
        Retorna (body ingest com ppg_signal, bronze records metadata).
        HR não é inferido aqui — apenas repassa PPG para BMO no servidor.
        """
        if isinstance(chunk, dict):
            chunk = HBandPPGStreamChunk.model_validate(chunk)

        ts = chunk.timestamp or datetime.now(timezone.utc).isoformat()
        realtime = HBandRealtimeIngest(
            patient_id=chunk.patient_id,
            device=chunk.device,
            timestamp=ts,
            heart_rate=70.0,  # placeholder; servidor usa mean PPG se filter BMO
            ppg_signal=chunk.green_light,
            filter_type="BMO",
            sdk_source="ppg_realtime",
            raw={
                "sample_rate_hz": chunk.sample_rate_hz,
                "mode": chunk.mode,
                "accel_n": len(chunk.acceleration or []),
            },
            signal_confidence=0.88,
        )
        body = self.to_wearable_ingest(realtime)
        # Bronze: não grava cada amostra PPG como métrica; só meta se necessário
        records: List[BronzeTelemetryRecord] = []
        return body, records

    # ------------------------------------------------------------------
    # Envelope router
    # ------------------------------------------------------------------

    def normalize_envelope(
        self, envelope: Dict[str, Any]
    ) -> Tuple[List[BronzeTelemetryRecord], Optional[Dict[str, Any]]]:
        """
        Processa HBandEnvelope.
        Returns: (bronze_records, optional_ingest_body)
        """
        msg = envelope.get("message_type") or envelope.get("type")
        payload = envelope.get("payload") or envelope

        try:
            mtype = HBandMessageType(msg) if msg else None
        except ValueError:
            mtype = None

        if mtype == HBandMessageType.REALTIME_INGEST or (
            mtype is None and "heart_rate" in payload
        ):
            model = HBandRealtimeIngest.model_validate(payload)
            return self.from_realtime(model), self.to_wearable_ingest(model)

        if mtype == HBandMessageType.ORIGIN_BATCH or "samples" in payload:
            return self.from_origin_batch(payload), None

        if mtype == HBandMessageType.SLEEP_BATCH or "records" in payload:
            return self.from_sleep_batch(payload), None

        if mtype == HBandMessageType.SPORT_SNAPSHOT or "step" in payload:
            return self.from_sport(payload), None

        if mtype == HBandMessageType.PPG_STREAM or "green_light" in payload:
            body, recs = self.from_ppg_stream(payload)
            return recs, body

        logger.warning("Envelope HBand não reconhecido: keys=%s", list(envelope.keys()))
        return [], None
