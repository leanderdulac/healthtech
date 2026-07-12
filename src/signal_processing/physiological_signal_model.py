"""
physiological_signal_model.py — Geração Realista de Sinais Biomédicos
=====================================================================

Este módulo implementa modelos estocásticos para geração de sinais fisiológicos
realistas, fundamentados em processos físicos e estatísticos bem estabelecidos
na literatura biomédica.

Modelos Implementados:
    1. **Processo de Ornstein-Uhlenbeck (OU)**: Simula frequência cardíaca com
       dinâmica de reversão à média. A discretização de Euler-Maruyama é:

           x_{t+1} = x_t + θ·(μ - x_t)·Δt + σ·√(Δt)·ε,   ε ~ N(0,1)

       onde θ controla a velocidade de reversão, μ é a média de longo prazo,
       σ é a volatilidade do processo, e Δt é o passo temporal.

    2. **Gerador Multivariado Fisiológico**: Produz dados populacionais correlacionados
       (BPM, horas_sono, minutos_atividade) usando distribuição normal multivariada
       com matriz de covariância realista que captura correlações negativas entre
       frequência cardíaca de repouso e indicadores de saúde (sono, atividade).

    3. **Intervalos R-R**: Conversão de séries de frequência cardíaca para intervalos
       R-R em milissegundos com jitter gaussiano para simular variabilidade
       fisiológica natural (HRV — Heart Rate Variability).

Referências:
    - Uhlenbeck, G.E. & Ornstein, L.S. (1930). On the Theory of Brownian Motion.
    - Task Force of ESC/NASPE (1996). Heart Rate Variability: Standards of Measurement.
"""

import logging
from typing import Optional

import numpy as np

# Configuração do logger para o módulo
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class OrnsteinUhlenbeckProcess:
    """
    Processo de Ornstein-Uhlenbeck para simulação de frequência cardíaca.

    O processo OU é um processo estocástico gaussiano com reversão à média,
    amplamente utilizado para modelar variáveis fisiológicas que flutuam
    ao redor de um valor de equilíbrio homeostático.

    Formulação Matemática (SDE):
        dX_t = θ·(μ - X_t)·dt + σ·dW_t

    Discretização de Euler-Maruyama:
        X_{t+1} = X_t + θ·(μ - X_t)·Δt + σ·√(Δt)·ε,   ε ~ N(0,1)

    Propriedades Estacionárias:
        - Média estacionária: E[X_∞] = μ
        - Variância estacionária: Var[X_∞] = σ² / (2θ)
        - Tempo de autocorrelação: τ = 1/θ

    Parâmetros:
        theta (float): Taxa de reversão à média (velocidade de retorno ao equilíbrio).
            Valores maiores implicam retorno mais rápido. Unidade: 1/s.
        mu (float): Média de longo prazo do processo (ponto de equilíbrio).
            Para frequência cardíaca em repouso, tipicamente ~70 BPM.
        sigma (float): Coeficiente de difusão (volatilidade). Controla a amplitude
            das flutuações estocásticas ao redor da média.
        dt (float): Intervalo temporal de discretização em segundos.

    Atributos:
        state (float): Estado atual do processo (último valor gerado).

    Exemplo:
        >>> ou = OrnsteinUhlenbeckProcess(theta=0.5, mu=70.0, sigma=4.0, dt=1.0)
        >>> serie_hr = ou.generate(n_steps=3600, x0=72.0)
        >>> print(f"HR médio: {serie_hr.mean():.1f} BPM")
    """

    def __init__(
        self,
        theta: float = 0.5,
        mu: float = 70.0,
        sigma: float = 4.0,
        dt: float = 1.0,
    ) -> None:
        """
        Inicializa o processo de Ornstein-Uhlenbeck.

        Parâmetros:
            theta: Taxa de reversão à média. Padrão: 0.5 (tempo de relaxação ~2s).
            mu: Média de longo prazo em BPM. Padrão: 70.0.
            sigma: Coeficiente de difusão. Padrão: 4.0.
            dt: Passo temporal em segundos. Padrão: 1.0.

        Levanta:
            ValueError: Se theta, sigma ou dt forem não-positivos.
        """
        if theta <= 0:
            raise ValueError(f"theta deve ser positivo, recebido: {theta}")
        if sigma <= 0:
            raise ValueError(f"sigma deve ser positivo, recebido: {sigma}")
        if dt <= 0:
            raise ValueError(f"dt deve ser positivo, recebido: {dt}")

        self.theta: float = theta
        self.mu: float = mu
        self.sigma: float = sigma
        self.dt: float = dt
        self.state: float = mu  # Estado inicial no equilíbrio

        # Variância estacionária teórica: σ² / (2θ)
        self._stationary_variance: float = (sigma ** 2) / (2 * theta)
        logger.info(
            "Processo OU inicializado: θ=%.3f, μ=%.1f, σ=%.2f, Δt=%.2f, "
            "Var_estacionária=%.2f",
            theta, mu, sigma, dt, self._stationary_variance,
        )

    def step(self, x: float, rng: Optional[np.random.Generator] = None) -> float:
        """
        Executa um passo da discretização de Euler-Maruyama.

        Formulação:
            x_{t+1} = x_t + θ·(μ - x_t)·Δt + σ·√(Δt)·ε

        Parâmetros:
            x: Estado atual do processo.
            rng: Gerador de números aleatórios NumPy. Se None, usa o padrão.

        Retorna:
            Próximo estado do processo.
        """
        if rng is None:
            rng = np.random.default_rng()

        # Termo determinístico (drift de reversão à média)
        drift: float = self.theta * (self.mu - x) * self.dt
        # Termo estocástico (difusão browniana)
        diffusion: float = self.sigma * np.sqrt(self.dt) * rng.standard_normal()

        return x + drift + diffusion

    def generate(
        self,
        n_steps: int,
        x0: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> np.ndarray:
        """
        Gera uma série temporal completa do processo OU.

        Parâmetros:
            n_steps: Número de passos temporais a gerar.
            x0: Condição inicial. Se None, usa a média μ.
            seed: Semente para reprodutibilidade.

        Retorna:
            np.ndarray de shape (n_steps,) com a série temporal gerada.

        Nota:
            Para n_steps grande, a série converge estatisticamente para
            média μ e variância σ²/(2θ), independente de x0 (ergodicidade).
        """
        rng = np.random.default_rng(seed)
        x: float = x0 if x0 is not None else self.mu
        series: np.ndarray = np.empty(n_steps, dtype=np.float64)

        for t in range(n_steps):
            series[t] = x
            x = self.step(x, rng)

        self.state = x
        logger.debug(
            "Série OU gerada: %d passos, média=%.2f, std=%.2f",
            n_steps, series.mean(), series.std(),
        )
        return series

    @property
    def stationary_variance(self) -> float:
        """Variância estacionária teórica do processo: σ²/(2θ)."""
        return self._stationary_variance

    @property
    def relaxation_time(self) -> float:
        """Tempo de relaxação (autocorrelação) do processo: 1/θ."""
        return 1.0 / self.theta


class MultivariatePhysiologicalGenerator:
    """
    Gerador de dados fisiológicos populacionais multivariados.

    Utiliza distribuição normal multivariada para gerar amostras correlacionadas
    de variáveis fisiológicas, capturando as interdependências biológicas
    conhecidas entre frequência cardíaca, qualidade do sono e nível de atividade.

    Estrutura de Correlação:
        A matriz de covariância Σ codifica:
        - Correlação negativa BPM ↔ Sono: Indivíduos com menor FC de repouso
          tendem a dormir mais (melhor condicionamento cardiovascular).
        - Correlação negativa BPM ↔ Atividade: Maior atividade física está
          associada a menor FC de repouso (adaptação cardíaca).
        - Correlação positiva Sono ↔ Atividade: Indivíduos mais ativos
          tendem a ter melhor qualidade de sono.

    Matriz de Covariância (Σ):
        ┌                              ┐
        │  64.0    -3.2    -48.0       │   (BPM: var=64, σ=8)
        │  -3.2     1.44    12.0       │   (Sono: var=1.44, σ=1.2h)
        │ -48.0    12.0   1600.0       │   (Atividade: var=1600, σ=40min)
        └                              ┘

    Correlações Implícitas:
        ρ(BPM, Sono)      = -3.2  / (8 × 1.2)  ≈ -0.333
        ρ(BPM, Atividade) = -48.0 / (8 × 40)   = -0.150
        ρ(Sono, Atividade) = 12.0 / (1.2 × 40)  =  0.250

    Injeção de Anomalias:
        Para simular condições patológicas, 5% da população recebe:
        - BPM deslocado +25 (taquicardia de repouso)
        - Sono reduzido -3h (privação severa)
        - Atividade reduzida para 10min (sedentarismo extremo)

    Parâmetros:
        mean_bpm (float): Média populacional de BPM. Padrão: 70.
        mean_sleep (float): Média de horas de sono. Padrão: 7.0.
        mean_activity (float): Média de minutos de atividade. Padrão: 45.
        anomaly_fraction (float): Fração da população com anomalias. Padrão: 0.05.
    """

    # Médias populacionais padrão
    DEFAULT_MEANS: np.ndarray = np.array([70.0, 7.0, 45.0])

    # Matriz de covariância com correlações fisiológicas realistas
    DEFAULT_COVARIANCE: np.ndarray = np.array([
        [64.0,   -3.2,  -48.0],   # BPM: variância 64 (σ=8 BPM)
        [-3.2,    1.44,  12.0],    # Sono: variância 1.44 (σ=1.2h)
        [-48.0,  12.0,  1600.0],   # Atividade: variância 1600 (σ=40min)
    ])

    def __init__(
        self,
        mean_bpm: float = 70.0,
        mean_sleep: float = 7.0,
        mean_activity: float = 45.0,
        anomaly_fraction: float = 0.05,
    ) -> None:
        """
        Inicializa o gerador multivariado.

        Parâmetros:
            mean_bpm: Média populacional de frequência cardíaca de repouso (BPM).
            mean_sleep: Média de horas de sono por noite.
            mean_activity: Média de minutos de atividade física diária.
            anomaly_fraction: Proporção da população com perfil anômalo (0–1).

        Levanta:
            ValueError: Se anomaly_fraction estiver fora do intervalo [0, 1].
        """
        if not 0.0 <= anomaly_fraction <= 1.0:
            raise ValueError(
                f"anomaly_fraction deve estar em [0,1], recebido: {anomaly_fraction}"
            )

        self.means: np.ndarray = np.array([mean_bpm, mean_sleep, mean_activity])
        self.covariance: np.ndarray = self.DEFAULT_COVARIANCE.copy()
        self.anomaly_fraction: float = anomaly_fraction

        # Valida que a matriz de covariância é definida positiva
        eigenvalues = np.linalg.eigvalsh(self.covariance)
        if np.any(eigenvalues <= 0):
            raise ValueError(
                "Matriz de covariância não é definida positiva. "
                f"Autovalores: {eigenvalues}"
            )

        logger.info(
            "Gerador multivariado inicializado: médias=%s, anomaly_frac=%.2f",
            self.means, anomaly_fraction,
        )

    def generate_population(
        self,
        n_individuals: int,
        seed: Optional[int] = None,
    ) -> dict[str, np.ndarray]:
        """
        Gera dados fisiológicos para uma população de indivíduos.

        O processo de geração consiste em:
            1. Amostragem da distribuição normal multivariada N(μ, Σ)
            2. Identificação aleatória de indivíduos anômalos (5% padrão)
            3. Modificação dos perfis anômalos (taquicardia + privação de sono
               + sedentarismo)
            4. Clipping para garantir valores fisiologicamente plausíveis

        Parâmetros:
            n_individuals: Número de indivíduos na população.
            seed: Semente para reprodutibilidade.

        Retorna:
            Dicionário com:
                'resting_bpm': np.ndarray — Frequência cardíaca de repouso
                'sleep_hours': np.ndarray — Horas de sono
                'activity_mins': np.ndarray — Minutos de atividade diária
                'is_anomalous': np.ndarray (bool) — Máscara de indivíduos anômalos
        """
        rng = np.random.default_rng(seed)

        # Amostragem multivariada: X ~ N(μ, Σ)
        samples: np.ndarray = rng.multivariate_normal(
            mean=self.means,
            cov=self.covariance,
            size=n_individuals,
        )

        bpm: np.ndarray = samples[:, 0]
        sleep: np.ndarray = samples[:, 1]
        activity: np.ndarray = samples[:, 2]

        # Injeção de anomalias: perfil patológico para fração selecionada
        n_anomalies: int = int(n_individuals * self.anomaly_fraction)
        anomaly_mask: np.ndarray = np.zeros(n_individuals, dtype=bool)

        if n_anomalies > 0:
            anomaly_indices: np.ndarray = rng.choice(
                n_individuals, size=n_anomalies, replace=False
            )
            anomaly_mask[anomaly_indices] = True

            # Modificações patológicas mantendo estrutura multivariada
            bpm[anomaly_mask] += 25.0       # Taquicardia: +25 BPM
            sleep[anomaly_mask] -= 3.0      # Privação severa: -3h sono
            activity[anomaly_mask] = 10.0   # Sedentarismo extremo: 10min

            logger.info(
                "Anomalias injetadas: %d/%d indivíduos (%.1f%%)",
                n_anomalies, n_individuals, 100 * n_anomalies / n_individuals,
            )

        # Clipping para valores fisiologicamente plausíveis
        bpm = np.clip(bpm, 35.0, 220.0)         # Limites fisiológicos de FC
        sleep = np.clip(sleep, 0.0, 16.0)        # 0 a 16 horas
        activity = np.clip(activity, 0.0, 480.0)  # 0 a 8 horas

        logger.debug(
            "População gerada: n=%d, BPM=%.1f±%.1f, Sono=%.1f±%.1fh, "
            "Atividade=%.0f±%.0fmin",
            n_individuals, bpm.mean(), bpm.std(),
            sleep.mean(), sleep.std(),
            activity.mean(), activity.std(),
        )

        return {
            "resting_bpm": bpm,
            "sleep_hours": sleep,
            "activity_mins": activity,
            "is_anomalous": anomaly_mask,
        }

    def correlation_matrix(self) -> np.ndarray:
        """
        Calcula a matriz de correlação a partir da covariância.

        Relação: ρ_{ij} = Σ_{ij} / √(Σ_{ii} · Σ_{jj})

        Retorna:
            np.ndarray de shape (3, 3) com correlações de Pearson.
        """
        stds = np.sqrt(np.diag(self.covariance))
        return self.covariance / np.outer(stds, stds)


def generate_rr_intervals(
    hr_series: np.ndarray,
    jitter_std_ms: float = 10.0,
    seed: Optional[int] = None,
) -> np.ndarray:
    """
    Converte série de frequência cardíaca para intervalos R-R em milissegundos.

    A conversão fundamental é:
        RR(ms) = 60000 / HR(BPM)

    Para simular a variabilidade natural do intervalo R-R (HRV — Heart Rate
    Variability), adiciona-se um jitter modelado como ruído gaussiano:

        RR_observado = 60000/HR + ε,   ε ~ N(0, σ_jitter²)

    O jitter captura micro-variações no controle autonômico do nó sinoatrial
    que não são capturadas pela resolução temporal da série de HR.

    Parâmetros:
        hr_series: Array de valores de frequência cardíaca em BPM.
            Valores devem ser positivos e tipicamente entre 30-220 BPM.
        jitter_std_ms: Desvio padrão do jitter gaussiano em milissegundos.
            Valores típicos: 5-20ms para adultos saudáveis em repouso.
        seed: Semente para reprodutibilidade do jitter.

    Retorna:
        np.ndarray de intervalos R-R em milissegundos.

    Levanta:
        ValueError: Se hr_series contiver valores ≤ 0.

    Exemplo:
        >>> hr = np.array([60.0, 72.0, 80.0])
        >>> rr = generate_rr_intervals(hr, jitter_std_ms=5.0, seed=42)
        >>> print(f"RR médio: {rr.mean():.0f} ms")
    """
    hr_array: np.ndarray = np.asarray(hr_series, dtype=np.float64)

    if np.any(hr_array <= 0):
        raise ValueError(
            "Frequência cardíaca deve ser positiva. "
            f"Valores mínimo/máximo: {hr_array.min():.1f}/{hr_array.max():.1f}"
        )

    rng = np.random.default_rng(seed)

    # Conversão fundamental: RR(ms) = 60000 / HR(BPM)
    rr_base: np.ndarray = 60000.0 / hr_array

    # Adição de jitter gaussiano para simular HRV
    jitter: np.ndarray = rng.normal(0.0, jitter_std_ms, size=hr_array.shape)
    rr_intervals: np.ndarray = rr_base + jitter

    # Clipping para evitar intervalos fisiologicamente implausíveis
    # RR mínimo ~273ms (220 BPM), RR máximo ~2000ms (30 BPM)
    rr_intervals = np.clip(rr_intervals, 200.0, 2500.0)

    logger.debug(
        "Intervalos R-R gerados: n=%d, média=%.0fms, std=%.1fms, "
        "jitter_std=%.1fms",
        len(rr_intervals), rr_intervals.mean(), rr_intervals.std(),
        jitter_std_ms,
    )

    return rr_intervals


if __name__ == "__main__":
    # Configuração de logging para demonstração
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    print("=" * 70)
    print("DEMONSTRAÇÃO: Geração de Sinais Fisiológicos Realistas")
    print("=" * 70)

    # --- 1. Processo de Ornstein-Uhlenbeck ---
    print("\n--- 1. Processo de Ornstein-Uhlenbeck (Simulação de HR) ---")
    ou = OrnsteinUhlenbeckProcess(theta=0.5, mu=70.0, sigma=4.0, dt=1.0)
    hr_series = ou.generate(n_steps=3600, x0=72.0, seed=42)
    print(f"   Série gerada: {len(hr_series)} amostras")
    print(f"   HR médio: {hr_series.mean():.2f} BPM (teórico: {ou.mu})")
    print(f"   HR std:   {hr_series.std():.2f} BPM "
          f"(teórico estacionário: {np.sqrt(ou.stationary_variance):.2f})")
    print(f"   Tempo de relaxação: {ou.relaxation_time:.1f} s")
    print(f"   Primeiros 10 valores: {hr_series[:10].round(1)}")

    # --- 2. Gerador Multivariado ---
    print("\n--- 2. Gerador Multivariado Fisiológico ---")
    gen = MultivariatePhysiologicalGenerator(
        mean_bpm=70.0, mean_sleep=7.0, mean_activity=45.0, anomaly_fraction=0.05
    )
    population = gen.generate_population(n_individuals=1000, seed=42)

    print(f"   População: {len(population['resting_bpm'])} indivíduos")
    print(f"   BPM: {population['resting_bpm'].mean():.1f} ± "
          f"{population['resting_bpm'].std():.1f}")
    print(f"   Sono: {population['sleep_hours'].mean():.1f} ± "
          f"{population['sleep_hours'].std():.1f} h")
    print(f"   Atividade: {population['activity_mins'].mean():.0f} ± "
          f"{population['activity_mins'].std():.0f} min")
    print(f"   Anômalos: {population['is_anomalous'].sum()} indivíduos")

    # Matriz de correlação
    corr = gen.correlation_matrix()
    print(f"\n   Matriz de Correlação:")
    labels = ["BPM", "Sono", "Ativ"]
    print(f"         {'  '.join(f'{l:>6}' for l in labels)}")
    for i, label in enumerate(labels):
        row = "  ".join(f"{corr[i, j]:+.3f}" for j in range(3))
        print(f"   {label:>4}  {row}")

    # --- 3. Intervalos R-R ---
    print("\n--- 3. Conversão para Intervalos R-R ---")
    rr = generate_rr_intervals(hr_series[:100], jitter_std_ms=10.0, seed=42)
    print(f"   Intervalos R-R: {len(rr)} amostras")
    print(f"   RR médio: {rr.mean():.0f} ms")
    print(f"   RR std:   {rr.std():.1f} ms")
    print(f"   RMSSD (proxy HRV): {np.sqrt(np.mean(np.diff(rr)**2)):.1f} ms")
    print(f"   Primeiros 5 valores: {rr[:5].round(0)}")

    print("\n" + "=" * 70)
    print("Demonstração concluída com sucesso.")
    print("=" * 70)
