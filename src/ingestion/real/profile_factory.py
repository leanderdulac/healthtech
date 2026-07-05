"""Factory para perfis mínimos a partir de IDs de paciente."""

from typing import List

from src.datalake.utils.telemetry_simulator import PatientProfile


def profiles_from_ids(patient_ids: List[str]) -> List[PatientProfile]:
    profiles = []
    for i, pid in enumerate(patient_ids):
        profiles.append(PatientProfile(
            patient_id=pid,
            age=45 + (i % 20),
            resting_hr=68 + (i % 5),
            baseline_spo2=97.0,
            baseline_hrv=50.0,
            activity_level="moderate",
            risk_factor=0.1 * (i % 3),
        ))
    return profiles