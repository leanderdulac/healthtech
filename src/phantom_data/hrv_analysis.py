"""
hrv_analysis.py — Análise de Variabilidade da Frequência Cardíaca (VFC/HRV)

Este módulo implementa análise completa de HRV nos domínios temporal,
frequencial e não-linear, seguindo as diretrizes da Task Force of the
European Society of Cardiology (1996) e atualizações recentes.

Métricas implementadas:
    Domínio temporal: SDNN, RMSSD, pNN50, FC média
    Domínio frequencial: VLF, LF, HF, LF/HF, potência total (Welch e Lomb-Scargle)
    Não-linear: Entropia Aproximada (ApEn), Entropia Amostral (SampEn)

Dependências:
    numpy, scipy (signal, interpolate)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import numpy as np
from scipy import interpolate, signal

logger = logging.getLogger(__name__)


class HRVAnalyzer:
    """
    Analisador completo de Variabilidade da Frequência Cardíaca (HRV).

    Realiza análise nos três domínios fundamentais:
        1. Temporal — estatísticas dos intervalos R-R
        2. Frequencial — decomposição espectral via Welch ou Lomb-Scargle
        3. Não-linear — entropia aproximada e amostral

    Attributes:
        fs: Frequência de amostragem fixa para reamostragem (Hz).
             Se None, utiliza o padrão de cada método.
    """

    # Bandas de frequência padrão (Hz) — Task Force ESC 1996
    VLF_BAND: Tuple[float, float] = (0.003, 0.04)
    LF_BAND: Tuple[float, float] = (0.04, 0.15)
    HF_BAND: Tuple[float, float] = (0.15, 0.4)

    def __init__(self, fs: Optional[float] = None) -> None:
        """
        Inicializa o analisador de HRV.

        Args:
            fs: Frequência de amostragem fixa para reamostragem dos intervalos
                R-R (Hz). Se None, utiliza fs=4.0 Hz como padrão no método Welch.
                Valores típicos: 2.0 a 10.0 Hz.
        """
        self.fs: Optional[float] = fs
        logger.info(
            "HRVAnalyzer inicializado (fs=%s)",
            f"{fs:.1f} Hz" if fs else "auto",
        )

    # ========================================================================
    # Validações
    # ========================================================================

    @staticmethod
    def _validate_rr(rr_intervals: np.ndarray, min_length: int = 2) -> np.ndarray:
        """
        Valida e converte os intervalos R-R para ndarray.

        Args:
            rr_intervals: Sequência de intervalos R-R (ms).
            min_length: Número mínimo de intervalos necessários.

        Returns:
            Array validado de intervalos R-R.

        Raises:
            ValueError: Se dados insuficientes ou inválidos.
        """
        rr = np.asarray(rr_intervals, dtype=float)
        rr = rr[np.isfinite(rr)]  # Remover NaN e inf

        if rr.size < min_length:
            raise ValueError(
                f"Dados insuficientes: {rr.size} intervalos R-R "
                f"(mínimo necessário: {min_length})"
            )

        if np.any(rr <= 0):
            logger.warning(
                "Intervalos R-R negativos ou zero encontrados; removendo %d valores.",
                np.sum(rr <= 0),
            )
            rr = rr[rr > 0]
            if rr.size < min_length:
                raise ValueError(
                    "Dados insuficientes após remoção de valores inválidos."
                )

        return rr

    # ========================================================================
    # Domínio Temporal
    # ========================================================================

    def compute_sdnn(self, rr_intervals: np.ndarray) -> float:
        """
        Calcula o SDNN — Desvio Padrão dos Intervalos N-N.

        Fórmula:
            SDNN = √( 1/(N-1) · Σᵢ (RRᵢ - R̄R)² )

        Onde:
            N = número de intervalos R-R
            R̄R = média dos intervalos R-R
            RRᵢ = i-ésimo intervalo R-R

        O SDNN reflete a variabilidade global e é influenciado tanto pelo
        sistema nervoso simpático quanto pelo parassimpático.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.

        Returns:
            SDNN em milissegundos.
        """
        rr = self._validate_rr(rr_intervals, min_length=2)
        sdnn = float(np.std(rr, ddof=1))
        logger.debug("SDNN calculado: %.2f ms (N=%d)", sdnn, rr.size)
        return sdnn

    def compute_rmssd(self, rr_intervals: np.ndarray) -> float:
        """
        Calcula o RMSSD — Raiz Quadrada da Média das Diferenças Sucessivas ao Quadrado.

        Fórmula:
            RMSSD = √( 1/(N-1) · Σᵢ₌₁ᴺ⁻¹ (RRᵢ₊₁ - RRᵢ)² )

        Onde:
            N = número de intervalos R-R
            (RRᵢ₊₁ - RRᵢ) = diferença sucessiva entre intervalos adjacentes

        O RMSSD é uma medida de atividade vagal (parassimpática) e reflete
        variações de curto prazo nos intervalos R-R. É o índice temporal
        mais utilizado para avaliação do tono parassimpático.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.

        Returns:
            RMSSD em milissegundos.
        """
        rr = self._validate_rr(rr_intervals, min_length=2)
        successive_diffs = np.diff(rr)
        rmssd = float(np.sqrt(np.mean(successive_diffs ** 2)))
        logger.debug("RMSSD calculado: %.2f ms (N=%d)", rmssd, rr.size)
        return rmssd

    def compute_pnn50(self, rr_intervals: np.ndarray) -> float:
        """
        Calcula o pNN50 — Percentual de Diferenças Sucessivas > 50 ms.

        Fórmula:
            pNN50 = ( count(|ΔRRᵢ| > 50) / (N-1) ) × 100

        Onde:
            ΔRRᵢ = RRᵢ₊₁ - RRᵢ (diferença sucessiva)
            N = número de intervalos R-R
            O limiar de 50 ms é um padrão clínico da Task Force ESC

        O pNN50 é altamente correlacionado com a atividade parassimpática e
        com o componente HF da análise espectral. Valores altos indicam
        predominância vagal.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.

        Returns:
            pNN50 em percentual (0-100).
        """
        rr = self._validate_rr(rr_intervals, min_length=2)
        successive_diffs = np.abs(np.diff(rr))
        n_diffs = len(successive_diffs)

        if n_diffs == 0:
            return 0.0

        nn50_count = np.sum(successive_diffs > 50.0)
        pnn50 = float(nn50_count / n_diffs) * 100.0
        logger.debug(
            "pNN50 calculado: %.2f%% (NN50=%d, N-1=%d)",
            pnn50, nn50_count, n_diffs,
        )
        return pnn50

    def compute_time_domain(self, rr_intervals: np.ndarray) -> Dict[str, float]:
        """
        Calcula todas as métricas do domínio temporal.

        Inclui:
            - SDNN: desvio padrão dos intervalos N-N
            - RMSSD: raiz quadrada da média das diferenças sucessivas²
            - pNN50: percentual de diferenças sucessivas > 50ms
            - mean_rr: média dos intervalos R-R (ms)
            - mean_hr: frequência cardíaca média = 60000 / mean_rr (bpm)
            - min_rr, max_rr: extremos dos intervalos (ms)
            - range_rr: amplitude = max_rr - min_rr (ms)

        Args:
            rr_intervals: Intervalos R-R em milissegundos.

        Returns:
            Dicionário com todas as métricas temporais.
        """
        rr = self._validate_rr(rr_intervals, min_length=2)

        mean_rr = float(np.mean(rr))
        mean_hr = 60000.0 / mean_rr if mean_rr > 0 else 0.0

        result = {
            "sdnn": self.compute_sdnn(rr),
            "rmssd": self.compute_rmssd(rr),
            "pnn50": self.compute_pnn50(rr),
            "mean_rr": mean_rr,
            "mean_hr": mean_hr,
            "min_rr": float(np.min(rr)),
            "max_rr": float(np.max(rr)),
            "range_rr": float(np.max(rr) - np.min(rr)),
        }

        logger.info(
            "Análise temporal concluída: SDNN=%.1f, RMSSD=%.1f, pNN50=%.1f%%",
            result["sdnn"], result["rmssd"], result["pnn50"],
        )
        return result

    # ========================================================================
    # Domínio Frequencial
    # ========================================================================

    def compute_psd_welch(
        self,
        rr_intervals: np.ndarray,
        fs: float = 4.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calcula a Densidade Espectral de Potência (PSD) via método de Welch.

        Procedimento:
            1. Calcula os timestamps cumulativos dos intervalos R-R
            2. Remove a média (detrending)
            3. Interpola para amostragem uniforme a fs Hz usando spline cúbica
            4. Aplica o método de Welch com janela de Hann

        O método de Welch divide o sinal em segmentos sobrepostos,
        aplica uma janela e promedia os periodogramas, reduzindo a
        variância da estimativa espectral.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.
            fs: Frequência de amostragem para interpolação (Hz). Padrão: 4.0 Hz.
                Deve ser ≥ 2× a frequência máxima de interesse (0.4 Hz),
                portanto fs ≥ 0.8 Hz (Nyquist). Recomendado: 4.0 Hz.

        Returns:
            Tupla (frequencies, psd):
                frequencies: Array de frequências (Hz).
                psd: Array de potência espectral (ms²/Hz).

        Raises:
            ValueError: Se dados insuficientes para análise espectral.
        """
        rr = self._validate_rr(rr_intervals, min_length=8)
        effective_fs = self.fs if self.fs is not None else fs

        # Calcular timestamps cumulativos (em segundos)
        timestamps = np.cumsum(rr) / 1000.0
        timestamps -= timestamps[0]  # Iniciar em zero

        # Remover a média (detrending linear)
        rr_detrended = rr - np.mean(rr)

        # Interpolação cúbica para amostragem uniforme
        total_duration = timestamps[-1]
        n_samples = int(total_duration * effective_fs)

        if n_samples < 8:
            raise ValueError(
                f"Duração insuficiente ({total_duration:.1f}s) para análise "
                f"espectral com fs={effective_fs:.1f} Hz"
            )

        t_uniform = np.linspace(0, total_duration, n_samples, endpoint=False)
        interp_func = interpolate.CubicSpline(timestamps, rr_detrended)
        rr_uniform = interp_func(t_uniform)

        # Calcular PSD via Welch
        nperseg = min(256, n_samples)
        # Garantir nperseg seja par
        nperseg = max(nperseg, 16)

        freqs, psd = signal.welch(
            rr_uniform,
            fs=effective_fs,
            window="hann",
            nperseg=nperseg,
            noverlap=nperseg // 2,
            detrend="constant",
        )

        logger.debug(
            "PSD Welch calculada: %d pontos, fmax=%.3f Hz, nperseg=%d",
            len(freqs), freqs[-1] if len(freqs) > 0 else 0, nperseg,
        )
        return freqs, psd

    def compute_psd_lomb_scargle(
        self,
        rr_intervals: np.ndarray,
        timestamps: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calcula a PSD via periodograma de Lomb-Scargle para dados irregulares.

        O método de Lomb-Scargle é ideal para séries temporais amostradas
        de forma não uniforme, evitando artefatos de interpolação.

        O periodograma é calculado como:
            P(ω) = 1/(2σ²) · { [Σ(xⱼ-x̄)cos(ω(tⱼ-τ))]² / Σcos²(ω(tⱼ-τ))
                               + [Σ(xⱼ-x̄)sin(ω(tⱼ-τ))]² / Σsin²(ω(tⱼ-τ)) }

        Onde τ é definido de forma que o estimador seja invariante a
        deslocamentos temporais.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.
            timestamps: Timestamps correspondentes a cada intervalo (segundos).

        Returns:
            Tupla (frequencies, psd):
                frequencies: Array de frequências (Hz).
                psd: Array de potência espectral (ms²/Hz).

        Raises:
            ValueError: Se rr_intervals e timestamps tiverem comprimentos diferentes.
        """
        rr = self._validate_rr(rr_intervals, min_length=8)
        ts = np.asarray(timestamps, dtype=float)

        if len(rr) != len(ts):
            raise ValueError(
                f"Comprimentos diferentes: rr_intervals ({len(rr)}) != "
                f"timestamps ({len(ts)})"
            )

        # Remover média
        rr_centered = rr - np.mean(rr)

        # Definir frequências de análise (0.003 a 0.4 Hz)
        n_freqs = 1000
        freqs = np.linspace(0.003, 0.4, n_freqs)
        angular_freqs = 2.0 * np.pi * freqs

        # Calcular periodograma de Lomb-Scargle
        # scipy.signal.lombscargle espera frequências angulares
        psd = signal.lombscargle(ts, rr_centered, angular_freqs, normalize=False)

        # Normalizar para ms²/Hz
        # A normalização padrão do scipy retorna potência em unidades de
        # amplitude²; dividir por N para normalizar
        psd = psd * 2.0 / len(rr)

        logger.debug(
            "PSD Lomb-Scargle calculada: %d pontos de frequência, "
            "faixa=[%.3f, %.3f] Hz",
            n_freqs, freqs[0], freqs[-1],
        )
        return freqs, psd

    def _band_power(
        self,
        freqs: np.ndarray,
        psd: np.ndarray,
        low: float,
        high: float,
    ) -> float:
        """
        Calcula a potência espectral em uma banda de frequência específica.

        Utiliza integração trapezoidal (regra do trapézio) da PSD na faixa
        [low, high] Hz:
            P_band = ∫[low→high] PSD(f) df ≈ Σ trapézios

        Args:
            freqs: Array de frequências (Hz).
            psd: Array de potência espectral (ms²/Hz).
            low: Frequência inferior da banda (Hz).
            high: Frequência superior da banda (Hz).

        Returns:
            Potência na banda (ms²).
        """
        mask = (freqs >= low) & (freqs <= high)
        if not np.any(mask):
            logger.warning(
                "Nenhum ponto de frequência na banda [%.3f, %.3f] Hz",
                low, high,
            )
            return 0.0

        power = float(np.trapz(psd[mask], freqs[mask]))
        return max(power, 0.0)  # Garantir não-negatividade

    def compute_frequency_domain(
        self,
        rr_intervals: np.ndarray,
        timestamps: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """
        Calcula todas as métricas do domínio frequencial.

        Bandas de frequência (Task Force ESC, 1996):
            VLF: 0.003 — 0.04 Hz (termorregulação, SRAA, atividade vasomotora)
            LF:  0.04  — 0.15 Hz (modulação simpática e parassimpática)
            HF:  0.15  — 0.40 Hz (modulação parassimpática/vagal, respiração)

        Métricas calculadas:
            vlf_power: Potência na banda VLF (ms²)
            lf_power:  Potência na banda LF (ms²)
            hf_power:  Potência na banda HF (ms²)
            total_power: VLF + LF + HF (ms²)
            lf_hf_ratio: LF/HF — balanço simpato-vagal
            lf_norm: LF normalizada = 100 × LF / (LF + HF) (%)
            hf_norm: HF normalizada = 100 × HF / (LF + HF) (%)

        O método espectral é escolhido automaticamente:
            - Lomb-Scargle se timestamps forem fornecidos (dados irregulares)
            - Welch caso contrário (assume amostragem regular após interpolação)

        Args:
            rr_intervals: Intervalos R-R em milissegundos.
            timestamps: Timestamps opcionais para Lomb-Scargle (segundos).

        Returns:
            Dicionário com todas as métricas frequenciais.
        """
        rr = self._validate_rr(rr_intervals, min_length=8)

        # Escolher método de PSD
        if timestamps is not None:
            freqs, psd = self.compute_psd_lomb_scargle(rr, timestamps)
            method = "lomb_scargle"
        else:
            freqs, psd = self.compute_psd_welch(rr)
            method = "welch"

        # Calcular potências nas bandas
        vlf = self._band_power(freqs, psd, *self.VLF_BAND)
        lf = self._band_power(freqs, psd, *self.LF_BAND)
        hf = self._band_power(freqs, psd, *self.HF_BAND)
        total = vlf + lf + hf

        # LF/HF ratio (balanço simpato-vagal)
        if hf > 1e-10:
            lf_hf_ratio = lf / hf
        else:
            lf_hf_ratio = float("inf")
            logger.warning(
                "Potência HF próxima de zero (%.2e); LF/HF ratio indefinido.", hf,
            )

        # Unidades normalizadas (excluindo VLF)
        lf_hf_sum = lf + hf
        if lf_hf_sum > 1e-10:
            lf_norm = 100.0 * lf / lf_hf_sum
            hf_norm = 100.0 * hf / lf_hf_sum
        else:
            lf_norm = 0.0
            hf_norm = 0.0

        result = {
            "vlf_power": vlf,
            "lf_power": lf,
            "hf_power": hf,
            "total_power": total,
            "lf_hf_ratio": lf_hf_ratio,
            "lf_norm": lf_norm,
            "hf_norm": hf_norm,
            "method": method,
        }

        logger.info(
            "Análise frequencial (%s): VLF=%.1f, LF=%.1f, HF=%.1f, "
            "LF/HF=%.2f",
            method, vlf, lf, hf, lf_hf_ratio,
        )
        return result

    # ========================================================================
    # Métodos Não-Lineares
    # ========================================================================

    def compute_approximate_entropy(
        self,
        rr_intervals: np.ndarray,
        m: int = 2,
        r_factor: float = 0.2,
    ) -> float:
        """
        Calcula a Entropia Aproximada (ApEn).

        A ApEn quantifica a regularidade/previsibilidade de uma série temporal.
        Valores baixos indicam maior regularidade; valores altos indicam
        maior complexidade/imprevisibilidade.

        Algoritmo (Pincus, 1991):
            1. Definir tolerância: r = r_factor × σ(RR)
            2. Para dimensão de embedding d ∈ {m, m+1}:
                a. Construir vetores template de comprimento d:
                   uᵢ = [RRᵢ, RRᵢ₊₁, ..., RRᵢ₊ₐ₋₁]
                b. Para cada template uᵢ, contar o número de templates uⱼ
                   tal que d(uᵢ, uⱼ) = max_k(|uᵢ[k] - uⱼ[k]|) ≤ r
                   (incluindo auto-comparação j=i)
                c. Cᵢᵈ = count / N' (proporção de matches)
                d. φ(d) = (1/N') × Σ ln(Cᵢᵈ)
            3. ApEn(m, r, N) = φ(m) - φ(m+1)

        Nota: ApEn inclui auto-comparação (self-match), o que introduz
        viés para séries curtas. Para séries longas, é equivalente a SampEn.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.
            m: Dimensão de embedding (padrão: 2).
            r_factor: Fator de tolerância r = r_factor × σ(RR) (padrão: 0.2).

        Returns:
            Entropia aproximada (adimensional, tipicamente entre 0 e 2).
        """
        rr = self._validate_rr(rr_intervals, min_length=m + 2)
        N = len(rr)
        std_rr = np.std(rr, ddof=1)

        if std_rr < 1e-10:
            logger.warning(
                "Desvio padrão dos intervalos R-R é ~0; retornando ApEn=0.0"
            )
            return 0.0

        r = r_factor * std_rr

        def _phi(dim: int) -> float:
            """Calcula φ(d) para a dimensão de embedding d."""
            n_templates = N - dim + 1
            if n_templates <= 0:
                return 0.0

            # Construir templates
            templates = np.array([rr[i: i + dim] for i in range(n_templates)])

            # Contar matches (incluindo self-match)
            counts = np.zeros(n_templates)
            for i in range(n_templates):
                # Distância Chebyshev: max_k |u_i[k] - u_j[k]|
                dists = np.max(np.abs(templates - templates[i]), axis=1)
                counts[i] = np.sum(dists <= r)

            # Proporção de matches
            C = counts / n_templates

            # Evitar log(0) — não deve ocorrer com self-match
            C = np.maximum(C, 1e-100)
            return float(np.mean(np.log(C)))

        phi_m = _phi(m)
        phi_m1 = _phi(m + 1)
        apen = phi_m - phi_m1

        logger.debug(
            "ApEn calculada: %.4f (m=%d, r=%.2f, N=%d)",
            apen, m, r, N,
        )
        return float(apen)

    def compute_sample_entropy(
        self,
        rr_intervals: np.ndarray,
        m: int = 2,
        r_factor: float = 0.2,
    ) -> float:
        """
        Calcula a Entropia Amostral (SampEn).

        A SampEn é uma variante sem viés da ApEn que exclui auto-comparações,
        tornando-a mais robusta para séries curtas.

        Algoritmo (Richman & Moorman, 2000):
            1. Definir tolerância: r = r_factor × σ(RR)
            2. Para dimensão de embedding d ∈ {m, m+1}:
                a. Construir vetores template de comprimento d
                b. Contar pares (i,j) com i≠j onde d(uᵢ, uⱼ) ≤ r
            3. B = número de matches de comprimento m (excluindo self-matches)
            4. A = número de matches de comprimento m+1 (excluindo self-matches)
            5. SampEn = -ln(A / B)

        Interpretação:
            SampEn ≈ 0: série altamente previsível/regular
            SampEn > 1: série complexa/irregular
            SampEn = ∞: nenhum match encontrado (A=0)

        Args:
            rr_intervals: Intervalos R-R em milissegundos.
            m: Dimensão de embedding (padrão: 2).
            r_factor: Fator de tolerância r = r_factor × σ(RR) (padrão: 0.2).

        Returns:
            Entropia amostral (adimensional). Retorna float('inf') se A=0.
        """
        rr = self._validate_rr(rr_intervals, min_length=m + 2)
        N = len(rr)
        std_rr = np.std(rr, ddof=1)

        if std_rr < 1e-10:
            logger.warning(
                "Desvio padrão dos intervalos R-R é ~0; retornando SampEn=0.0"
            )
            return 0.0

        r = r_factor * std_rr

        def _count_matches(dim: int) -> int:
            """Conta matches (excluindo self-matches) para dimensão d."""
            n_templates = N - dim
            if n_templates <= 0:
                return 0

            templates = np.array([rr[i: i + dim] for i in range(n_templates)])

            count = 0
            for i in range(n_templates):
                # Distância Chebyshev, excluindo self-match (j ≠ i)
                for j in range(i + 1, n_templates):
                    if np.max(np.abs(templates[i] - templates[j])) <= r:
                        count += 1

            # Cada par (i,j) é contado uma vez; multiplicar por 2 para
            # obter contagem total simétrica
            return count * 2

        B = _count_matches(m)      # Matches de comprimento m
        A = _count_matches(m + 1)  # Matches de comprimento m+1

        if B == 0:
            logger.warning(
                "Nenhum match de comprimento m=%d encontrado; SampEn indefinida.",
                m,
            )
            return float("inf")

        if A == 0:
            logger.warning(
                "Nenhum match de comprimento m+1=%d encontrado; SampEn=inf.",
                m + 1,
            )
            return float("inf")

        sampen = -np.log(A / B)
        logger.debug(
            "SampEn calculada: %.4f (m=%d, r=%.2f, B=%d, A=%d)",
            sampen, m, r, B, A,
        )
        return float(sampen)

    def compute_nonlinear(
        self,
        rr_intervals: np.ndarray,
    ) -> Dict[str, float]:
        """
        Calcula todas as métricas não-lineares.

        Inclui:
            - approximate_entropy (ApEn): regularidade com self-match
            - sample_entropy (SampEn): regularidade sem self-match (mais robusta)

        Args:
            rr_intervals: Intervalos R-R em milissegundos.

        Returns:
            Dicionário com as métricas não-lineares.
        """
        rr = self._validate_rr(rr_intervals, min_length=4)

        result = {
            "approximate_entropy": self.compute_approximate_entropy(rr),
            "sample_entropy": self.compute_sample_entropy(rr),
        }

        logger.info(
            "Análise não-linear concluída: ApEn=%.4f, SampEn=%.4f",
            result["approximate_entropy"], result["sample_entropy"],
        )
        return result

    # ========================================================================
    # Análise Completa
    # ========================================================================

    def full_analysis(
        self,
        rr_intervals: np.ndarray,
        timestamps: Optional[np.ndarray] = None,
    ) -> Dict:
        """
        Realiza análise completa de HRV nos três domínios.

        Combina as análises temporal, frequencial e não-linear em um
        relatório unificado. Falhas parciais são tratadas graciosamente:
        se uma análise falhar, as demais continuam e o erro é registrado
        no log.

        Args:
            rr_intervals: Intervalos R-R em milissegundos.
            timestamps: Timestamps opcionais para Lomb-Scargle (segundos).

        Returns:
            Dicionário com:
                'time_domain': métricas temporais
                'frequency_domain': métricas frequenciais
                'nonlinear': métricas não-lineares
                'metadata': metadados da análise (N, duração, timestamp)
        """
        rr = self._validate_rr(rr_intervals, min_length=2)
        report: Dict = {}

        # Metadados
        duration_s = float(np.sum(rr)) / 1000.0
        report["metadata"] = {
            "n_intervals": len(rr),
            "duration_seconds": duration_s,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Domínio temporal
        try:
            report["time_domain"] = self.compute_time_domain(rr)
        except Exception as e:
            logger.warning("Falha na análise temporal: %s", e)
            report["time_domain"] = {"error": str(e)}

        # Domínio frequencial
        try:
            report["frequency_domain"] = self.compute_frequency_domain(
                rr, timestamps=timestamps,
            )
        except Exception as e:
            logger.warning("Falha na análise frequencial: %s", e)
            report["frequency_domain"] = {"error": str(e)}

        # Não-linear
        try:
            report["nonlinear"] = self.compute_nonlinear(rr)
        except Exception as e:
            logger.warning("Falha na análise não-linear: %s", e)
            report["nonlinear"] = {"error": str(e)}

        logger.info(
            "Análise completa de HRV concluída: N=%d, duração=%.1fs",
            len(rr), duration_s,
        )
        return report


if __name__ == "__main__":
    # ==========================================================================
    # Demonstração — Análise de Variabilidade da Frequência Cardíaca
    # ==========================================================================
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 70)
    print("  DEMONSTRAÇÃO — Análise de HRV (Heart Rate Variability)")
    print("=" * 70)

    # Simular intervalos R-R realistas
    # FC média ~ 75 bpm → RR médio ~ 800 ms
    np.random.seed(42)
    n_beats = 300
    mean_rr = 800.0   # ms
    std_rr = 50.0      # ms — variabilidade fisiológica típica

    # Adicionar componentes oscilatórios para simular LF e HF
    t_beats = np.arange(n_beats) * mean_rr / 1000.0  # tempo em segundos
    lf_component = 30.0 * np.sin(2 * np.pi * 0.1 * t_beats)   # 0.1 Hz (LF)
    hf_component = 15.0 * np.sin(2 * np.pi * 0.25 * t_beats)  # 0.25 Hz (HF)
    noise = np.random.normal(0, 10, n_beats)

    rr_intervals = mean_rr + lf_component + hf_component + noise
    rr_intervals = np.clip(rr_intervals, 400, 1500)  # Limites fisiológicos

    print(f"\n  Intervalos R-R simulados: N={n_beats}")
    print(f"  RR médio: {np.mean(rr_intervals):.1f} ms")
    print(f"  FC média: {60000 / np.mean(rr_intervals):.1f} bpm")
    print(f"  Duração total: {np.sum(rr_intervals) / 1000:.1f} s")

    # Instanciar analisador
    analyzer = HRVAnalyzer()

    # --- Domínio Temporal ---
    print("\n--- Domínio Temporal ---")
    time_metrics = analyzer.compute_time_domain(rr_intervals)
    for key, value in time_metrics.items():
        unit = "ms" if "rr" in key or key in ("sdnn", "rmssd") else (
            "bpm" if "hr" in key else "%"
        )
        print(f"  {key:>12s}: {value:>10.2f} {unit}")

    # --- Domínio Frequencial ---
    print("\n--- Domínio Frequencial (Welch) ---")
    freq_metrics = analyzer.compute_frequency_domain(rr_intervals)
    for key, value in freq_metrics.items():
        if isinstance(value, str):
            print(f"  {key:>12s}: {value}")
        elif value == float("inf"):
            print(f"  {key:>12s}:        inf")
        else:
            print(f"  {key:>12s}: {value:>10.4f}")

    # --- Domínio Frequencial (Lomb-Scargle) ---
    print("\n--- Domínio Frequencial (Lomb-Scargle) ---")
    timestamps = np.cumsum(rr_intervals) / 1000.0
    freq_metrics_ls = analyzer.compute_frequency_domain(rr_intervals, timestamps)
    for key, value in freq_metrics_ls.items():
        if isinstance(value, str):
            print(f"  {key:>12s}: {value}")
        elif value == float("inf"):
            print(f"  {key:>12s}:        inf")
        else:
            print(f"  {key:>12s}: {value:>10.4f}")

    # --- Não-linear ---
    print("\n--- Métodos Não-Lineares ---")
    nonlinear_metrics = analyzer.compute_nonlinear(rr_intervals)
    for key, value in nonlinear_metrics.items():
        print(f"  {key:>25s}: {value:.4f}")

    # --- Análise Completa ---
    print("\n--- Relatório Completo ---")
    full_report = analyzer.full_analysis(rr_intervals)
    print(f"  Metadados: {full_report['metadata']}")
    print(f"  Domínios analisados: {list(full_report.keys())}")

    print("\n✓ Demonstração de HRV concluída com sucesso.")
