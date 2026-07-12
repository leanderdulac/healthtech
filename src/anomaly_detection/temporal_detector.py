"""
temporal_detector.py — Algoritmos de Detecção Temporal de Anomalias
===================================================================

Implementa três detectores complementares para séries temporais biomédicas:

1. **CUSUMDetector** — Teste de soma cumulativa (Page, 1954).
2. **MahalanobisScorer** — Distância de Mahalanobis multivariada.
3. **AdaptiveZScore** — Z-score adaptativo com suavização exponencial (EWMA).

Dependências: numpy, scipy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CUSUMDetector
# ---------------------------------------------------------------------------


class CUSUMDetector:
    """Detecção sequencial de mudanças de média via CUSUM (Cumulative Sum).

    O algoritmo CUSUM monitora desvios persistentes em relação a uma média
    de referência ``μ₀``. Duas estatísticas cumulativas são mantidas:

    .. math::

        S^{+}_t = \\max\\bigl(0,\\; S^{+}_{t-1} + (x_t - \\mu_0 - k)\\bigr)

        S^{-}_t = \\max\\bigl(0,\\; S^{-}_{t-1} - (x_t - \\mu_0 + k)\\bigr)

    Um alarme é acionado quando ``S⁺ > h`` (desvio para cima) ou
    ``S⁻ > h`` (desvio para baixo).

    Parâmetros
    ----------
    mu0 : float
        Média de referência (valor esperado sob controle).
    k : float
        Tolerância (slack / allowance). Quanto maior, menos sensível.
    h : float
        Limiar de decisão. Quanto maior, menos alarmes falsos.

    Atributos
    ---------
    S_plus : float
        Soma cumulativa superior.
    S_minus : float
        Soma cumulativa inferior.
    alarm_history : list[dict]
        Histórico de todos os alarmes disparados.
    """

    def __init__(self, mu0: float = 70.0, k: float = 5.0, h: float = 10.0) -> None:
        self.mu0: float = mu0
        self.k: float = k
        self.h: float = h

        # Estado interno
        self.S_plus: float = 0.0
        self.S_minus: float = 0.0
        self._step: int = 0
        self.alarm_history: List[Dict[str, Any]] = []

        logger.info(
            "CUSUMDetector inicializado: μ₀=%.2f, k=%.2f, h=%.2f",
            mu0, k, h,
        )

    # ----- API pública -----

    def update(self, x: float) -> Dict[str, Any]:
        """Processa uma nova observação e retorna o estado do detector.

        Parâmetros
        ----------
        x : float
            Valor observado no instante atual.

        Retorna
        -------
        dict
            Chaves: ``alarm`` (bool), ``S_plus`` (float), ``S_minus`` (float),
            ``direction`` (``'up'`` | ``'down'`` | ``None``).
        """
        self._step += 1

        self.S_plus = max(0.0, self.S_plus + (x - self.mu0 - self.k))
        self.S_minus = max(0.0, self.S_minus - (x - self.mu0 + self.k))

        direction: Optional[str] = None
        alarm = False

        if self.S_plus > self.h:
            alarm = True
            direction = "up"
        if self.S_minus > self.h:
            alarm = True
            # Se ambas dispararam, a maior define a direção dominante
            if direction is None or self.S_minus > self.S_plus:
                direction = "down"

        result: Dict[str, Any] = {
            "alarm": alarm,
            "S_plus": self.S_plus,
            "S_minus": self.S_minus,
            "direction": direction,
        }

        if alarm:
            record = {"step": self._step, "x": x, **result}
            self.alarm_history.append(record)
            logger.warning(
                "CUSUM alarme no passo %d: x=%.4f, S⁺=%.4f, S⁻=%.4f, dir=%s",
                self._step, x, self.S_plus, self.S_minus, direction,
            )

        return result

    def process_series(self, series: Sequence[float]) -> List[Dict[str, Any]]:
        """Processa uma série inteira de observações.

        Parâmetros
        ----------
        series : sequência de float
            Série temporal a ser analisada.

        Retorna
        -------
        list[dict]
            Lista de resultados de ``update`` para cada ponto.
        """
        if len(series) == 0:
            logger.warning("Série vazia fornecida a process_series.")
            return []
        return [self.update(x) for x in series]

    def reset(self) -> None:
        """Reinicia as somas cumulativas e o contador de passos."""
        self.S_plus = 0.0
        self.S_minus = 0.0
        self._step = 0
        logger.info("CUSUMDetector resetado.")

    def set_params_from_data(
        self,
        baseline_data: Sequence[float],
        num_sigma: float = 3.0,
    ) -> None:
        """Auto-calibra os parâmetros (μ₀, k, h) a partir de dados de referência.

        Estratégia
        ----------
        - ``μ₀ = \\overline{x}``  (média amostral)
        - ``δ  = \\text{num\\_sigma} \\times s``  (desvio que se deseja detectar)
        - ``k  = δ / 2``
        - ``h  = 4s`` a ``5s``  — aqui usamos ``h = 5s`` como margem conservadora.

        Parâmetros
        ----------
        baseline_data : sequência de float
            Dados sob condições normais de operação.
        num_sigma : float
            Número de desvios-padrão que define o desvio alvo δ.

        Raises
        ------
        ValueError
            Se ``baseline_data`` estiver vazio.
        """
        arr = np.asarray(baseline_data, dtype=np.float64)
        if arr.size == 0:
            raise ValueError("baseline_data não pode estar vazio.")

        mu = float(np.mean(arr))
        sigma = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0

        delta = num_sigma * sigma
        self.mu0 = mu
        self.k = 0.5 * delta
        self.h = 5.0 * sigma if sigma > 0 else 1.0  # fallback

        self.reset()
        logger.info(
            "CUSUM auto-calibrado: μ₀=%.4f, σ=%.4f, δ=%.4f, k=%.4f, h=%.4f",
            mu, sigma, delta, self.k, self.h,
        )


# ---------------------------------------------------------------------------
# MahalanobisScorer
# ---------------------------------------------------------------------------


class MahalanobisScorer:
    """Pontuação de anomalias via distância de Mahalanobis.

    Para um vetor de observação ``x`` em ℝᵖ, a distância de Mahalanobis
    em relação à distribuição de treino é:

    .. math::

        D_M(\\mathbf{x}) = \\sqrt{
            (\\mathbf{x} - \\boldsymbol{\\mu})^\\top
            \\boldsymbol{\\Sigma}^{-1}
            (\\mathbf{x} - \\boldsymbol{\\mu})
        }

    Sob normalidade multivariada, ``D_M² ~ χ²(p)``, permitindo o cálculo
    de p-valores analíticos.

    Parâmetros
    ----------
    fit_data : np.ndarray | None
        Se fornecido, ``fit`` é chamado automaticamente na inicialização.
    """

    def __init__(self, fit_data: Optional[np.ndarray] = None) -> None:
        self.mu_: Optional[np.ndarray] = None
        self.sigma_inv_: Optional[np.ndarray] = None
        self.p_: int = 0  # dimensionalidade

        if fit_data is not None:
            self.fit(fit_data)

    # ----- Treinamento -----

    def fit(self, X: np.ndarray) -> "MahalanobisScorer":
        """Estima média e covariância a partir dos dados de treino.

        Utiliza ``np.linalg.pinv`` (pseudo-inversa) para garantir
        estabilidade numérica em matrizes singulares ou quase-singulares.

        Parâmetros
        ----------
        X : np.ndarray, shape (n, p)
            Matriz de dados de treino (n amostras, p features).

        Retorna
        -------
        self
            Instância ajustada.

        Raises
        ------
        ValueError
            Se ``X`` tiver menos de 2 amostras ou for unidimensional
            sem reestruturação possível.
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        if X.shape[0] < 2:
            raise ValueError(
                "São necessárias pelo menos 2 amostras para estimar a covariância."
            )

        self.p_ = X.shape[1]
        self.mu_ = np.mean(X, axis=0)
        cov = np.cov(X, rowvar=False)

        # Garantir que cov seja 2-D mesmo para p=1
        cov = np.atleast_2d(cov)

        self.sigma_inv_ = np.linalg.pinv(cov)

        logger.info(
            "MahalanobisScorer ajustado: p=%d, n=%d, cond(Σ)=%.2e",
            self.p_, X.shape[0], np.linalg.cond(cov),
        )
        return self

    # ----- Pontuação -----

    def _check_fitted(self) -> None:
        if self.mu_ is None or self.sigma_inv_ is None:
            raise RuntimeError(
                "MahalanobisScorer não foi ajustado. Chame fit() primeiro."
            )

    def score(self, x: np.ndarray) -> float:
        """Calcula a distância de Mahalanobis para uma observação.

        Parâmetros
        ----------
        x : np.ndarray, shape (p,) ou (1, p)
            Vetor de observação.

        Retorna
        -------
        float
            Distância de Mahalanobis ``D_M(x)``.
        """
        self._check_fitted()
        x = np.asarray(x, dtype=np.float64).ravel()
        if x.shape[0] != self.p_:
            raise ValueError(
                f"Dimensão esperada {self.p_}, recebida {x.shape[0]}."
            )
        diff = x - self.mu_
        # D_M² = diff^T @ Σ⁻¹ @ diff
        dm_sq = float(diff @ self.sigma_inv_ @ diff)
        # Proteção contra valores negativos por erro numérico
        dm_sq = max(dm_sq, 0.0)
        return float(np.sqrt(dm_sq))

    def score_batch(self, X: np.ndarray) -> np.ndarray:
        """Calcula distâncias de Mahalanobis para um lote de observações.

        Parâmetros
        ----------
        X : np.ndarray, shape (n, p)
            Matriz de observações.

        Retorna
        -------
        np.ndarray, shape (n,)
            Vetor de distâncias de Mahalanobis.
        """
        self._check_fitted()
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(-1, self.p_)
        diff = X - self.mu_  # (n, p)
        # Vetorizado: dm_sq[i] = diff[i] @ Σ⁻¹ @ diff[i]
        left = diff @ self.sigma_inv_  # (n, p)
        dm_sq = np.sum(left * diff, axis=1)  # (n,)
        dm_sq = np.maximum(dm_sq, 0.0)
        return np.sqrt(dm_sq)

    def p_value(self, x: np.ndarray) -> float:
        """Calcula o p-valor sob hipótese de normalidade multivariada.

        Sob normalidade, ``D_M² ~ χ²(p)`` onde ``p`` é a dimensionalidade.

        .. math::

            \\text{p-valor} = 1 - F_{\\chi^2(p)}(D_M^2)

        Parâmetros
        ----------
        x : np.ndarray
            Vetor de observação.

        Retorna
        -------
        float
            P-valor em [0, 1].
        """
        dm = self.score(x)
        dm_sq = dm ** 2
        pval = 1.0 - stats.chi2.cdf(dm_sq, df=self.p_)
        return float(pval)

    def is_anomaly(self, x: np.ndarray, alpha: float = 0.01) -> bool:
        """Verifica se a observação é anômala ao nível de significância α.

        Parâmetros
        ----------
        x : np.ndarray
            Vetor de observação.
        alpha : float
            Nível de significância (padrão 0.01).

        Retorna
        -------
        bool
            ``True`` se o p-valor < α.
        """
        return self.p_value(x) < alpha


# ---------------------------------------------------------------------------
# AdaptiveZScore
# ---------------------------------------------------------------------------


class AdaptiveZScore:
    """Z-score adaptativo com média e variância exponencialmente ponderadas (EWMA).

    A média e a variância são atualizadas a cada novo ponto usando
    suavização exponencial com fator ``α = 2 / (span + 1)``:

    .. math::

        \\hat{\\mu}_t = \\alpha \\cdot x_t + (1 - \\alpha) \\cdot \\hat{\\mu}_{t-1}

        \\hat{\\sigma}^2_t = \\alpha \\cdot (x_t - \\hat{\\mu}_t)^2
                             + (1 - \\alpha) \\cdot \\hat{\\sigma}^2_{t-1}

        z_t = \\frac{x_t - \\hat{\\mu}_t}{\\hat{\\sigma}_t}

    Um alarme é acionado quando ``|z_t| > \\text{threshold}``.

    Parâmetros
    ----------
    span : int
        Janela efetiva para a suavização exponencial.
    threshold : float
        Limiar do z-score para acionamento de alarme.
    """

    def __init__(self, span: int = 50, threshold: float = 3.0) -> None:
        if span < 1:
            raise ValueError("span deve ser >= 1.")
        self.span: int = span
        self.threshold: float = threshold
        self.alpha: float = 2.0 / (span + 1.0)

        # Estado interno
        self._ewma_mean: Optional[float] = None
        self._ewma_var: float = 0.0
        self._initialized: bool = False
        self._step: int = 0

        logger.info(
            "AdaptiveZScore inicializado: span=%d, α=%.4f, threshold=%.2f",
            span, self.alpha, threshold,
        )

    def update(self, x: float) -> Dict[str, Any]:
        """Processa uma nova observação e retorna o z-score adaptativo.

        Parâmetros
        ----------
        x : float
            Valor observado.

        Retorna
        -------
        dict
            Chaves: ``z_score`` (float), ``alarm`` (bool),
            ``ewma_mean`` (float), ``ewma_std`` (float).
        """
        self._step += 1

        if not self._initialized:
            self._ewma_mean = x
            self._ewma_var = 0.0
            self._initialized = True
            return {
                "z_score": 0.0,
                "alarm": False,
                "ewma_mean": self._ewma_mean,
                "ewma_std": 0.0,
            }

        # Atualizar EWMA da média
        self._ewma_mean = self.alpha * x + (1.0 - self.alpha) * self._ewma_mean

        # Atualizar EWMA da variância
        self._ewma_var = (
            self.alpha * (x - self._ewma_mean) ** 2
            + (1.0 - self.alpha) * self._ewma_var
        )

        ewma_std = float(np.sqrt(self._ewma_var))

        # Proteção contra divisão por zero
        if ewma_std < 1e-12:
            z_score = 0.0
        else:
            z_score = (x - self._ewma_mean) / ewma_std

        alarm = abs(z_score) > self.threshold

        if alarm:
            logger.warning(
                "AdaptiveZScore alarme no passo %d: z=%.4f, x=%.4f",
                self._step, z_score, x,
            )

        return {
            "z_score": float(z_score),
            "alarm": alarm,
            "ewma_mean": float(self._ewma_mean),
            "ewma_std": ewma_std,
        }

    def process_series(self, series: Sequence[float]) -> List[Dict[str, Any]]:
        """Processa uma série inteira de observações.

        Parâmetros
        ----------
        series : sequência de float
            Série temporal a ser analisada.

        Retorna
        -------
        list[dict]
            Lista de resultados de ``update`` para cada ponto.
        """
        if len(series) == 0:
            logger.warning("Série vazia fornecida a process_series.")
            return []
        return [self.update(x) for x in series]


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    rng = np.random.default_rng(42)

    # ---- CUSUM Demo ----
    print("=" * 70)
    print("  CUSUM Detector -- Demonstracao")
    print("=" * 70)

    baseline = rng.normal(loc=70.0, scale=2.0, size=200)
    cusum = CUSUMDetector()
    cusum.set_params_from_data(baseline, num_sigma=3)
    print(f"  Parametros auto-calibrados: mu0={cusum.mu0:.2f}, k={cusum.k:.2f}, h={cusum.h:.2f}")

    # Série com mudança de média no ponto 100
    normal_part = rng.normal(loc=70.0, scale=2.0, size=100)
    shifted_part = rng.normal(loc=80.0, scale=2.0, size=100)
    series = np.concatenate([normal_part, shifted_part])

    cusum.reset()
    results = cusum.process_series(series)
    alarm_steps = [i for i, r in enumerate(results) if r["alarm"]]
    print(f"  Alarmes em {len(alarm_steps)} de {len(series)} pontos.")
    if alarm_steps:
        print(f"  Primeiro alarme no índice: {alarm_steps[0]}")

    # ---- Mahalanobis Demo ----
    print("\n" + "=" * 70)
    print("  Mahalanobis Scorer -- Demonstracao")
    print("=" * 70)

    train_data = rng.multivariate_normal(
        mean=[5.0, 10.0, 3.0],
        cov=[[1, 0.5, 0.2], [0.5, 2, 0.3], [0.2, 0.3, 0.8]],
        size=500,
    )
    maha = MahalanobisScorer(fit_data=train_data)

    normal_obs = np.array([5.1, 10.2, 3.1])
    anomaly_obs = np.array([12.0, 20.0, 9.0])

    print(f"  Observação normal:   D_M={maha.score(normal_obs):.4f}, "
          f"p={maha.p_value(normal_obs):.4f}, anomalia={maha.is_anomaly(normal_obs)}")
    print(f"  Observação anômala:  D_M={maha.score(anomaly_obs):.4f}, "
          f"p={maha.p_value(anomaly_obs):.6f}, anomalia={maha.is_anomaly(anomaly_obs)}")

    # Batch
    test_batch = rng.multivariate_normal(
        mean=[5.0, 10.0, 3.0],
        cov=[[1, 0.5, 0.2], [0.5, 2, 0.3], [0.2, 0.3, 0.8]],
        size=50,
    )
    scores = maha.score_batch(test_batch)
    print(f"  Batch (50 obs): D_M médio={scores.mean():.4f}, máx={scores.max():.4f}")

    # ---- AdaptiveZScore Demo ----
    print("\n" + "=" * 70)
    print("  Adaptive Z-Score -- Demonstracao")
    print("=" * 70)

    az = AdaptiveZScore(span=30, threshold=3.0)
    stable = rng.normal(loc=100, scale=5, size=150)
    spike = np.array([100, 100, 150, 155, 100, 100])  # spikes artificiais
    full_series = np.concatenate([stable, spike])
    az_results = az.process_series(full_series)

    az_alarms = [(i, r["z_score"]) for i, r in enumerate(az_results) if r["alarm"]]
    print(f"  Alarmes: {len(az_alarms)} de {len(full_series)} pontos.")
    for idx, z in az_alarms[:5]:
        print(f"    Índice {idx}: z={z:.2f}")

    print("\n[OK] Demonstracao concluida com sucesso.")
