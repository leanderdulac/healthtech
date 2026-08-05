"""
bmo_analysis.py — Análise de Espaço de Oscilação Média Limitada (BMO) e VMO
============================================================================

Este módulo implementa a teoria do Espaço BMO (Bounded Mean Oscillation),
formalizada por Fritz John e Louis Nirenberg (1961), adaptada para processamento
de sinais biomédicos, imagens médicas (CT, RM, Ultrassom) e telemetria fisiológica.

Matemática do BMO:
------------------
Para um sinal ou função f, a Oscilação Média (Mean Oscillation - MO) em uma janela Q é:
    MO(f, Q) = 1/|Q| * ∫_Q |f(x) - f_Q| dx
onde f_Q é a média de f em Q.

A Norma BMO é o supremo das oscilações médias sobre todas as janelas possíveis Q:
    ||f||_BMO = sup_Q MO(f, Q)

Aplicações Adaptadas para HealthTech:
------------------------------------
1. Denoising Preservador de Bordas sem Efeito Escada (Staircasing):
   Filtro variacional adaptativo que atenua ruídos de alta frequência enquanto
   preserva gradientes anatômicos e picos fisiológicos agudos (complexos QRS, picos EEG).
2. Análise Multiescala de Rugosidade e VMO (Vanishing Mean Oscillation):
   Diferencia variações fisiológicas suaves de descontinuidades patológicas agudas.
3. Imagens Médicas 2D (RM, TC, Ultrassom):
   Cálculo de mapa local BMO e remoção de ruído speckle/gaussiano.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


class BMOAnalyzer:
    """
    Analisador e Filtro Adaptativo baseado no Espaço BMO (Bounded Mean Oscillation).
    """

    def __init__(self, default_scales: Optional[List[int]] = None) -> None:
        """
        Inicializa o analisador BMO.

        Args:
            default_scales: Tamanhos de janelas (em amostras) para análise multiescala.
                            Se None, utiliza [4, 8, 16, 32, 64].
        """
        self.default_scales = default_scales or [4, 8, 16, 32, 64]

    @staticmethod
    def compute_local_mean_oscillation(signal: np.ndarray, window_size: int) -> np.ndarray:
        """
        Calcula a Oscilação Média Local MO(f, Q) para um sinal 1D com janela deslizante de tamanho `window_size`.

        Args:
            signal: Array 1D do sinal fisiológico.
            window_size: Tamanho da janela Q em amostras (deve ser >= 2).

        Returns:
            Array 1D com os valores de MO(f, Q) para cada ponto.
        """
        x = np.asarray(signal, dtype=np.float64)
        N = len(x)
        w = max(2, int(window_size))
        half_w = w // 2

        mo = np.zeros(N, dtype=np.float64)
        
        # Otimização com janela móvel
        for i in range(N):
            start = max(0, i - half_w)
            end = min(N, i + half_w + 1)
            sub = x[start:end]
            mean_q = np.mean(sub)
            mo[i] = np.mean(np.abs(sub - mean_q))

        return mo

    def compute_bmo_norm(self, signal: np.ndarray, scales: Optional[List[int]] = None) -> float:
        """
        Calcula a norma BMO ||f||_BMO (supremo das oscilações médias locais).

        Args:
            signal: Array 1D do sinal fisiológico.
            scales: Lista de tamanhos de janelas. Se None, utiliza os padrões.

        Returns:
            Valor escalar da norma BMO.
        """
        x = np.asarray(signal, dtype=np.float64)
        if len(x) < 2:
            return 0.0

        eval_scales = scales or [s for s in self.default_scales if s < len(x)]
        if not eval_scales:
            eval_scales = [max(2, len(x) // 4)]

        max_oscillation = 0.0
        for w in eval_scales:
            mo_arr = self.compute_local_mean_oscillation(x, w)
            max_w = float(np.max(mo_arr))
            if max_w > max_oscillation:
                max_oscillation = max_w

        return float(max_oscillation)

    def multiscale_bmo_profile(
        self, signal: np.ndarray, scales: Optional[List[int]] = None
    ) -> Dict[str, Union[float, Dict[int, float], List[float]]]:
        """
        Gera o perfil multiescala de oscilação média para séries temporais biomédicas.

        Returns:
            Dicionário com a norma BMO global, oscilações médias por escala,
            e estatísticas da rugosidade local.
        """
        x = np.asarray(signal, dtype=np.float64)
        eval_scales = scales or [s for s in self.default_scales if s < len(x)]
        if not eval_scales:
            eval_scales = [4, 8, 16]

        scale_means: Dict[int, float] = {}
        scale_maxs: Dict[int, float] = {}

        for w in eval_scales:
            mo_arr = self.compute_local_mean_oscillation(x, w)
            scale_means[w] = float(np.mean(mo_arr))
            scale_maxs[w] = float(np.max(mo_arr))

        bmo_norm = float(max(scale_maxs.values())) if scale_maxs else 0.0
        vmo_ratio = self.compute_vmo_index(x, eval_scales[0], eval_scales[-1])

        return {
            "bmo_norm": bmo_norm,
            "vmo_index": vmo_ratio,
            "scale_mean_oscillations": scale_means,
            "scale_max_oscillations": scale_maxs,
        }

    def compute_vmo_index(self, signal: np.ndarray, min_scale: int = 4, max_scale: int = 64) -> float:
        """
        Calcula o índice VMO (Vanishing Mean Oscillation).
        Avalia se a oscilação média tende a zero nas menores escalas (|Q| -> 0).
        Sinais fisiológicos contínuos possuem VMO baixo, enquanto artefatos brutos
        ou picos patológicos agudos elevam a razão de oscilação em pequena escala.

        Returns:
            Razão de oscilação VMO = MO(min_scale) / (MO(max_scale) + 1e-8)
        """
        x = np.asarray(signal, dtype=np.float64)
        if len(x) < max_scale:
            max_scale = max(2, len(x) // 2)
            min_scale = min(min_scale, max_scale)

        mo_small = np.mean(self.compute_local_mean_oscillation(x, min_scale))
        mo_large = np.mean(self.compute_local_mean_oscillation(x, max_scale))

        return float(mo_small / (mo_large + 1e-8))

    def denoise_edge_preserving_1d(
        self, signal: np.ndarray, window_size: int = 8, alpha: float = 0.5
    ) -> np.ndarray:
        """
        Filtro Denoising 1D Adaptativo baseado em BMO.
        
        Evita o efeito escada (staircasing) da Variação Total (TV), suavizando
        ruídos de fundo enquanto preserva bordas acentuadas onde a oscilação local BMO
        é estatisticamente significante.

        Formulação:
            w_i = 1 / (1 + exp(- (MO_i - mean(MO)) / (alpha * std(MO) + 1e-8)))
            y_i = w_i * x_i + (1 - w_i) * local_mean_i

        Args:
            signal: Sinal de entrada 1D.
            window_size: Janela local para estimativa BMO.
            alpha: Sensibilidade da preservação de bordas (0.1 a 2.0).

        Returns:
            Sinal 1D filtrado sem efeito escada e com bordas preservadas.
        """
        x = np.asarray(signal, dtype=np.float64)
        N = len(x)
        if N < 4:
            return x.copy()

        mo = self.compute_local_mean_oscillation(x, window_size)
        mean_mo = np.mean(mo)
        std_mo = np.std(mo)

        if std_mo < 1e-8:
            return x.copy()

        # Peso sigmoidal adaptativo baseado em BMO
        z_mo = (mo - mean_mo) / (alpha * std_mo + 1e-8)
        weights = 1.0 / (1.0 + np.exp(-z_mo))

        # Média móvel suave para áreas de baixa oscilação
        smooth_base = np.convolve(x, np.ones(window_size) / window_size, mode="same")

        # Combinação convexa: preserva o sinal original onde BMO é alto, usa suave onde BMO é baixo
        filtered = weights * x + (1.0 - weights) * smooth_base
        return filtered

    @staticmethod
    def compute_bmo_2d(image: np.ndarray, window_size: int = 5) -> np.ndarray:
        """
        Calcula o mapa local de Oscilação Média BMO para imagens médicas 2D (ex: TC, RM, Ultrassom).

        Args:
            image: Matriz 2D da imagem médica ou espectrograma.
            window_size: Tamanho do bloco 2D Q (ex: 3, 5, 7).

        Returns:
            Matriz 2D do mesmo formato contendo os valores de MO(f, Q) locais.
        """
        img = np.asarray(image, dtype=np.float64)
        rows, cols = img.shape
        w = max(3, int(window_size))
        half_w = w // 2

        mo_map = np.zeros((rows, cols), dtype=np.float64)

        for r in range(rows):
            r_start = max(0, r - half_w)
            r_end = min(rows, r + half_w + 1)
            for c in range(cols):
                c_start = max(0, c - half_w)
                c_end = min(cols, c + half_w + 1)

                patch = img[r_start:r_end, c_start:c_end]
                mean_patch = np.mean(patch)
                mo_map[r, c] = np.mean(np.abs(patch - mean_patch))

        return mo_map

    def denoise_image_2d_bmo(
        self, image: np.ndarray, window_size: int = 5, lambda_param: float = 0.5
    ) -> np.ndarray:
        """
        Filtro de Imagens Médicas 2D baseado em BMO.
        
        Suprime ruído de speckle (ultrassom) e ruído gaussiano (TC/RM) sem gerar
        o artefato de escada típico de algoritmos de Total Variation (TV).

        Args:
            image: Imagem médica 2D de entrada.
            window_size: Tamanho do patch 2D.
            lambda_param: Parâmetro de limiarização da oscilação BMO.

        Returns:
            Imagem 2D filtrada com preservação de bordas anatômicas.
        """
        img = np.asarray(image, dtype=np.float64)
        mo_map = self.compute_bmo_2d(img, window_size)

        mean_mo = np.mean(mo_map)
        std_mo = np.std(mo_map)

        if std_mo < 1e-8:
            return img.copy()

        # Normalização BMO do patch 2D
        edge_mask = 1.0 / (1.0 + np.exp(-(mo_map - mean_mo) / (lambda_param * std_mo + 1e-8)))

        # Filtro de suavização uniforme 2D
        w_kernel = np.ones((window_size, window_size), dtype=np.float64) / (window_size * window_size)
        
        # Convolução manual 2D simples sem dependência externa adicional
        from scipy.signal import convolve2d
        smooth_img = convolve2d(img, w_kernel, mode="same", boundary="symm")

        filtered_img = edge_mask * img + (1.0 - edge_mask) * smooth_img
        return filtered_img
