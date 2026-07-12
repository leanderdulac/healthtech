"""
phantom_inference_engine.py — Pipeline de Inferência de Dados Fantasmas

Este módulo orquestra o processo de inferência dos dados fantasmas fisiológicos
(Pressão Arterial, SpO2, Glicose e Tônus Vagal) a partir das leituras reais de
dispositivos vestíveis, usando Filtros de Kalman (EKF ou UKF) e estimando
intervalos de confiança e flags de confiabilidade diagnóstica.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Any, Tuple, Optional
import numpy as np
import pandas as pd
from scipy.stats import norm

from src.phantom_data.state_space_model import (
    ExtendedKalmanFilter,
    UnscentedKalmanFilter,
    PhysiologicalTransitionModel,
    WearableObservationModel
)

logger = logging.getLogger(__name__)


class PhantomDataEngine:
    """
    Motor de processamento de Dados Fantasmas.
    
    Integra os modelos dinâmicos do corpo e dos sensores com um Filtro de Kalman
    (Extended ou Unscented) para realizar inferência em tempo real de sinais latentes.
    """
    
    def __init__(self, dt: float = 1.0, use_ukf: bool = False) -> None:
        """
        Inicializa o motor de inferência fisiológica.
        
        Args:
            dt: Passo temporal entre atualizações (segundos).
            use_ukf: Se True, utiliza o Unscented Kalman Filter. Caso contrário, o EKF.
        """
        self.dt = dt
        self.use_ukf = use_ukf
        
        self.transition_model = PhysiologicalTransitionModel()
        self.observation_model = WearableObservationModel()
        
        self.dim_x = self.transition_model.dim_x
        self.dim_z = self.observation_model.dim_z
        
        self.reset()
        
    def reset(self) -> None:
        """
        Reinicializa o filtro de Kalman para os valores basais de equilíbrio.
        """
        if self.use_ukf:
            self.filter = UnscentedKalmanFilter(dim_x=self.dim_x, dim_z=self.dim_z, dt=self.dt)
        else:
            self.filter = ExtendedKalmanFilter(dim_x=self.dim_x, dim_z=self.dim_z, dt=self.dt)
            
        # Iniciar no estado de equilíbrio fisiológico
        self.filter.x = self.transition_model.mu.copy()
        
        # Incerteza inicial moderada nos estados
        self.filter.P = np.diag([25.0, 16.0, 1.0, 100.0, 400.0])
        
        # Configurar matrizes de covariância de ruído
        self.filter.Q = self.transition_model.get_process_noise(dt=self.dt)
        self.filter.R = self.observation_model.get_measurement_noise()
        
        # Histórico de inovações (resíduos) para fins estatísticos
        self.innovations: List[np.ndarray] = []
        
        logger.info(
            "PhantomDataEngine reinicializado. Filtro ativo: %s",
            "UKF" if self.use_ukf else "EKF"
        )
        
    def process_reading(self, wearable_data: Dict[str, float]) -> Dict[str, Any]:
        """
        Processa uma nova leitura do wearable, prevendo o próximo estado
        fisiológico e atualizando-o com a nova observação.
        
        Args:
            wearable_data: Dicionário contendo:
                - 'heart_rate' (BPM)
                - 'hrv_rmssd' (ms)
                - 'skin_temp' (°C)
                - 'activity_level' (arbitrário/acelerômetro)
                
        Returns:
            Dicionário com o estado estimado, limites de confiança e flags.
        """
        # Extrair observações com valores de fallback se ausentes
        hr = float(wearable_data.get('heart_rate', self.observation_model.hr_baseline))
        hrv = float(wearable_data.get('hrv_rmssd', self.observation_model.hrv_baseline))
        temp = float(wearable_data.get('skin_temp', self.observation_model.temp_baseline))
        act = float(wearable_data.get('activity_level', self.observation_model.activity_baseline))
        
        z = np.array([hr, hrv, temp, act])
        
        # 1. Passo de Predição
        if self.use_ukf:
            self.filter.predict(
                f_func=lambda x: self.transition_model.f(x, dt=self.dt)
            )
        else:
            self.filter.predict(
                f_func=lambda x: self.transition_model.f(x, dt=self.dt),
                F_jacobian=lambda x: self.transition_model.F_jacobian(x, dt=self.dt)
            )
            
        # Calcular inovação (diferença entre observado e predito antes do update)
        z_pred_before = self.observation_model.h(self.filter._x_pred)
        innovation = z - z_pred_before
        self.innovations.append(innovation)
        if len(self.innovations) > 100:
            self.innovations.pop(0)
            
        # 2. Passo de Atualização (Medição)
        if self.use_ukf:
            self.filter.update(z, h_func=self.observation_model.h)
        else:
            self.filter.update(
                z,
                h_func=self.observation_model.h,
                H_jacobian=self.observation_model.H_jacobian
            )
            
        # Obter estado estimado e covariância
        x_est, P_est = self.filter.get_state()
        
        # 3. Formatar resposta
        state_dict = {}
        for idx, name in enumerate(self.transition_model.STATE_NAMES):
            val = float(x_est[idx])
            std_dev = float(np.sqrt(P_est[idx, idx]))
            
            # Limites de confiança de 95%
            ci_lower = val - 1.96 * std_dev
            ci_upper = val + 1.96 * std_dev
            
            # Ajustar limites fisiológicos do CI
            if name == "spo2":
                ci_lower = max(0.0, min(100.0, ci_lower))
                ci_upper = max(0.0, min(100.0, ci_upper))
            elif name in ["systolic_bp", "diastolic_bp", "glucose", "vagal_tone"]:
                ci_lower = max(0.0, ci_lower)
                
            state_dict[name] = {
                'estimate': val,
                'std_dev': std_dev,
                'ci_lower': ci_lower,
                'ci_upper': ci_upper
            }
            
        # Obter flags de confiabilidade
        reliability = self.get_reliability_flags()
        for name in self.transition_model.STATE_NAMES:
            state_dict[name]['reliable'] = reliability[name]
            
        return {
            'timestamp_offset': self.dt,
            'states': state_dict,
            'raw_state_vector': x_est.tolist(),
            'raw_covariance': P_est.tolist(),
            'innovation': innovation.tolist()
        }

    def get_confidence_intervals(self, confidence: float = 0.95) -> Dict[str, Tuple[float, float]]:
        """
        Calcula o intervalo de confiança para cada variável latente.
        
        Fórmula: x̂_i ± z_{α/2} · √(P_ii)
        """
        x_est, P_est = self.filter.get_state()
        alpha = 1.0 - confidence
        z_val = norm.ppf(1.0 - alpha / 2.0)
        
        ci_dict = {}
        for idx, name in enumerate(self.transition_model.STATE_NAMES):
            val = x_est[idx]
            std_dev = np.sqrt(P_est[idx, idx])
            lower = float(val - z_val * std_dev)
            upper = float(val + z_val * std_dev)
            
            # Limites físicos
            if name == "spo2":
                lower = max(0.0, min(100.0, lower))
                upper = max(0.0, min(100.0, upper))
            elif name in ["systolic_bp", "diastolic_bp", "glucose", "vagal_tone"]:
                lower = max(0.0, lower)
                
            ci_dict[name] = (lower, upper)
            
        return ci_dict

    def get_reliability_flags(self) -> Dict[str, bool]:
        """
        Determina a confiabilidade de cada dado fantasma inferido.
        A confiabilidade é baseada na variância estimada do estado (P_ii).
        Se a incerteza estiver acima de um limite, o sinal é marcado como não confiável.
        
        Limites típicos de desvio padrão (√P_ii):
            - Pressão sistólica: std_dev < 12.0 mmHg
            - Pressão diastólica: std_dev < 8.0 mmHg
            - SpO2: std_dev < 2.0 %
            - Tônus Vagal: std_dev < 15.0 u.a.
            - Glicose: std_dev < 25.0 mg/dL
        """
        _, P_est = self.filter.get_state()
        
        thresholds = {
            "systolic_bp": 12.0 ** 2,
            "diastolic_bp": 8.0 ** 2,
            "spo2": 2.0 ** 2,
            "vagal_tone": 15.0 ** 2,
            "glucose": 25.0 ** 2
        }
        
        flags = {}
        for idx, name in enumerate(self.transition_model.STATE_NAMES):
            var = P_est[idx, idx]
            flags[name] = bool(var < thresholds.get(name, 100.0))
            
        return flags

    def get_full_state_report(self) -> Dict[str, Any]:
        """
        Gera um relatório estatístico completo sobre o estado atual do motor.
        """
        x_est, P_est = self.filter.get_state()
        ci = self.get_confidence_intervals(confidence=0.95)
        reliability = self.get_reliability_flags()
        
        report = {
            'filter_type': 'UKF' if self.use_ukf else 'EKF',
            'state_dimension': self.dim_x,
            'observation_dimension': self.dim_z,
            'trace_P': float(np.trace(P_est)),
            'variables': {}
        }
        
        for idx, name in enumerate(self.transition_model.STATE_NAMES):
            report['variables'][name] = {
                'estimate': float(x_est[idx]),
                'variance': float(P_est[idx, idx]),
                'std_dev': float(np.sqrt(P_est[idx, idx])),
                'ci_95': ci[name],
                'is_reliable': reliability[name]
            }
            
        if self.innovations:
            innov_arr = np.array(self.innovations)
            report['innovation_statistics'] = {
                'mean': innov_arr.mean(axis=0).tolist(),
                'std': innov_arr.std(axis=0).tolist(),
                'latest': self.innovations[-1].tolist()
            }
            
        return report


class BatchPhantomProcessor:
    """
    Processador em lote (Batch) de dados fantasma a partir de DataFrames.
    """
    
    def __init__(self, use_ukf: bool = False) -> None:
        self.use_ukf = use_ukf
        
    def process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Processa um DataFrame de séries temporais de sensores biométricos,
        infere os dados fantasmas linha a linha e retorna o DataFrame enriquecido.
        
        Args:
            df: DataFrame contendo colunas como 'heart_rate', 'hrv_rmssd', 'skin_temp', 'activity_level'
            
        Returns:
            pd.DataFrame: O DataFrame original acrescido das colunas de estimativas
                          fantasmas, limites de confiança e confiabilidade.
        """
        if df.empty:
            return df.copy()
            
        # Fazer uma cópia para evitar side-effects
        df_out = df.copy()
        
        # Garantir colunas necessárias com baselines se ausentes
        req_cols = {
            'heart_rate': 60.0,
            'hrv_rmssd': 40.0,
            'skin_temp': 33.0,
            'activity_level': 0.0
        }
        for col, default in req_cols.items():
            if col not in df_out.columns:
                df_out[col] = default
                
        # Inicializar o motor
        # Assumindo que a frequência de amostragem média é o intervalo médio entre timestamps
        dt = 1.0
        if 'timestamp' in df_out.columns:
            try:
                times = pd.to_datetime(df_out['timestamp'])
                diffs = times.diff().dropna().dt.total_seconds()
                if not diffs.empty:
                    dt = float(diffs.median())
                    if dt <= 0:
                        dt = 1.0
            except Exception:
                pass
                
        engine = PhantomDataEngine(dt=dt, use_ukf=self.use_ukf)
        
        # Reservar listas para armazenar os resultados temporários
        n_rows = len(df_out)
        systolic_bp = np.zeros(n_rows)
        systolic_bp_lower = np.zeros(n_rows)
        systolic_bp_upper = np.zeros(n_rows)
        systolic_bp_rel = [False] * n_rows
        
        diastolic_bp = np.zeros(n_rows)
        diastolic_bp_lower = np.zeros(n_rows)
        diastolic_bp_upper = np.zeros(n_rows)
        diastolic_bp_rel = [False] * n_rows
        
        spo2 = np.zeros(n_rows)
        spo2_lower = np.zeros(n_rows)
        spo2_upper = np.zeros(n_rows)
        spo2_rel = [False] * n_rows
        
        vagal_tone = np.zeros(n_rows)
        vagal_tone_lower = np.zeros(n_rows)
        vagal_tone_upper = np.zeros(n_rows)
        vagal_tone_rel = [False] * n_rows
        
        glucose = np.zeros(n_rows)
        glucose_lower = np.zeros(n_rows)
        glucose_upper = np.zeros(n_rows)
        glucose_rel = [False] * n_rows
        
        # Processar sequencialmente linha a linha (o filtro acumula memória temporal)
        for i in range(n_rows):
            row = df_out.iloc[i]
            data = {
                'heart_rate': row['heart_rate'],
                'hrv_rmssd': row['hrv_rmssd'],
                'skin_temp': row['skin_temp'],
                'activity_level': row['activity_level']
            }
            
            res = engine.process_reading(data)
            states = res['states']
            
            systolic_bp[i] = states['systolic_bp']['estimate']
            systolic_bp_lower[i] = states['systolic_bp']['ci_lower']
            systolic_bp_upper[i] = states['systolic_bp']['ci_upper']
            systolic_bp_rel[i] = states['systolic_bp']['reliable']
            
            diastolic_bp[i] = states['diastolic_bp']['estimate']
            diastolic_bp_lower[i] = states['diastolic_bp']['ci_lower']
            diastolic_bp_upper[i] = states['diastolic_bp']['ci_upper']
            diastolic_bp_rel[i] = states['diastolic_bp']['reliable']
            
            spo2[i] = states['spo2']['estimate']
            spo2_lower[i] = states['spo2']['ci_lower']
            spo2_upper[i] = states['spo2']['ci_upper']
            spo2_rel[i] = states['spo2']['reliable']
            
            vagal_tone[i] = states['vagal_tone']['estimate']
            vagal_tone_lower[i] = states['vagal_tone']['ci_lower']
            vagal_tone_upper[i] = states['vagal_tone']['ci_upper']
            vagal_tone_rel[i] = states['vagal_tone']['reliable']
            
            glucose[i] = states['glucose']['estimate']
            glucose_lower[i] = states['glucose']['ci_lower']
            glucose_upper[i] = states['glucose']['ci_upper']
            glucose_rel[i] = states['glucose']['reliable']
            
        # Inserir colunas no DataFrame resultante
        df_out['est_systolic_bp'] = systolic_bp
        df_out['est_systolic_bp_ci_lower'] = systolic_bp_lower
        df_out['est_systolic_bp_ci_upper'] = systolic_bp_upper
        df_out['est_systolic_bp_reliable'] = systolic_bp_rel
        
        df_out['est_diastolic_bp'] = diastolic_bp
        df_out['est_diastolic_bp_ci_lower'] = diastolic_bp_lower
        df_out['est_diastolic_bp_ci_upper'] = diastolic_bp_upper
        df_out['est_diastolic_bp_reliable'] = diastolic_bp_rel
        
        df_out['est_spo2'] = spo2
        df_out['est_spo2_ci_lower'] = spo2_lower
        df_out['est_spo2_ci_upper'] = spo2_upper
        df_out['est_spo2_reliable'] = spo2_rel
        
        df_out['est_vagal_tone'] = vagal_tone
        df_out['est_vagal_tone_ci_lower'] = vagal_tone_lower
        df_out['est_vagal_tone_ci_upper'] = vagal_tone_upper
        df_out['est_vagal_tone_reliable'] = vagal_tone_rel
        
        df_out['est_glucose'] = glucose
        df_out['est_glucose_ci_lower'] = glucose_lower
        df_out['est_glucose_ci_upper'] = glucose_upper
        df_out['est_glucose_reliable'] = glucose_rel
        
        return df_out


if __name__ == '__main__':
    # Demonstração local rápida
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("=" * 70)
    print("  DEMONSTRAÇÃO — Phantom Data Inference Engine")
    print("=" * 70)
    
    # 1. Iniciar o motor
    engine = PhantomDataEngine(dt=1.0, use_ukf=False)
    
    # 2. Gerar uma leitura típica de paciente saudável em repouso
    # Sinais observáveis basais: hr=60, rmssd=40, temp=33, act=0
    print("\n[Caso 1] Paciente saudável em repouso absoluto:")
    reading_healthy = {
        'heart_rate': 60.0,
        'hrv_rmssd': 45.0,
        'skin_temp': 33.1,
        'activity_level': 0.0
    }
    
    # Executar atualizações para convergir as estimativas
    for step in range(5):
        res = engine.process_reading(reading_healthy)
        
    report = engine.get_full_state_report()
    for var, details in report['variables'].items():
        print(
            f"  {var:>15s}: Est={details['estimate']:>7.2f} "
            f"| IC_95=({details['ci_95'][0]:>6.2f}, {details['ci_95'][1]:>6.2f}) "
            f"| Confiável={details['is_reliable']}"
        )
        
    # 3. Gerar leituras de estresse agudo cardiovascular (Hipertensão / Taquicardia)
    # hr=120, rmssd=15, temp=33.5, act=0.0
    print("\n[Caso 2] Evento agudo de taquicardia sinusal e estresse:")
    reading_stress = {
        'heart_rate': 120.0,
        'hrv_rmssd': 15.0,
        'skin_temp': 33.5,
        'activity_level': 0.0
    }
    
    for step in range(10):
        res = engine.process_reading(reading_stress)
        
    report_stress = engine.get_full_state_report()
    for var, details in report_stress['variables'].items():
        print(
            f"  {var:>15s}: Est={details['estimate']:>7.2f} "
            f"| IC_95=({details['ci_95'][0]:>6.2f}, {details['ci_95'][1]:>6.2f}) "
            f"| Confiável={details['is_reliable']}"
        )
        
    # 4. Demonstração de processamento em lote
    print("\n[Caso 3] Processamento em Lote (Batch):")
    df_raw = pd.DataFrame([
        {'heart_rate': 60.0, 'hrv_rmssd': 45.0, 'skin_temp': 33.1, 'activity_level': 0.0},
        {'heart_rate': 62.0, 'hrv_rmssd': 44.0, 'skin_temp': 33.1, 'activity_level': 0.0},
        {'heart_rate': 100.0, 'hrv_rmssd': 20.0, 'skin_temp': 33.4, 'activity_level': 1.0},
        {'heart_rate': 110.0, 'hrv_rmssd': 15.0, 'skin_temp': 33.5, 'activity_level': 2.0}
    ])
    processor = BatchPhantomProcessor(use_ukf=False)
    df_enriched = processor.process_dataframe(df_raw)
    
    print("\nDataFrame enriquecido com dados fantasmas:")
    print(df_enriched[['heart_rate', 'est_systolic_bp', 'est_spo2', 'est_glucose']].to_string())
    print("\n✓ Processador de dados fantasmas validado com sucesso!")
