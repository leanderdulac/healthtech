import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.fhir.builders import build_patient, resource_to_dict
from src.fhir.mappers import patient_fhir_mock_to_anonymized
from src.fhir.terminology import BR_CPF_SYSTEM, LOINC_SYSTEM


def generate_sensor_data(num_records=50, base_time=None):
    """Gera dados simulados de sensores biometricos."""
    if base_time is None:
        base_time = datetime.now()

    records = []
    current_time = base_time
    current_hr = random.randint(65, 75)

    for i in range(num_records):
        current_time += timedelta(seconds=random.randint(1, 2))
        current_hr += random.choice([-1, 0, 1, 2, -2])
        current_hr = max(50, min(180, current_hr))

        if i > num_records - 5:
            current_hr += 35

        records.append({
            "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "sensor_id": "pixel_watch",
            "heart_rate": current_hr,
            "loinc_code": "8867-4",
        })

        if random.random() > 0.4:
            records.append({
                "timestamp": (
                    current_time + timedelta(milliseconds=random.randint(100, 500))
                ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "sensor_id": "fitbit_band",
                "heart_rate": current_hr + random.choice([-1, 0, 1]),
                "loinc_code": "8867-4",
            })

    return pd.DataFrame(records)


def generate_patient_fhir_mock():
    """Gera recurso FHIR R4 Patient com PII (para demonstracao de anonimizacao)."""
    patient = build_patient(
        patient_id="12345",
        gender="male",
        birth_date="1985-06-15",
        city="Sao Paulo",
        state="SP",
        country="BR",
    )
    resource = resource_to_dict(patient)

    resource["identifier"] = [
        {"system": BR_CPF_SYSTEM, "value": "12345678901", "use": "official"},
    ]
    resource["name"] = [
        {"use": "official", "family": "Silva", "given": ["Joao", "Pedro"]},
    ]
    resource["telecom"] = [
        {"system": "phone", "value": "555-0100", "use": "mobile"},
        {"system": "email", "value": "joao.silva@exemplo.com"},
    ]
    resource["address"] = [
        {
            "use": "home",
            "line": ["Rua das Flores, 123"],
            "city": "Sao Paulo",
            "state": "SP",
            "postalCode": "01000-000",
            "country": "BR",
        }
    ]
    return resource


def generate_patient_fhir_anonymized():
    """Gera Patient FHIR ja anonimizado (fluxo completo HL7 de-identification)."""
    return patient_fhir_mock_to_anonymized(generate_patient_fhir_mock())


def generate_historical_population_data(num_patients=1000):
    """Gera dados agregados simulados para analise em lote (Batch)."""
    np.random.seed(42)

    hr_resting = np.random.normal(loc=70, scale=8, size=num_patients)
    sleep_hours = np.random.normal(loc=7.5, scale=1.2, size=num_patients)
    activity_mins = np.random.normal(loc=150, scale=40, size=num_patients)

    df = pd.DataFrame({
        "patient_id": [f"PAT-{str(i).zfill(4)}" for i in range(num_patients)],
        "media_bpm_repouso": hr_resting,
        "horas_sono": sleep_hours,
        "minutos_atividade_intensa": activity_mins,
        "loinc_heart_rate": f"{LOINC_SYSTEM}|8867-4",
        "loinc_sleep": f"{LOINC_SYSTEM}|93832-4",
    })

    indices_anomalia = np.random.choice(df.index, size=int(num_patients * 0.05), replace=False)
    df.loc[indices_anomalia, "media_bpm_repouso"] += 25
    df.loc[indices_anomalia, "horas_sono"] -= 3
    df.loc[indices_anomalia, "minutos_atividade_intensa"] = 10

    return df