import random
import logging
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from src.fhir.builders import build_patient, resource_to_dict
from src.fhir.mappers import patient_fhir_mock_to_anonymized
from src.fhir.terminology import BR_CPF_SYSTEM, LOINC_SYSTEM

logger = logging.getLogger(__name__)


def generate_sensor_data(num_records=50, base_time=None):
    """
    Gera dados simulados de sensores biométricos usando processo de Ornstein-Uhlenbeck.
    
    Modelo matemático: dX_t = θ(μ - X_t)dt + σ dW_t
    Discretizado: X_{t+1} = X_t + θ(μ - X_t)Δt + σ√(Δt) · N(0,1)
    
    Parâmetros fisiológicos:
        θ = 0.5 (taxa de reversão à média — homeostase cardíaca)
        μ = 70 bpm (frequência cardíaca média de repouso)
        σ = 4.0 bpm (volatilidade — variabilidade natural)
    """
    if base_time is None:
        base_time = datetime.now()

    records = []
    current_time = base_time
    
    # Parâmetros do processo de Ornstein-Uhlenbeck
    theta = 0.5   # Taxa de reversão à média
    mu = 70.0     # BPM médio de equilíbrio
    sigma = 4.0   # Volatilidade (desvio padrão da difusão)
    dt = 1.0      # Passo temporal em segundos
    
    # Estado inicial amostrado da distribuição estacionária
    # A distribuição estacionária de O-U é N(μ, σ²/(2θ))
    stationary_std = sigma / np.sqrt(2 * theta)
    current_hr = np.random.normal(mu, stationary_std)
    
    # Flag de anomalia: nos últimos 5 registros, simular evento de estresse agudo
    # (mudança súbita no setpoint μ)
    anomaly_start = num_records - 5
    
    for i in range(num_records):
        # Avança 1 ou 2 segundos
        current_time += timedelta(seconds=random.randint(1, 2))
        
        # Evento de estresse: setpoint sobe para 105 bpm (taquicardia sinusal)
        mu_t = 105.0 if i > anomaly_start else mu
        
        # Discretização de Euler-Maruyama do processo O-U
        dW = np.random.normal(0, 1)
        current_hr = current_hr + theta * (mu_t - current_hr) * dt + sigma * np.sqrt(dt) * dW
        
        # Limites fisiológicos absolutos (clipping biológico)
        current_hr = np.clip(current_hr, 30, 220)
        
        bpm_int = int(round(current_hr))
        
        # Simula leitura de dois sensores (watch e phone/chest band)
        # Ocasionalmente gera leituras no mesmo segundo ou bem próximas
        records.append({
            'timestamp': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'sensor_id': 'pixel_watch',
            'heart_rate': bpm_int
        })
        
        # 60% de chance de ter uma leitura redundante de outro sensor
        # O segundo sensor tem ruído de medição independente (±1 bpm)
        if random.random() > 0.4:
            sensor_noise = np.random.choice([-1, 0, 1])
            records.append({
                'timestamp': (current_time + timedelta(milliseconds=random.randint(100, 500))).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                'sensor_id': 'fitbit_band',
                'heart_rate': bpm_int + sensor_noise
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
    """
    Gera dados agregados simulados para análise em lote (Batch) usando
    distribuição normal multivariada com estrutura de covariância fisiológica.
    
    Modelo: X ~ N(μ, Σ) onde Σ codifica correlações conhecidas:
        - Alta BPM de repouso correlaciona NEGATIVAMENTE com horas de sono
        - Alta BPM de repouso correlaciona NEGATIVAMENTE com atividade física
        - Horas de sono correlacionam POSITIVAMENTE com atividade física
    
    Matriz de covariância:
        Σ = [[  64.0,  -3.2, -48.0 ],    # BPM: var=64 (std=8)
             [  -3.2,   1.44,  12.0 ],    # Sono: var=1.44 (std=1.2)
             [ -48.0,  12.0, 1600.0 ]]    # Atividade: var=1600 (std=40)
    
    Correlações resultantes:
        ρ(BPM, Sono) = -3.2 / (8 × 1.2) ≈ -0.33
        ρ(BPM, Atividade) = -48 / (8 × 40) = -0.15
        ρ(Sono, Atividade) = 12 / (1.2 × 40) = 0.25
    """
    np.random.seed(42)
    
    # Vetor de médias fisiológicas
    mu = np.array([70.0, 7.5, 150.0])
    
    # Matriz de covariância com correlações fisiológicas realistas
    # BPM↑ → Sono↓, BPM↑ → Atividade↓, Sono↑ → Atividade↑
    Sigma = np.array([
        [  64.0,  -3.2, -48.0],   # BPM de repouso
        [  -3.2,   1.44,  12.0],  # Horas de sono
        [ -48.0,  12.0, 1600.0]   # Minutos de atividade intensa
    ])
    
    # Amostragem da distribuição normal multivariada
    data = np.random.multivariate_normal(mu, Sigma, size=num_patients)
    
    df = pd.DataFrame({
        'paciente_id': [f'P{str(i).zfill(4)}' for i in range(num_patients)],
        'media_bpm_repouso': data[:, 0],
        'horas_sono': data[:, 1],
        'minutos_atividade_intensa': data[:, 2]
    })
    
    # Injetando anomalias (pacientes de risco cardiovascular)
    # Shift do vetor de médias: BPM+25, Sono-3, Atividade→10
    indices_anomalia = np.random.choice(df.index, size=int(num_patients * 0.05), replace=False)
    df.loc[indices_anomalia, 'media_bpm_repouso'] += 25
    df.loc[indices_anomalia, 'horas_sono'] -= 3
    df.loc[indices_anomalia, 'minutos_atividade_intensa'] = 10
    
    return df


def generate_rr_intervals(hr_series, jitter_std_ms=10.0):
    """
    Converte uma série de frequência cardíaca (BPM) em intervalos R-R (ms)
    com jitter fisiológico gaussiano.
    
    Modelo: RR_i = 60000/HR_i + ε_i, onde ε_i ~ N(0, σ_jitter²)
    
    O jitter modela a variabilidade beat-to-beat natural (HRV),
    que contém informação clínica sobre o sistema nervoso autônomo.
    
    Args:
        hr_series: Array ou Series com valores de BPM
        jitter_std_ms: Desvio padrão do jitter em milissegundos (default: 10ms)
    
    Returns:
        np.ndarray: Intervalos R-R em milissegundos
    """
    hr_array = np.asarray(hr_series, dtype=float)
    
    # Conversão: BPM → ms por batimento
    rr_base = 60000.0 / hr_array
    
    # Jitter gaussiano (variabilidade beat-to-beat)
    jitter = np.random.normal(0, jitter_std_ms, size=len(hr_array))
    rr_intervals = rr_base + jitter
    
    # Clipping fisiológico: RR entre 200ms (300 BPM) e 2000ms (30 BPM)
    rr_intervals = np.clip(rr_intervals, 200, 2000)
    
    return rr_intervals


def generate_wearable_multimodal_data(num_records=200, base_time=None):
    """
    Gera dados multimodais simulados de wearables para alimentar o motor de dados fantasma.
    
    Sinais gerados:
        - heart_rate: BPM via processo O-U (θ=0.5, μ=70, σ=4)
        - hrv_rmssd: RMSSD estimado (proxy de tônus vagal)
        - skin_temp: Temperatura cutânea (°C) com dinâmica lenta
        - activity_level: Nível de atividade (0=repouso, 1=moderada, 2=intensa)
    
    Estes sinais observáveis são as entradas do Extended Kalman Filter
    que infere os dados fantasma (PA, SpO₂, glicose, tônus vagal).
    """
    if base_time is None:
        base_time = datetime.now()
    
    # Parâmetros O-U para frequência cardíaca
    theta_hr, mu_hr, sigma_hr = 0.5, 70.0, 4.0
    dt = 1.0
    
    # Estado inicial
    hr = np.random.normal(mu_hr, sigma_hr / np.sqrt(2 * theta_hr))
    rmssd = np.random.normal(40.0, 8.0)
    skin_temp = np.random.normal(33.0, 0.3)
    
    records = []
    current_time = base_time
    
    for i in range(num_records):
        current_time += timedelta(seconds=random.randint(1, 2))
        
        # Simulação de mudança de atividade ao longo do tempo
        if i < num_records * 0.3:
            activity = 0  # Repouso
            mu_hr_t = 70.0
        elif i < num_records * 0.6:
            activity = 1  # Atividade moderada
            mu_hr_t = 90.0
        elif i < num_records * 0.8:
            activity = 2  # Atividade intensa
            mu_hr_t = 130.0
        else:
            activity = 0  # Recuperação
            mu_hr_t = 75.0
        
        # Evolução O-U do HR
        dW = np.random.normal(0, 1)
        hr = hr + theta_hr * (mu_hr_t - hr) * dt + sigma_hr * np.sqrt(dt) * dW
        hr = np.clip(hr, 30, 220)
        
        # RMSSD inversamente correlacionado com HR (tônus vagal ↓ quando HR ↑)
        rmssd_target = 60.0 - 0.3 * (hr - 70.0)
        rmssd = rmssd + 0.3 * (rmssd_target - rmssd) + np.random.normal(0, 2.0)
        rmssd = max(5.0, rmssd)
        
        # Temperatura cutânea — dinâmica muito lenta
        skin_temp = skin_temp + 0.05 * (33.0 - skin_temp) + np.random.normal(0, 0.05)
        skin_temp = np.clip(skin_temp, 30.0, 38.0)
        
        records.append({
            'timestamp': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'heart_rate': round(hr, 1),
            'hrv_rmssd': round(rmssd, 2),
            'skin_temp': round(skin_temp, 2),
            'activity_level': activity
        })
    
    return pd.DataFrame(records)


if __name__ == '__main__':
    print("=== Teste: Geração de dados com O-U ===")
    df_sensor = generate_sensor_data(num_records=20)
    print(df_sensor.head(10))
    
    print("\n=== Teste: Dados populacionais com covariância ===")
    df_pop = generate_historical_population_data(num_patients=100)
    print(f"Correlação BPM-Sono: {df_pop['media_bpm_repouso'].corr(df_pop['horas_sono']):.3f}")
    print(f"Correlação BPM-Atividade: {df_pop['media_bpm_repouso'].corr(df_pop['minutos_atividade_intensa']):.3f}")
    
    print("\n=== Teste: Intervalos R-R ===")
    rr = generate_rr_intervals(df_sensor[df_sensor['sensor_id'] == 'pixel_watch']['heart_rate'])
    print(f"R-R médio: {rr.mean():.1f} ms, SDNN: {rr.std():.1f} ms")
    
    print("\n=== Teste: Dados multimodais ===")
    df_multi = generate_wearable_multimodal_data(num_records=10)
    print(df_multi)
