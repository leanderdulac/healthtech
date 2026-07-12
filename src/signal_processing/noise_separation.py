"""
noise_separation.py — Separação e Remoção de Ruído em Sinais Biomédicos
========================================================================

Este módulo implementa técnicas avançadas de denoising para sinais fisiológicos,
combinando análise wavelet (domínio tempo-frequência) com filtragem clássica
(domínio da frequência) para separar componentes de sinal e ruído.

Técnicas Implementadas:

    1. **Denoising por Wavelets (DWT)**:
       Utiliza a Transformada Discreta de Wavelets para decompor o sinal em
       coeficientes de aproximação (baixa frequência) e detalhes (alta frequência).
       Os coeficientes de detalhe são processados via thresholding para remover
       componentes de ruído.

       Limiar Universal (VisuShrink):
           λ = σ̂ · √(2·ln(N))

       onde σ̂ é estimado pela MAD (Median Absolute Deviation) dos coeficientes
       de detalhe do nível mais fino:
           σ̂ = MAD(d₁) / 0.6745

       Modos de thresholding:
           - Soft: sign(d)·max(|d|-λ, 0) — preserva continuidade
           - Hard: d·𝟙(|d|>λ) — preserva amplitude dos coeficientes retidos

    2. **Filtro Butterworth**:
       Filtro IIR com resposta em frequência maximamente plana na banda passante.
       A função de transferência de ordem N é:
           |H(jω)|² = 1 / (1 + (ω/ωc)^{2N})

       Implementação via Second-Order Sections (SOS) para estabilidade numérica.

    3. **Decomposição de Componentes**:
       Pipeline completo que separa um sinal em:
           - Tendência (trend): Componente de baixa frequência (< 0.01·fs)
           - Fisiológico: Componente na faixa de interesse biológico
           - Ruído: Componente residual de alta frequência
           - SNR: Razão sinal-ruído em dB

Referências:
    - Donoho, D.L. & Johnstone, I.M. (1994). Ideal spatial adaptation by wavelet
      shrinkage. Biometrika.
    - Butterworth, S. (1930). On the theory of filter amplifiers. Wireless Engineer.
    - Mallat, S.G. (1989). A theory for multiresolution signal decomposition.
      IEEE PAMI.
"""

import logging
from typing import Optional

import numpy as np
from scipy import signal as scipy_signal

# Importação condicional de pywt
try:
    import pywt
    _HAS_PYWT = True
except ImportError:
    _HAS_PYWT = False

# Configuração do logger para o módulo
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class WaveletDenoiser:
    """
    Remoção de ruído por Transformada Discreta de Wavelets (DWT).

    Implementa o algoritmo de denoising por wavelet shrinkage com limiar
    universal (VisuShrink), que é minimax ótimo para sinais com ruído
    gaussiano aditivo branco.

    Formulação Matemática:
        1. Decomposição DWT do sinal x(t) em L níveis:
           x → [cA_L, cD_L, cD_{L-1}, ..., cD_1]

        2. Estimativa de ruído via MAD do nível mais fino:
           σ̂ = MAD(cD_1) / 0.6745

        3. Limiar universal:
           λ = σ̂ · √(2·ln(N))

        4. Thresholding dos coeficientes de detalhe:
           - Soft: ĉD = sign(cD)·max(|cD|-λ, 0)
           - Hard: ĉD = cD·𝟙(|cD|>λ)

        5. Reconstrução via IDWT:
           x̂ = IDWT([cA_L, ĉD_L, ..., ĉD_1])

    Parâmetros:
        wavelet (str): Família de wavelet a usar. Padrão: 'db4' (Daubechies-4).
            Outras opções comuns: 'sym8', 'coif3', 'bior3.5'.
        level (int): Número de níveis de decomposição. Padrão: 4.
            Deve satisfazer: level ≤ log₂(N) onde N é o comprimento do sinal.
        threshold_mode (str): Modo de thresholding. Padrão: 'soft'.
            'soft' — Soft thresholding (suavização, sem descontinuidades).
            'hard' — Hard thresholding (preserva magnitudes acima do limiar).

    Exemplo:
        >>> denoiser = WaveletDenoiser(wavelet='db4', level=4, threshold_mode='soft')
        >>> sinal_limpo = denoiser.denoise(sinal_ruidoso)
        >>> snr = denoiser.estimate_snr(sinal_ruidoso, sinal_limpo)
        >>> print(f"SNR: {snr:.1f} dB")
    """

    def __init__(
        self,
        wavelet: str = "db4",
        level: int = 4,
        threshold_mode: str = "soft",
    ) -> None:
        """
        Inicializa o denoiser wavelet.

        Parâmetros:
            wavelet: Nome da wavelet mãe (e.g., 'db4', 'sym8', 'coif3').
            level: Número de níveis de decomposição DWT.
            threshold_mode: Modo de thresholding ('soft' ou 'hard').

        Levanta:
            ImportError: Se pywt não estiver instalado.
            ValueError: Se threshold_mode não for 'soft' ou 'hard'.
        """
        if not _HAS_PYWT:
            raise ImportError(
                "PyWavelets (pywt) é necessário para WaveletDenoiser. "
                "Instale com: pip install PyWavelets"
            )

        if threshold_mode not in ("soft", "hard"):
            raise ValueError(
                f"threshold_mode deve ser 'soft' ou 'hard', "
                f"recebido: '{threshold_mode}'"
            )

        self.wavelet: str = wavelet
        self.level: int = level
        self.threshold_mode: str = threshold_mode

        # Validar que a wavelet existe
        try:
            pywt.Wavelet(wavelet)
        except ValueError as e:
            raise ValueError(f"Wavelet '{wavelet}' não reconhecida: {e}") from e

        logger.info(
            "WaveletDenoiser inicializado: wavelet='%s', level=%d, mode='%s'",
            wavelet, level, threshold_mode,
        )

    def denoise(self, signal_data: np.ndarray) -> np.ndarray:
        """
        Aplica denoising wavelet ao sinal.

        Algoritmo:
            1. Decomposição DWT em L níveis
            2. Estimativa de σ̂ via MAD dos coeficientes do nível mais fino
            3. Cálculo do limiar universal: λ = σ̂·√(2·ln(N))
            4. Thresholding dos coeficientes de detalhe
            5. Reconstrução IDWT

        Parâmetros:
            signal_data: Sinal de entrada como array 1D.

        Retorna:
            Sinal denoised como np.ndarray de mesmo comprimento.

        Levanta:
            ValueError: Se o sinal for muito curto para o nível de decomposição.

        Notas:
            - O nível efetivo de decomposição é ajustado automaticamente se o
              sinal for mais curto que 2^level amostras.
            - A estimativa MAD/0.6745 é robusta a outliers (ao contrário do
              desvio padrão clássico).
        """
        sig: np.ndarray = np.asarray(signal_data, dtype=np.float64)
        n: int = len(sig)

        # Ajustar nível de decomposição se necessário
        max_level: int = pywt.dwt_max_level(n, pywt.Wavelet(self.wavelet).dec_len)
        effective_level: int = min(self.level, max_level)

        if effective_level < self.level:
            logger.warning(
                "Nível de decomposição reduzido de %d para %d "
                "(sinal com %d amostras)",
                self.level, effective_level, n,
            )

        if effective_level < 1:
            logger.warning("Sinal muito curto para decomposição wavelet (n=%d)", n)
            return sig.copy()

        # 1. Decomposição DWT
        # coeffs = [cA_L, cD_L, cD_{L-1}, ..., cD_1]
        coeffs: list = pywt.wavedec(sig, self.wavelet, level=effective_level)

        # 2. Estimativa robusta de ruído via MAD do nível mais fino
        # σ̂ = MAD(cD_1) / 0.6745
        detail_finest: np.ndarray = coeffs[-1]
        mad: float = float(np.median(np.abs(detail_finest - np.median(detail_finest))))
        sigma_hat: float = mad / 0.6745

        # 3. Limiar universal (VisuShrink): λ = σ̂ · √(2·ln(N))
        threshold: float = sigma_hat * np.sqrt(2.0 * np.log(n))

        logger.debug(
            "Denoising wavelet: σ̂=%.4f, λ=%.4f, level=%d, n=%d",
            sigma_hat, threshold, effective_level, n,
        )

        # 4. Thresholding dos coeficientes de detalhe (preservar aproximação)
        denoised_coeffs: list = [coeffs[0]]  # Manter coeficientes de aproximação
        for i in range(1, len(coeffs)):
            denoised_coeffs.append(
                pywt.threshold(
                    coeffs[i],
                    value=threshold,
                    mode=self.threshold_mode,
                )
            )

        # 5. Reconstrução IDWT
        reconstructed: np.ndarray = pywt.waverec(denoised_coeffs, self.wavelet)

        # Ajustar comprimento (pode diferir em ±1 amostra)
        reconstructed = reconstructed[:n]

        return reconstructed

    @staticmethod
    def estimate_snr(
        original: np.ndarray,
        denoised: np.ndarray,
    ) -> float:
        """
        Estima a razão sinal-ruído (SNR) em decibéis.

        Formulação:
            SNR(dB) = 10 · log₁₀(P_sinal / P_ruído)

        onde:
            P_sinal = (1/N) · Σ(x_denoised[i]²)  (potência do sinal limpo)
            P_ruído = (1/N) · Σ(x_noise[i]²)      (potência do ruído estimado)
            x_noise = x_original - x_denoised

        Parâmetros:
            original: Sinal original (ruidoso).
            denoised: Sinal após denoising.

        Retorna:
            SNR em decibéis (dB). Valores típicos:
                > 20 dB: Excelente qualidade
                10-20 dB: Qualidade aceitável
                < 10 dB: Qualidade pobre

        Levanta:
            ValueError: Se os sinais tiverem comprimentos diferentes.
        """
        orig: np.ndarray = np.asarray(original, dtype=np.float64)
        clean: np.ndarray = np.asarray(denoised, dtype=np.float64)

        if len(orig) != len(clean):
            raise ValueError(
                f"Comprimentos incompatíveis: original={len(orig)}, "
                f"denoised={len(clean)}"
            )

        # Potência do sinal limpo (estimativa do sinal verdadeiro)
        p_signal: float = float(np.mean(clean ** 2))

        # Potência do ruído (diferença entre original e denoised)
        noise: np.ndarray = orig - clean
        p_noise: float = float(np.mean(noise ** 2))

        # Evitar divisão por zero
        if p_noise < 1e-15:
            logger.warning("Potência de ruído ~0: sinal pode não conter ruído.")
            return float("inf")

        snr_db: float = 10.0 * np.log10(p_signal / p_noise)

        logger.debug(
            "SNR estimado: %.2f dB (P_sinal=%.4f, P_ruído=%.6f)",
            snr_db, p_signal, p_noise,
        )

        return snr_db


class ButterworthFilter:
    """
    Filtro Butterworth para processamento de sinais biomédicos.

    O filtro Butterworth possui resposta em frequência maximamente plana
    na banda passante, o que o torna ideal para sinais fisiológicos onde
    distorção de amplitude é indesejável.

    Função de Transferência:
        |H(jω)|² = 1 / (1 + (ω/ωc)^{2N})

    onde ωc é a frequência de corte e N é a ordem do filtro.

    Implementação:
        Utiliza representação em Second-Order Sections (SOS) via
        scipy.signal.sosfiltfilt (filtro zero-phase, sem distorção de fase)
        para estabilidade numérica superior em relação à forma transfer
        function (b, a).

    Parâmetros:
        fs (float): Frequência de amostragem em Hz. Padrão: 1.0.
        order (int): Ordem do filtro. Padrão: 4.
            Ordens maiores → transição mais abrupta entre banda passante e
            banda de rejeição, mas maior risco de instabilidade numérica.

    Exemplo:
        >>> filt = ButterworthFilter(fs=250.0, order=4)
        >>> ecg_filtrado = filt.bandpass(ecg_raw, lowcut=0.5, highcut=40.0)
    """

    def __init__(
        self,
        fs: float = 1.0,
        order: int = 4,
    ) -> None:
        """
        Inicializa o filtro Butterworth.

        Parâmetros:
            fs: Frequência de amostragem do sinal em Hz.
            order: Ordem do filtro (número de polos).

        Levanta:
            ValueError: Se fs ou order forem não-positivos.
        """
        if fs <= 0:
            raise ValueError(f"fs deve ser positivo, recebido: {fs}")
        if order < 1:
            raise ValueError(f"order deve ser ≥ 1, recebido: {order}")

        self.fs: float = fs
        self.order: int = order
        self._nyquist: float = fs / 2.0

        logger.info(
            "ButterworthFilter inicializado: fs=%.1f Hz, ordem=%d, Nyquist=%.1f Hz",
            fs, order, self._nyquist,
        )

    def bandpass(
        self,
        signal_data: np.ndarray,
        lowcut: float,
        highcut: float,
    ) -> np.ndarray:
        """
        Aplica filtro passa-banda Butterworth ao sinal.

        Parâmetros:
            signal_data: Sinal de entrada como array 1D.
            lowcut: Frequência de corte inferior em Hz.
            highcut: Frequência de corte superior em Hz.

        Retorna:
            Sinal filtrado (mesmo comprimento).

        Levanta:
            ValueError: Se lowcut ≥ highcut ou frequências fora do intervalo
                de Nyquist.

        Notas:
            Utiliza sosfiltfilt para filtro zero-phase (sem distorção de fase).
            A ordem efetiva é 2×order devido à aplicação forward-backward.
        """
        if lowcut >= highcut:
            raise ValueError(
                f"lowcut ({lowcut} Hz) deve ser < highcut ({highcut} Hz)"
            )
        if lowcut <= 0:
            raise ValueError(f"lowcut deve ser > 0, recebido: {lowcut}")
        if highcut >= self._nyquist:
            raise ValueError(
                f"highcut ({highcut} Hz) deve ser < Nyquist ({self._nyquist} Hz)"
            )

        # Frequências normalizadas (fração de Nyquist)
        low: float = lowcut / self._nyquist
        high: float = highcut / self._nyquist

        # Design do filtro em SOS
        sos: np.ndarray = scipy_signal.butter(
            self.order, [low, high], btype="band", output="sos"
        )

        # Aplicar filtro zero-phase
        filtered: np.ndarray = scipy_signal.sosfiltfilt(sos, signal_data)

        logger.debug(
            "Bandpass aplicado: [%.2f, %.2f] Hz, ordem=%d, n=%d",
            lowcut, highcut, self.order, len(signal_data),
        )

        return filtered

    def lowpass(
        self,
        signal_data: np.ndarray,
        cutoff: float,
    ) -> np.ndarray:
        """
        Aplica filtro passa-baixa Butterworth ao sinal.

        Parâmetros:
            signal_data: Sinal de entrada como array 1D.
            cutoff: Frequência de corte em Hz.

        Retorna:
            Sinal filtrado (mesmo comprimento).

        Levanta:
            ValueError: Se cutoff ≤ 0 ou ≥ Nyquist.

        Notas:
            Ideal para remoção de ruído de alta frequência em sinais
            fisiológicos (e.g., remoção de interferência EMG em ECG).
        """
        if cutoff <= 0:
            raise ValueError(f"cutoff deve ser > 0, recebido: {cutoff}")
        if cutoff >= self._nyquist:
            raise ValueError(
                f"cutoff ({cutoff} Hz) deve ser < Nyquist ({self._nyquist} Hz)"
            )

        # Frequência normalizada
        norm_cutoff: float = cutoff / self._nyquist

        # Design do filtro em SOS
        sos: np.ndarray = scipy_signal.butter(
            self.order, norm_cutoff, btype="low", output="sos"
        )

        # Aplicar filtro zero-phase
        filtered: np.ndarray = scipy_signal.sosfiltfilt(sos, signal_data)

        logger.debug(
            "Lowpass aplicado: cutoff=%.2f Hz, ordem=%d, n=%d",
            cutoff, self.order, len(signal_data),
        )

        return filtered


def decompose_signal_components(
    signal_data: np.ndarray,
    fs: float,
    trend_cutoff_ratio: float = 0.01,
    physiological_band: Optional[tuple[float, float]] = None,
) -> dict[str, object]:
    """
    Pipeline completo de decomposição de sinal em componentes.

    Separa um sinal biomédico em três componentes fundamentais:
        1. Tendência (trend): Variações lentas de baseline (drift)
        2. Fisiológico: Componente de interesse biológico
        3. Ruído: Componente residual de alta frequência

    Algoritmo:
        1. Estima tendência via filtro Butterworth passa-baixa (fc = trend_ratio × fs)
        2. Remove tendência: sinal_sem_trend = sinal - tendência
        3. Extrai componente fisiológico via bandpass ou denoising wavelet
        4. Estima ruído: ruído = sinal_sem_trend - fisiológico
        5. Calcula SNR

    Parâmetros:
        signal_data: Sinal de entrada como array 1D.
        fs: Frequência de amostragem em Hz.
        trend_cutoff_ratio: Razão da frequência de corte para tendência
            em relação à frequência de Nyquist. Padrão: 0.01.
        physiological_band: Tupla (low, high) em Hz para faixa fisiológica.
            Se None, usa denoising wavelet em vez de bandpass.

    Retorna:
        Dicionário com:
            'trend': np.ndarray — Componente de tendência (baseline drift)
            'physiological': np.ndarray — Componente fisiológico de interesse
            'noise': np.ndarray — Componente de ruído residual
            'snr_db': float — Razão sinal-ruído em decibéis

    Exemplo:
        >>> result = decompose_signal_components(ecg_raw, fs=250.0,
        ...     physiological_band=(0.5, 40.0))
        >>> print(f"SNR: {result['snr_db']:.1f} dB")
    """
    sig: np.ndarray = np.asarray(signal_data, dtype=np.float64)
    n: int = len(sig)
    nyquist: float = fs / 2.0

    logger.info(
        "Decomposição de sinal: n=%d, fs=%.1f Hz, Nyquist=%.1f Hz",
        n, fs, nyquist,
    )

    # --- 1. Extração de Tendência ---
    # Frequência de corte para trend: muito baixa (drift do baseline)
    trend_cutoff: float = trend_cutoff_ratio * nyquist

    # Garantir que o cutoff é válido (>0 e < nyquist)
    if trend_cutoff <= 0 or trend_cutoff >= nyquist:
        logger.warning(
            "trend_cutoff=%.4f Hz inválido. Usando tendência como média.",
            trend_cutoff,
        )
        trend: np.ndarray = np.full(n, sig.mean())
    else:
        trend_filter = ButterworthFilter(fs=fs, order=2)
        trend = trend_filter.lowpass(sig, cutoff=trend_cutoff)

    # Sinal detrended
    detrended: np.ndarray = sig - trend

    # --- 2. Extração do Componente Fisiológico ---
    if physiological_band is not None:
        low_hz, high_hz = physiological_band

        # Validação das frequências
        if low_hz <= 0 or high_hz >= nyquist or low_hz >= high_hz:
            logger.warning(
                "Banda fisiológica [%.2f, %.2f] Hz inválida para Nyquist=%.1f Hz. "
                "Usando denoising wavelet como fallback.",
                low_hz, high_hz, nyquist,
            )
            # Fallback para wavelet
            if _HAS_PYWT:
                denoiser = WaveletDenoiser(wavelet="db4", level=4, threshold_mode="soft")
                physiological = denoiser.denoise(detrended)
            else:
                physiological = detrended.copy()
        else:
            bp_filter = ButterworthFilter(fs=fs, order=4)
            physiological = bp_filter.bandpass(detrended, lowcut=low_hz, highcut=high_hz)
    else:
        # Sem banda especificada: usar denoising wavelet
        if _HAS_PYWT:
            denoiser = WaveletDenoiser(wavelet="db4", level=4, threshold_mode="soft")
            physiological = denoiser.denoise(detrended)
        else:
            logger.warning(
                "pywt não disponível e banda fisiológica não especificada. "
                "Componente fisiológico = sinal detrended."
            )
            physiological = detrended.copy()

    # --- 3. Estimativa de Ruído ---
    noise: np.ndarray = detrended - physiological

    # --- 4. Cálculo de SNR ---
    p_signal: float = float(np.mean(physiological ** 2))
    p_noise: float = float(np.mean(noise ** 2))

    if p_noise < 1e-15:
        snr_db: float = float("inf")
    else:
        snr_db = 10.0 * np.log10(p_signal / p_noise)

    logger.info(
        "Decomposição concluída: SNR=%.2f dB, "
        "P_trend=%.4f, P_physio=%.4f, P_noise=%.6f",
        snr_db, float(np.mean(trend ** 2)), p_signal, p_noise,
    )

    return {
        "trend": trend,
        "physiological": physiological,
        "noise": noise,
        "snr_db": snr_db,
    }


if __name__ == "__main__":
    # Configuração de logging para demonstração
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    print("=" * 70)
    print("DEMONSTRAÇÃO: Separação de Ruído em Sinais Biomédicos")
    print("=" * 70)

    # Geração de sinal sintético para demonstração
    np.random.seed(42)
    fs: float = 250.0   # Frequência de amostragem (Hz)
    duration: float = 10.0  # Duração (segundos)
    n_samples: int = int(fs * duration)
    t: np.ndarray = np.linspace(0, duration, n_samples, endpoint=False)

    # Componentes do sinal sintético:
    # 1. Tendência lenta (drift de baseline)
    trend_true: np.ndarray = 0.5 * np.sin(2 * np.pi * 0.05 * t)
    # 2. Sinal fisiológico (simula ECG simplificado: 1.2 Hz = 72 BPM)
    physio_true: np.ndarray = (
        1.0 * np.sin(2 * np.pi * 1.2 * t)
        + 0.3 * np.sin(2 * np.pi * 2.4 * t)  # Harmônico
    )
    # 3. Ruído gaussiano
    noise_true: np.ndarray = 0.2 * np.random.randn(n_samples)

    # Sinal observado (soma das componentes)
    signal_observed: np.ndarray = trend_true + physio_true + noise_true

    # --- 1. Denoising Wavelet ---
    print("\n--- 1. Denoising por Wavelets (DWT) ---")
    if _HAS_PYWT:
        denoiser = WaveletDenoiser(wavelet="db4", level=4, threshold_mode="soft")
        signal_denoised: np.ndarray = denoiser.denoise(signal_observed)
        snr: float = denoiser.estimate_snr(signal_observed, signal_denoised)

        print(f"   Wavelet: db4, Nível: 4, Modo: soft")
        print(f"   Amostras: {n_samples}")
        print(f"   SNR estimado: {snr:.2f} dB")
        print(f"   Amplitude original std: {signal_observed.std():.4f}")
        print(f"   Amplitude denoised std: {signal_denoised.std():.4f}")
        print(f"   Redução de ruído: {(1 - signal_denoised.std()/signal_observed.std())*100:.1f}%")
    else:
        print("   ⚠ pywt não instalado. Pulando demonstração wavelet.")
        print("   Instale com: pip install PyWavelets")

    # --- 2. Filtro Butterworth ---
    print("\n--- 2. Filtro Butterworth ---")
    filt = ButterworthFilter(fs=fs, order=4)

    # Bandpass: extrair faixa de 0.5-10 Hz (HR e respiração)
    signal_bp: np.ndarray = filt.bandpass(signal_observed, lowcut=0.5, highcut=10.0)
    print(f"   Bandpass [0.5, 10.0] Hz aplicado")
    print(f"   Amplitude bandpass std: {signal_bp.std():.4f}")

    # Lowpass: remover alta frequência
    signal_lp: np.ndarray = filt.lowpass(signal_observed, cutoff=5.0)
    print(f"   Lowpass 5.0 Hz aplicado")
    print(f"   Amplitude lowpass std: {signal_lp.std():.4f}")

    # --- 3. Decomposição Completa ---
    print("\n--- 3. Decomposição de Componentes ---")
    result = decompose_signal_components(
        signal_observed,
        fs=fs,
        physiological_band=(0.5, 10.0),
    )

    print(f"   SNR: {result['snr_db']:.2f} dB")
    print(f"   Potência da tendência: {np.mean(result['trend']**2):.4f}")
    print(f"   Potência fisiológica: {np.mean(result['physiological']**2):.4f}")
    print(f"   Potência do ruído:    {np.mean(result['noise']**2):.6f}")

    # Verificação de conservação de energia
    total_power_in: float = np.mean(signal_observed ** 2)
    total_power_out: float = (
        np.mean(result["trend"] ** 2)
        + np.mean(result["physiological"] ** 2)
        + np.mean(result["noise"] ** 2)
    )
    # Nota: potência não é exatamente conservada devido a termos cruzados,
    # mas serve como verificação de sanidade
    print(f"\n   Potência total entrada: {total_power_in:.4f}")
    print(f"   Soma potências saída:   {total_power_out:.4f}")

    # --- 4. Benchmark com ruído conhecido ---
    print("\n--- 4. Benchmark: Recuperação com Ruído Conhecido ---")
    snr_true_db: float = 10.0 * np.log10(
        np.mean(physio_true ** 2) / np.mean(noise_true ** 2)
    )
    print(f"   SNR verdadeiro (sinal vs ruído puro): {snr_true_db:.2f} dB")

    if _HAS_PYWT:
        denoised_physio = WaveletDenoiser().denoise(physio_true + noise_true)
        reconstruction_error = np.sqrt(np.mean((denoised_physio - physio_true) ** 2))
        print(f"   Erro de reconstrução (RMSE): {reconstruction_error:.4f}")
        print(f"   RMSE relativo: {reconstruction_error / np.std(physio_true) * 100:.1f}%")

    print("\n" + "=" * 70)
    print("Demonstração concluída com sucesso.")
    print("=" * 70)
