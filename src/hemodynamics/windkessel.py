"""
Módulo de Hemodinâmica Avançada — Modelo Windkessel de 4 Elementos e Barorreflexo.

Implementa a mecânica de fluidos cardiovasculares de parâmetros concentrados (lumped parameters),
propagação de onda de pulso (PWV) e acoplamento neurovegetativo com o barorreflexo.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class Windkessel4EParams:
    """
    Parâmetros do Modelo Windkessel de 4 Elementos (WK4).
    
    Unidades padrão:
        - Rp (Resistência Periférica Total): mmHg · s / mL (~0.9 - 1.2)
        - C (Complacência Arterial Total): mL / mmHg (~1.0 - 1.8)
        - Zc (Impedância Característica Aórtica): mmHg · s / mL (~0.03 - 0.08)
        - L (Inertância do Sangue Arterial): mmHg · s² / mL (~0.003 - 0.008)
    """
    Rp: float = 1.05     # Resistência periférica sistêmica
    C: float = 1.35      # Complacência da árvore arterial elástica
    Zc: float = 0.05     # Impedância característica da aorta proximal
    L: float = 0.005     # Inertância da coluna de sangue ejetada
    P_venous: float = 4.0 # Pressão venosa central de referência (mmHg)


@dataclass
class BaroreflexParams:
    """
    Parâmetros da alça de controle autonômico do Barorreflexo do Seio Carotídeo.
    """
    P_setpoint: float = 93.3   # Pressão Arterial Média alvo (mmHg) ~ (2*PAD + PAS)/3
    gain_hr: float = 0.65       # Ganho da modulação de FC (bpm / mmHg)
    gain_rp: float = 0.008      # Ganho da modulação vasomotora de Rp (unidades / mmHg)
    tau_symp: float = 3.0       # Constante de tempo da resposta simpática (s)
    f_max: float = 100.0        # Taxa de disparo barorreceptora máxima (Hz)
    k_slope: float = 0.08       # Inclinação da função sigmoide barorreceptora


@dataclass
class WindkesselSimResult:
    t: np.ndarray
    pressure: np.ndarray
    flow: np.ndarray
    systolic_bp: float
    diastolic_bp: float
    mean_arterial_pressure: float
    pulse_pressure: float
    pwv_bramwell_hill: float

    def __getitem__(self, key: str) -> Any:
        if key == "time":
            return self.t
        return getattr(self, str(key))

    def __contains__(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        return (key == "time") or hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (AttributeError, KeyError):
            return default

    def keys(self) -> List[str]:
        return ["time", "pressure", "flow", "systolic_bp", "diastolic_bp", "mean_arterial_pressure", "pulse_pressure", "pwv_bramwell_hill"]


class Windkessel4ESimulator:
    """
    Simulador hemodinâmico baseado nas equações constitutivas do Windkessel de 4 elementos.
    
    Equação diferencial acoplada:
        (1 + Zc/Rp) * dP/dt + P/(Rp*C) = Q(t)/C + (Zc + L/(Rp*C)) * dQ/dt + L * d²Q/dt²
    """

    def __init__(self, params: Optional[Windkessel4EParams] = None, baro_params: Optional[BaroreflexParams] = None, baroreflex: Optional[BaroreflexParams] = None):
        self.params = params or Windkessel4EParams()
        self.baro = baro_params or baroreflex or BaroreflexParams()

    @staticmethod
    def generate_ejection_flow(
        heart_rate: float,
        stroke_volume: float = 70.0,
        ejection_fraction_duration: float = 0.35,
        fs: float = 200.0,
        num_cycles: int = 5
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Gera a forma de onda do fluxo de ejeção aórtica Q(t) (mL/s).
        
        Args:
            heart_rate: Frequência cardíaca (bpm)
            stroke_volume: Volume sistólico ejetado por batimento (mL)
            ejection_fraction_duration: Fração do ciclo cardíaco correspondente à sístole (~0.30 - 0.38)
            fs: Frequência de amostragem temporal (Hz)
            num_cycles: Quantidade de batimentos a simular
        """
        t_cycle = 60.0 / max(30.0, heart_rate)
        t_systole = t_cycle * ejection_fraction_duration
        dt = 1.0 / fs
        time = np.arange(0, num_cycles * t_cycle, dt)
        flow = np.zeros_like(time)

        # Amplitude de pico para que a integral no ciclo seja o Volume Sistólico
        # Integral de Q_peak * sin(pi * t / T_sys) de 0 a T_sys = Q_peak * (2 * T_sys / pi) = SV
        q_peak = (stroke_volume * np.pi) / (2.0 * t_systole)

        for i, t in enumerate(time):
            t_phase = t % t_cycle
            if t_phase < t_systole:
                flow[i] = q_peak * np.sin(np.pi * t_phase / t_systole)
            else:
                flow[i] = 0.0

        return time, flow

    def simulate(
        self,
        time: Optional[np.ndarray] = None,
        flow: Optional[np.ndarray] = None,
        duration_s: float = 3.0,
        dt: float = 0.005,
        heart_rate: float = 75.0,
        stroke_volume: float = 70.0,
        initial_pressure: float = 80.0
    ) -> WindkesselSimResult:
        """
        Integra a equação de pressão arterial P(t) usando método de Runge-Kutta de 4ª ordem (RK4).
        """
        if time is None or flow is None:
            num_cycles = max(2, int(duration_s * heart_rate / 60.0) + 1)
            time, flow = self.generate_ejection_flow(
                heart_rate=heart_rate,
                stroke_volume=stroke_volume,
                fs=1.0 / dt,
                num_cycles=num_cycles
            )
        else:
            dt = float(time[1] - time[0])

        n = len(time)
        
        # Derivadas do fluxo Q(t)
        dq_dt = np.gradient(flow, dt)
        d2q_dt2 = np.gradient(dq_dt, dt)

        p = np.zeros(n)
        p[0] = initial_pressure

        rp = self.params.Rp
        c = self.params.C
        zc = self.params.Zc
        l = self.params.L

        alpha = 1.0 + (zc / rp)

        def dp_dt_func(p_curr: float, q_val: float, dq_val: float, d2q_val: float) -> float:
            rhs = (q_val / c) + (zc + l / (rp * c)) * dq_val + l * d2q_val - (p_curr / (rp * c))
            return rhs / alpha

        for i in range(n - 1):
            k1 = dp_dt_func(p[i], flow[i], dq_dt[i], d2q_dt2[i])
            
            p_mid1 = p[i] + 0.5 * dt * k1
            q_mid = 0.5 * (flow[i] + flow[i+1])
            dq_mid = 0.5 * (dq_dt[i] + dq_dt[i+1])
            d2q_mid = 0.5 * (d2q_dt2[i] + d2q_dt2[i+1])
            k2 = dp_dt_func(p_mid1, q_mid, dq_mid, d2q_mid)
            
            p_mid2 = p[i] + 0.5 * dt * k2
            k3 = dp_dt_func(p_mid2, q_mid, dq_mid, d2q_mid)
            
            p_end = p[i] + dt * k3
            k4 = dp_dt_func(p_end, flow[i+1], dq_dt[i+1], d2q_dt2[i+1])

            p[i+1] = p[i] + (dt / 6.0) * (k1 + 2*k2 + 2*k3 + k4)

        # Extrair métricas hemodinâmicas do último ciclo estável
        pas = float(np.max(p[-int(len(p)*0.3):]))
        pad = float(np.min(p[-int(len(p)*0.3):]))
        map_val = float(np.mean(p[-int(len(p)*0.3):]))
        pp = pas - pad
        pwv = self.compute_pulse_wave_velocity(distensibility=c * 0.001)

        return WindkesselSimResult(
            t=time,
            pressure=p,
            flow=flow,
            systolic_bp=pas,
            diastolic_bp=pad,
            mean_arterial_pressure=map_val,
            pulse_pressure=pp,
            pwv_bramwell_hill=pwv
        )

    def compute_pulse_wave_velocity(self, distensibility: float = 0.002, blood_density: float = 1060.0) -> float:
        """
        Calcula a Velocidade da Onda de Pulso (PWV) usando a relação de Bramwell-Hill.
        
        PWV = sqrt(1 / (rho * Distensibility)) (m/s)
        
        Valores clínicos:
            - Jovem saudável: 5 - 7 m/s
            - Rigidez arterial moderada: 8 - 10 m/s
            - Alto risco cardiovascular: > 10 m/s
        """
        # Distensibilidade em Pa^-1 (1 mmHg = 133.322 Pa)
        dist_pa = distensibility / 133.322
        pwv = np.sqrt(1.0 / (blood_density * dist_pa))
        return float(pwv)

    def evaluate_baroreflex(self, current_map: float, current_hr: float) -> Dict[str, float]:
        """
        Calcula a resposta compensatória do barorreflexo para adaptação de FC e Rp.
        """
        delta_p = current_map - self.baro.P_setpoint
        
        # Resposta sigmoide de disparo dos barorreceptores
        firing_rate = self.baro.f_max / (1.0 + np.exp(-self.baro.k_slope * delta_p))
        
        # Modulação de FC (feedback negativo)
        delta_hr = - self.baro.gain_hr * delta_p
        adjusted_hr = np.clip(current_hr + delta_hr, 40.0, 180.0)
        
        # Modulação vasomotora de Rp
        delta_rp = - self.baro.gain_rp * delta_p
        adjusted_rp = np.clip(self.params.Rp + delta_rp, 0.4, 2.5)

        return {
            "delta_map": delta_p,
            "baroreceptor_firing_hz": float(firing_rate),
            "adjusted_heart_rate": float(adjusted_hr),
            "adjusted_rp": float(adjusted_rp),
            "vagal_tone_proxy": float(firing_rate / self.baro.f_max)
        }
