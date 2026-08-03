"""
chaos_fractal.py — Matemática Fractal e Teoria do Caos em Sinais Fisiológicos
=============================================================================

Este módulo implementa algoritmos de análise não-linear, teoria do caos e 
geometria fractal para quantificar a complexidade de sinais biométricos 
(e.g., variabilidade da frequência cardíaca, SpO2, hemodinâmica).

Métodos Implementados:
    1. **Dimensão Fractal de Higuchi (HFD)**:
       Mede a dimensão fractal de séries temporais no domínio do tempo.
    2. **Dimensão Fractal de Katz (KFD)**:
       Quantifica a auto-similaridade da curva do sinal fisiológico.
    3. **Expoente de Hurst (H)**:
       Avalia a memória de longo prazo e persistência do sinal (comportamento caótico vs. aleatório).
    4. **Maior Expoente de Lyapunov Local (LLE)**:
       Mede a sensibilidade às condições iniciais (divergência exponencial de trajetórias no espaço de fase).
"""

import logging
from typing import Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

class FractalChaosAnalyzer:
    """
    Analisador de Teoria do Caos e Geometria Fractal para séries temporais biomédicas.
    """

    def __init__(self, k_max: int = 10, delay: int = 1, embed_dim: int = 3) -> None:
        self.k_max = k_max
        self.delay = delay
        self.embed_dim = embed_dim

    def higuchi_fractal_dimension(self, series: np.ndarray) -> float:
        """
        Calcula a Dimensão Fractal de Higuchi (HFD).
        """
        x = np.asarray(series, dtype=np.float64)
        N = len(x)
        if N < self.k_max * 2:
            return 1.0

        L = []
        x_reg = []
        y_reg = []

        for k in range(1, self.k_max + 1):
            Lk = 0.0
            for m in range(k):
                # Sub-série de passo k iniciando em m
                indices = np.arange(m, N, k)
                if len(indices) < 2:
                    continue
                sub_seq = x[indices]
                Lm = np.sum(np.abs(np.diff(sub_seq)))
                norm_factor = (N - 1) / (len(sub_seq) * k)
                Lk += (Lm * norm_factor) / k

            Lk /= k
            if Lk > 0:
                x_reg.append(np.log(1.0 / k))
                y_reg.append(np.log(Lk))

        if len(x_reg) < 2:
            return 1.0

        # Regressão linear slope = Dimensão Fractal
        poly = np.polyfit(x_reg, y_reg, 1)
        hfd = float(poly[0])
        return max(1.0, min(2.0, hfd))

    def katz_fractal_dimension(self, series: np.ndarray) -> float:
        """
        Calcula a Dimensão Fractal de Katz (KFD).
        """
        x = np.asarray(series, dtype=np.float64)
        N = len(x)
        if N < 3:
            return 1.0

        # Distância acumulada entre pontos consecutivos
        dists = np.sqrt(1.0 + np.diff(x)**2)
        L = np.sum(dists)

        # Distância máxima ao primeiro ponto
        d_max = np.max(np.sqrt(np.arange(N)**2 + (x - x[0])**2))

        if d_max == 0 or L == 0:
            return 1.0

        a = L / d_max
        n = L / (np.mean(dists) if np.mean(dists) > 0 else 1.0)
        
        kfd = np.log10(n) / (np.log10(n) + np.log10(d_max / L) if (np.log10(n) + np.log10(d_max / L)) != 0 else 1.0)
        return float(max(1.0, min(2.0, abs(kfd))))

    def hurst_exponent(self, series: np.ndarray) -> float:
        """
        Calcula o Expoente de Hurst (H) via R/S Analysis (Rescaled Range).
        H > 0.5: Comportamento persistente (tendência)
        H = 0.5: Passeio aleatório (ruído branco)
        H < 0.5: Comportamento anti-persistente (reversão à média)
        """
        x = np.asarray(series, dtype=np.float64)
        N = len(x)
        if N < 20:
            return 0.5

        # Sub-divisões de tamanhos n
        n_vals = np.floor(np.logspace(np.log10(10), np.log10(N // 2), num=8)).astype(int)
        n_vals = np.unique(n_vals)
        
        rs_means = []

        for n in n_vals:
            n_chunks = N // n
            if n_chunks == 0:
                continue
            
            rs_list = []
            for i in range(n_chunks):
                chunk = x[i*n : (i+1)*n]
                mean = np.mean(chunk)
                deviations = chunk - mean
                cum_deviations = np.cumsum(deviations)
                R = np.max(cum_deviations) - np.min(cum_deviations)
                S = np.std(chunk)
                if S > 1e-9:
                    rs_list.append(R / S)

            if len(rs_list) > 0:
                rs_means.append(np.mean(rs_list))

        if len(rs_means) < 2:
            return 0.5

        poly = np.polyfit(np.log(n_vals[:len(rs_means)]), np.log(rs_means), 1)
        h = float(poly[0])
        return float(max(0.0, min(1.0, h)))

    def local_lyapunov_exponent(self, series: np.ndarray) -> float:
        """
        Estima o Maior Expoente de Lyapunov Local (LLE) para quantificar o caos determinístico.
        LLE > 0 indica sensibilidade caótica às condições iniciais.
        """
        x = np.asarray(series, dtype=np.float64)
        N = len(x)
        M = self.embed_dim
        tau = self.delay

        if N < (M * tau + 10):
            return 0.0

        # Reconstrução do espaço de fase (Embedding)
        K = N - (M - 1) * tau
        phase_space = np.zeros((K, M))
        for m in range(M):
            phase_space[:, m] = x[m * tau : m * tau + K]

        # Encontrar os vizinhos mais próximos
        divergence = []
        for i in range(K - 5):
            distances = np.linalg.norm(phase_space - phase_space[i], axis=1)
            distances[i] = np.inf  # Ignorar o próprio ponto
            nearest_idx = np.argmin(distances)
            d0 = distances[nearest_idx]

            if d0 > 1e-9 and (i + 1 < K) and (nearest_idx + 1 < K):
                d1 = np.linalg.norm(phase_space[i + 1] - phase_space[nearest_idx + 1])
                if d1 > 0:
                    divergence.append(np.log(d1 / d0))

        if len(divergence) == 0:
            return 0.0

        lle = float(np.mean(divergence))
        return float(np.clip(lle, -2.0, 5.0))

    def analyze(self, series: np.ndarray) -> Dict[str, float]:
        """
        Análise completa de Caos e Geometria Fractal.
        """
        return {
            "higuchi_fd": self.higuchi_fractal_dimension(series),
            "katz_fd": self.katz_fractal_dimension(series),
            "hurst_exponent": self.hurst_exponent(series),
            "lyapunov_lle": self.local_lyapunov_exponent(series),
        }
