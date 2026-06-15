import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

def generate_sensor_data(num_records=50, base_time=None):
    """Gera dados simulados de sensores biométricos."""
    if base_time is None:
        base_time = datetime.now()
        
    records = []
    current_time = base_time
    
    # Simula batimentos cardíacos normais com pequena variação
    current_hr = random.randint(65, 75)
    
    for _ in range(num_records):
        # Avança 1 ou 2 segundos
        current_time += timedelta(seconds=random.randint(1, 2))
        
        # Flutuação normal do batimento
        current_hr += random.choice([-1, 0, 1, 2, -2])
        
        # Garante limites realistas
        current_hr = max(50, min(180, current_hr))
        
        # Introduz anomalia repentina no final (simulando pico)
        if _ > num_records - 5:
            current_hr += 35
            
        # Simula leitura de dois sensores (watch e phone/chest band)
        # Ocasionalmente gera leituras no mesmo segundo ou bem próximas
        records.append({
            'timestamp': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'sensor_id': 'pixel_watch',
            'heart_rate': current_hr
        })
        
        # 60% de chance de ter uma leitura redundante de outro sensor
        if random.random() > 0.4:
            records.append({
                'timestamp': (current_time + timedelta(milliseconds=random.randint(100, 500))).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                'sensor_id': 'fitbit_band',
                'heart_rate': current_hr + random.choice([-1, 0, 1]) # Variação leve do outro sensor
            })

    return pd.DataFrame(records)

def generate_patient_fhir_mock():
    """Gera um dicionário simulando um recurso FHIR de paciente com PII."""
    return {
        "resourceType": "Patient",
        "id": "12345",
        "identifier": [
            {"system": "urn:oid:2.16.840.1.113883.4.1", "value": "123-45-6789"} # SSN simulado
        ],
        "name": [
            {"use": "official", "family": "Silva", "given": ["João", "Pedro"]}
        ],
        "telecom": [
            {"system": "phone", "value": "555-0100", "use": "mobile"},
            {"system": "email", "value": "joao.silva@exemplo.com"}
        ],
        "gender": "male",
        "birthDate": "1985-06-15",
        "address": [
            {
                "use": "home",
                "line": ["Rua das Flores, 123"],
                "city": "São Paulo",
                "state": "SP",
                "postalCode": "01000-000",
                "country": "BR"
            }
        ]
    }

def generate_historical_population_data(num_patients=1000):
    """Gera dados agregados simulados para análise em lote (Batch)."""
    np.random.seed(42)
    
    # Dados normais
    hr_resting = np.random.normal(loc=70, scale=8, size=num_patients)
    sleep_hours = np.random.normal(loc=7.5, scale=1.2, size=num_patients)
    activity_mins = np.random.normal(loc=150, scale=40, size=num_patients)
    
    df = pd.DataFrame({
        'paciente_id': [f'P{str(i).zfill(4)}' for i in range(num_patients)],
        'media_bpm_repouso': hr_resting,
        'horas_sono': sleep_hours,
        'minutos_atividade_intensa': activity_mins
    })
    
    # Injetando algumas anomalias (pacientes de risco)
    # Risco cardíaco (alta BPM repouso, baixo sono, baixa atividade)
    indices_anomalia = np.random.choice(df.index, size=int(num_patients * 0.05), replace=False)
    df.loc[indices_anomalia, 'media_bpm_repouso'] += 25
    df.loc[indices_anomalia, 'horas_sono'] -= 3
    df.loc[indices_anomalia, 'minutos_atividade_intensa'] = 10
    
    return df
