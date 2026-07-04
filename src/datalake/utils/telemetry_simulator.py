import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.datalake.schemas.base import DeviceBinding, DeviceType, MetricType, TelemetrySource
from src.datalake.schemas.bronze import BronzeTelemetryRecord


@dataclass
class SimulationConfig:
    """Parâmetros para simulação de telemetria contínua 24h."""

    num_patients: int = 5
    hours: float = 24.0
    hr_interval_seconds: int = 5
    spo2_interval_seconds: int = 60
    hrv_interval_seconds: int = 300
    steps_interval_seconds: int = 900
    stress_interval_seconds: int = 600
    anomaly_probability: float = 0.02
    seed: int = 42


@dataclass
class PatientProfile:
    patient_id: str
    age: int
    resting_hr: int
    baseline_spo2: float
    baseline_hrv: float
    activity_level: str
    risk_factor: float = 0.0
    devices: List[DeviceBinding] = field(default_factory=list)


class TelemetrySimulator:
    """
    Simula telemetria 24h de múltiplos pacientes com relógios inteligentes.
    Modela ciclos circadianos, sono, atividade e episódios de anomalia.
    """

    VENDORS = {
        DeviceType.SMARTWATCH: ["pixel_watch", "apple_watch", "galaxy_watch"],
        DeviceType.FITNESS_BAND: ["fitbit_band", "mi_band"],
        DeviceType.RING: ["oura_ring"],
    }

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.rng = np.random.default_rng(config.seed)
        self._profiles = self._generate_patient_profiles()

    @property
    def patient_profiles(self) -> List[PatientProfile]:
        return self._profiles

    def _generate_patient_profiles(self) -> List[PatientProfile]:
        profiles = []
        for i in range(self.config.num_patients):
            patient_id = f"PAT-{hashlib.sha256(f'patient-{i}'.encode()).hexdigest()[:12]}"
            age = int(self.rng.integers(25, 75))
            resting_hr = int(self.rng.integers(58, 78))
            risk = float(self.rng.uniform(0, 0.3)) if i < self.config.num_patients - 1 else 0.8

            devices = [
                self._create_device_binding(patient_id, DeviceType.SMARTWATCH, is_primary=True),
                self._create_device_binding(patient_id, DeviceType.FITNESS_BAND, is_primary=False),
            ]

            profiles.append(PatientProfile(
                patient_id=patient_id,
                age=age,
                resting_hr=resting_hr,
                baseline_spo2=float(self.rng.uniform(95, 99)),
                baseline_hrv=float(self.rng.uniform(30, 80)),
                activity_level=self.rng.choice(["sedentary", "moderate", "active"]),
                risk_factor=risk,
                devices=devices,
            ))
        return profiles

    def _create_device_binding(
        self,
        patient_id: str,
        device_type: DeviceType,
        is_primary: bool,
    ) -> DeviceBinding:
        vendor = self.rng.choice(self.VENDORS[device_type])
        return DeviceBinding(
            patient_id=patient_id,
            device_id=f"{vendor}-{uuid.uuid4().hex[:8]}",
            device_type=device_type,
            vendor=vendor,
            firmware_version=f"{self.rng.integers(1,5)}.{self.rng.integers(0,9)}.{self.rng.integers(0,9)}",
            paired_at=datetime.utcnow() - timedelta(days=int(self.rng.integers(30, 365))),
            is_primary=is_primary,
        )

    def generate_24h_stream(
        self,
        start_time: Optional[datetime] = None,
        patient_ids: Optional[List[str]] = None,
    ) -> List[BronzeTelemetryRecord]:
        start = start_time or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=self.config.hours)
        profiles = self._profiles

        if patient_ids:
            profiles = [p for p in profiles if p.patient_id in patient_ids]

        records: List[BronzeTelemetryRecord] = []
        for profile in profiles:
            records.extend(self._simulate_patient_day(profile, start, end))

        records.sort(key=lambda r: r.timestamp_utc)
        return records

    def _simulate_patient_day(
        self,
        profile: PatientProfile,
        start: datetime,
        end: datetime,
    ) -> List[BronzeTelemetryRecord]:
        records: List[BronzeTelemetryRecord] = []
        current = start
        hr = float(profile.resting_hr)
        steps_accumulated = 0
        in_anomaly_episode = False
        anomaly_remaining = 0

        primary_device = next(d for d in profile.devices if d.is_primary)
        secondary_device = next((d for d in profile.devices if not d.is_primary), primary_device)

        while current < end:
            hour = current.hour
            sleep_ctx, activity_ctx = self._circadian_context(hour)
            hr = self._evolve_heart_rate(hr, profile, sleep_ctx, activity_ctx)

            if not in_anomaly_episode and self.rng.random() < self.config.anomaly_probability * (1 + profile.risk_factor):
                in_anomaly_episode = True
                anomaly_remaining = int(self.rng.integers(3, 12))

            if in_anomaly_episode:
                hr += float(self.rng.integers(25, 55))
                anomaly_remaining -= 1
                if anomaly_remaining <= 0:
                    in_anomaly_episode = False

            hr = max(35, min(210, hr))

            records.append(self._make_record(
                profile, primary_device, MetricType.HEART_RATE, hr, "bpm", current,
                sleep_ctx=sleep_ctx, activity_ctx=activity_ctx,
            ))

            if self.rng.random() > 0.35:
                records.append(self._make_record(
                    profile, secondary_device, MetricType.HEART_RATE,
                    hr + float(self.rng.integers(-2, 3)), "bpm",
                    current + timedelta(milliseconds=int(self.rng.integers(100, 800))),
                    sleep_ctx=sleep_ctx, activity_ctx=activity_ctx,
                    confidence=float(self.rng.uniform(0.7, 0.95)),
                ))

            if current.minute % (self.config.spo2_interval_seconds // 60 or 1) == 0 and current.second == 0:
                spo2 = profile.baseline_spo2 - (5 if in_anomaly_episode else 0) + float(self.rng.normal(0, 0.5))
                records.append(self._make_record(
                    profile, primary_device, MetricType.SPO2, max(85, min(100, spo2)), "%", current,
                ))

            if current.minute % (self.config.hrv_interval_seconds // 60 or 1) == 0 and current.second == 0:
                hrv = profile.baseline_hrv + float(self.rng.normal(0, 5))
                records.append(self._make_record(
                    profile, primary_device, MetricType.HRV, max(10, hrv), "ms", current,
                ))

            if current.minute % (self.config.steps_interval_seconds // 60 or 1) == 0 and current.second == 0:
                step_rate = {"sedentary": 20, "moderate": 80, "active": 150}[profile.activity_level]
                if activity_ctx == "active":
                    step_rate *= 3
                elif sleep_ctx == "deep_sleep":
                    step_rate = 0
                steps_delta = int(self.rng.poisson(step_rate))
                steps_accumulated += steps_delta
                records.append(self._make_record(
                    profile, primary_device, MetricType.STEPS, float(steps_accumulated), "count", current,
                ))

            if current.minute % (self.config.stress_interval_seconds // 60 or 1) == 0 and current.second == 0:
                stress = 30 + (40 if in_anomaly_episode else 0) + (20 if activity_ctx == "active" else 0)
                records.append(self._make_record(
                    profile, primary_device, MetricType.STRESS_INDEX,
                    min(100, stress + float(self.rng.normal(0, 5))), "index", current,
                ))

            current += timedelta(seconds=self.config.hr_interval_seconds)

        return records

    @staticmethod
    def _circadian_context(hour: int) -> Tuple[str, str]:
        if 0 <= hour < 6:
            return "deep_sleep", "resting"
        if 6 <= hour < 8:
            return "light_sleep", "waking"
        if 8 <= hour < 18:
            return "awake", "active"
        if 18 <= hour < 22:
            return "awake", "moderate"
        return "light_sleep", "resting"

    def _evolve_heart_rate(
        self,
        current_hr: float,
        profile: PatientProfile,
        sleep_ctx: str,
        activity_ctx: str,
    ) -> float:
        target = float(profile.resting_hr)
        if sleep_ctx == "deep_sleep":
            target -= 12
        elif activity_ctx == "active":
            target += 25
        elif activity_ctx == "moderate":
            target += 10

        delta = (target - current_hr) * 0.15 + float(self.rng.normal(0, 2))
        return current_hr + delta

    def _make_record(
        self,
        profile: PatientProfile,
        device: DeviceBinding,
        metric: MetricType,
        value: float,
        unit: str,
        timestamp: datetime,
        sleep_ctx: str = "awake",
        activity_ctx: str = "resting",
        confidence: float = 0.95,
    ) -> BronzeTelemetryRecord:
        now = datetime.utcnow()
        return BronzeTelemetryRecord(
            event_id=str(uuid.uuid4()),
            patient_id=profile.patient_id,
            device_id=device.device_id,
            device_type=device.device_type,
            vendor=device.vendor,
            metric_type=metric,
            metric_value=round(value, 2),
            unit=unit,
            timestamp_utc=timestamp,
            ingested_at=now,
            source=TelemetrySource.DEVICE_STREAM,
            battery_level=float(self.rng.uniform(0.2, 1.0)),
            signal_confidence=confidence,
            raw_payload={
                "firmware": device.firmware_version,
                "sleep_context": sleep_ctx,
                "activity_context": activity_ctx,
                "patient_age": profile.age,
                "is_primary_device": device.is_primary,
            },
        )