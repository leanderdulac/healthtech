"""
Mapeadores: schemas internos do datalake → recursos FHIR R4.
"""

import hashlib
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.datalake.schemas.base import DeviceBinding, DeviceType, MetricType
from src.datalake.schemas.bronze import BronzeTelemetryRecord
from src.datalake.schemas.gold import GoldPatientAlert
from src.datalake.utils.telemetry_simulator import PatientProfile
from src.fhir.builders import (
    build_device,
    build_flag,
    build_observation,
    build_patient,
    resource_to_dict,
)
from src.security.anonymization import anonimizar_paciente_fhir


def _stable_id(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]


def patient_profile_to_fhir(profile: PatientProfile) -> dict:
    """Converte PatientProfile do simulador em FHIR Patient."""
    birth_year = date.today().year - profile.age
    gender = "unknown"
    patient = build_patient(
        patient_id=profile.patient_id,
        gender=gender,
        birth_date=f"{birth_year}-01-01",
        country="BR",
    )
    return resource_to_dict(patient)


def patient_fhir_mock_to_anonymized(mock: dict) -> dict:
    """Pipeline: mock FHIR com PII → Patient anonimizado FHIR."""
    anonymized = anonimizar_paciente_fhir(mock)
    anonymized["meta"] = {
        "profile": ["http://healthtech.local/fhir/StructureDefinition/HealthtechPatient"],
        "security": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
                "code": "HTEST",
                "display": "test health data",
            }
        ],
    }
    return anonymized


def bronze_to_observation(record: BronzeTelemetryRecord) -> dict:
    """Converte registro Bronze em FHIR Observation."""
    obs_id = _stable_id(record.event_id, "obs")
    obs = build_observation(
        observation_id=obs_id,
        patient_id=record.patient_id,
        metric=record.metric_type,
        value=record.metric_value,
        effective_datetime=record.timestamp_utc,
        device_id=record.device_id,
        quality_score=record.signal_confidence,
    )
    return resource_to_dict(obs)


def silver_row_to_observation(row: Dict[str, Any]) -> dict:
    """Converte linha Silver em FHIR Observation consolidada."""
    metric = MetricType(row["metric_type"])
    window_start = row["window_start"]
    if isinstance(window_start, str):
        window_start = datetime.fromisoformat(window_start)

    device_ids = row.get("devices_involved", [])
    if hasattr(device_ids, "tolist"):
        device_ids = device_ids.tolist()
    device_id = device_ids[0] if isinstance(device_ids, list) and device_ids else None

    obs_id = _stable_id(str(row.get("record_id", uuid.uuid4())), "silver-obs")
    obs = build_observation(
        observation_id=obs_id,
        patient_id=row["patient_id"],
        metric=metric,
        value=float(row["metric_value"]),
        effective_datetime=window_start,
        device_id=device_id,
        is_anomaly=bool(row.get("is_anomaly", False)),
        quality_score=float(row.get("quality_score", 1.0)),
    )
    return resource_to_dict(obs)


def gold_alert_to_flag(alert: GoldPatientAlert) -> dict:
    """Converte alerta Gold em FHIR Flag."""
    flag = build_flag(
        flag_id=alert.alert_id,
        patient_id=alert.patient_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        metric_type=alert.metric_type,
        trigger_value=alert.trigger_value,
        threshold=alert.threshold,
        period_start=alert.window_start,
        period_end=alert.window_end,
    )
    return resource_to_dict(flag)


def device_binding_to_fhir(binding: DeviceBinding) -> dict:
    """Converte DeviceBinding em FHIR Device."""
    return resource_to_dict(build_device(binding))


def dataframe_to_observations(df: pd.DataFrame) -> List[dict]:
    """Converte DataFrame (bronze ou silver) em lista de Observations FHIR."""
    if df.empty:
        return []

    observations = []
    for _, row in df.iterrows():
        if "event_id" in row:
            record = BronzeTelemetryRecord.from_dict(row.to_dict())
            observations.append(bronze_to_observation(record))
        elif "record_id" in row:
            observations.append(silver_row_to_observation(row.to_dict()))
    return observations


def lakehouse_to_fhir_bundle(
    patients: List[PatientProfile],
    bronze_df: Optional[pd.DataFrame] = None,
    silver_df: Optional[pd.DataFrame] = None,
    alerts_df: Optional[pd.DataFrame] = None,
    bundle_id: Optional[str] = None,
) -> dict:
    """
    Monta Bundle FHIR completo a partir dos dados do lakehouse.
    Inclui Patient, Device, Observation e Flag.
    """
    from src.fhir.builders import build_bundle

    resources = []

    for profile in patients:
        resources.append(build_patient(
            patient_id=profile.patient_id,
            birth_date=f"{date.today().year - profile.age}-01-01",
            country="BR",
        ))
        for device in profile.devices:
            resources.append(build_device(device))

    from fhir.resources.flag import Flag
    from fhir.resources.observation import Observation
    from src.fhir.compat import fhir_parse

    if bronze_df is not None and not bronze_df.empty:
        for obs_dict in dataframe_to_observations(bronze_df.head(500)):
            resources.append(fhir_parse(Observation, obs_dict))

    if silver_df is not None and not silver_df.empty:
        for obs_dict in dataframe_to_observations(silver_df.head(2000)):
            resources.append(fhir_parse(Observation, obs_dict))

    if alerts_df is not None and not alerts_df.empty:
        for _, row in alerts_df.head(100).iterrows():
            alert = GoldPatientAlert(
                alert_id=row["alert_id"],
                patient_id=row["patient_id"],
                alert_type=row["alert_type"],
                severity=row["severity"],
                metric_type=row["metric_type"],
                trigger_value=float(row["trigger_value"]),
                threshold=float(row["threshold"]),
                window_start=pd.to_datetime(row["window_start"]).to_pydatetime(),
                window_end=pd.to_datetime(row["window_end"]).to_pydatetime(),
                duration_minutes=float(row.get("duration_minutes", 0)),
                devices_involved=list(row.get("devices_involved", [])),
            )
            resources.append(fhir_parse(Flag, gold_alert_to_flag(alert)))

    bundle = build_bundle(
        resources=resources,
        bundle_id=bundle_id or str(uuid.uuid4()),
        bundle_type="collection",
    )
    return resource_to_dict(bundle)