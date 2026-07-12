"""
ensemble_scorer.py — Sistema de Ensemble para Detecção de Anomalias
====================================================================

Combina múltiplos detectores heterogêneos em um escore unificado
usando calibração probabilística e teste combinado de Fisher.

Classes:
    - **PlattScaling**: Calibração de escores brutos → probabilidades via
      regressão logística (sigmoid fitting).
    - **FisherCombinedTest**: Combinação de p-valores independentes usando
      o método de Fisher (1932).
    - **EnsembleAnomalyScorer**: Orquestrador que registra detectores,
      coleta p-valores e emite vereditos com níveis de severidade.

Dependências: numpy, scipy, pandas.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import optimize, stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PlattScaling
# ---------------------------------------------------------------------------


class PlattScaling:
    """Calibração de escores brutos em probabilidades via Platt Scaling.

    Ajusta uma sigmóide parametrizada ``P(y=1 | s) = 1 / (1 + exp(A·s + B))``
    aos escores brutos ``s`` usando minimização da log-loss.

    A log-loss (entropia cruzada binária) é:

    .. math::

        \\mathcal{L}(A, B) = -\\sum_{i}
            \\bigl[ y_i \\log p_i + (1-y_i) \\log(1-p_i) \\bigr]

    onde ``p_i = \\sigma(A \\cdot s_i + B)`` e ``\\sigma`` é a função logística.

    Atributos
    ---------
    A_ : float
        Parâmetro de escala da sigmóide (ajustado).
    B_ : float
        Parâmetro de intercepto da sigmóide (ajustado).
    fitted_ : bool
        Indicador de que o modelo foi ajustado.
    """

    def __init__(self) -> None:
        self.A_: float = 0.0
        self.B_: float = 0.0
        self.fitted_: bool = False

    @staticmethod
    def _sigmoid(s: np.ndarray, A: float, B: float) -> np.ndarray:
        """Sigmóide parametrizada: P = 1 / (1 + exp(A*s + B))."""
        z = A * s + B
        # Estabilidade numérica: clamp z
        z = np.clip(z, -500.0, 500.0)
        return 1.0 / (1.0 + np.exp(z))

    def fit(
        self,
        raw_scores: np.ndarray,
        labels: np.ndarray,
    ) -> "PlattScaling":
        """Ajusta a sigmóide aos escores e rótulos fornecidos.

        Parâmetros
        ----------
        raw_scores : np.ndarray, shape (n,)
            Escores brutos de um detector (maiores → mais anômalos).
        labels : np.ndarray, shape (n,)
            Rótulos binários (1 = anomalia, 0 = normal).

        Retorna
        -------
        self

        Raises
        ------
        ValueError
            Se os arrays tiverem tamanhos diferentes ou estiverem vazios.
        """
        raw_scores = np.asarray(raw_scores, dtype=np.float64).ravel()
        labels = np.asarray(labels, dtype=np.float64).ravel()

        if raw_scores.size == 0:
            raise ValueError("raw_scores não pode estar vazio.")
        if raw_scores.shape != labels.shape:
            raise ValueError(
                f"Tamanhos incompatíveis: scores={raw_scores.shape}, "
                f"labels={labels.shape}."
            )

        eps = 1e-15

        def neg_log_loss(params: np.ndarray) -> float:
            A, B = params
            p = self._sigmoid(raw_scores, A, B)
            p = np.clip(p, eps, 1.0 - eps)
            loss = -np.sum(labels * np.log(p) + (1.0 - labels) * np.log(1.0 - p))
            return loss

        result = optimize.minimize(
            neg_log_loss,
            x0=np.array([0.0, 0.0]),
            method="Nelder-Mead",
            options={"maxiter": 10_000, "xatol": 1e-8, "fatol": 1e-8},
        )

        self.A_ = float(result.x[0])
        self.B_ = float(result.x[1])
        self.fitted_ = True

        logger.info(
            "PlattScaling ajustado: A=%.6f, B=%.6f, loss_final=%.4f",
            self.A_, self.B_, result.fun,
        )
        return self

    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        """Transforma escores brutos em probabilidades calibradas.

        .. math::

            P = \\frac{1}{1 + \\exp(A \\cdot s + B)}

        Parâmetros
        ----------
        raw_scores : np.ndarray
            Escores brutos.

        Retorna
        -------
        np.ndarray
            Probabilidades calibradas em [0, 1].

        Raises
        ------
        RuntimeError
            Se ``fit`` não tiver sido chamado antes.
        """
        if not self.fitted_:
            raise RuntimeError("PlattScaling não foi ajustado. Chame fit() primeiro.")
        raw_scores = np.asarray(raw_scores, dtype=np.float64).ravel()
        return self._sigmoid(raw_scores, self.A_, self.B_)


# ---------------------------------------------------------------------------
# FisherCombinedTest
# ---------------------------------------------------------------------------


class FisherCombinedTest:
    """Combinação de p-valores independentes pelo método de Fisher.

    O método de Fisher combina ``k`` p-valores independentes em uma
    estatística de teste:

    .. math::

        X^2 = -2 \\sum_{i=1}^{k} \\ln(p_i)

    Sob ``H_0`` (todos os p-valores uniformes), ``X² ~ χ²(2k)``.

    Notas
    -----
    P-valores exatamente zero são substituídos por ``ε = 1e-300`` para
    evitar ``ln(0)``.
    """

    @staticmethod
    def combine(p_values: List[float]) -> Dict[str, Any]:
        """Combina p-valores via método de Fisher.

        Parâmetros
        ----------
        p_values : list[float]
            Lista de p-valores individuais ∈ (0, 1].

        Retorna
        -------
        dict
            Chaves: ``test_statistic`` (float), ``combined_p_value`` (float),
            ``df`` (int — graus de liberdade = 2k).

        Raises
        ------
        ValueError
            Se a lista estiver vazia.
        """
        if len(p_values) == 0:
            raise ValueError("A lista de p-valores não pode estar vazia.")

        k = len(p_values)
        eps = 1e-300
        arr = np.array(p_values, dtype=np.float64)
        # Proteção contra log(0)
        arr = np.clip(arr, eps, 1.0)

        test_stat = float(-2.0 * np.sum(np.log(arr)))
        df = 2 * k
        combined_p = float(1.0 - stats.chi2.cdf(test_stat, df=df))

        logger.debug(
            "Fisher combinado: k=%d, X²=%.4f, df=%d, p_combinado=%.6e",
            k, test_stat, df, combined_p,
        )

        return {
            "test_statistic": test_stat,
            "combined_p_value": combined_p,
            "df": df,
        }


# ---------------------------------------------------------------------------
# EnsembleAnomalyScorer
# ---------------------------------------------------------------------------


class EnsembleAnomalyScorer:
    """Orquestrador de ensemble para detecção de anomalias.

    Registra múltiplos detectores, coleta p-valores individuais e
    combina-os estatisticamente via teste de Fisher para produzir
    um veredito unificado com níveis de severidade clínica.

    Níveis de Severidade
    --------------------
    ========== ==================
    Nível      Condição
    ========== ==================
    normal     p > 0.05
    watch      0.01 < p ≤ 0.05
    warning    0.001 < p ≤ 0.01
    critical   p ≤ 0.001
    ========== ==================

    Uso típico
    ----------
    >>> ensemble = EnsembleAnomalyScorer()
    >>> ensemble.add_detector("mahalanobis", maha_scorer, weight=1.0)
    >>> ensemble.add_detector("zscore", zscore_detector, weight=0.8)
    >>> result = ensemble.score_observation({"feature_a": 5.1, "feature_b": 10.2})
    """

    _SEVERITY_THRESHOLDS: List[Tuple[float, str]] = [
        (0.001, "critical"),
        (0.01, "warning"),
        (0.05, "watch"),
        (float("inf"), "normal"),
    ]

    def __init__(self) -> None:
        self._detectors: Dict[str, Dict[str, Any]] = {}
        self._fisher = FisherCombinedTest()
        logger.info("EnsembleAnomalyScorer inicializado (sem detectores).")

    def add_detector(
        self,
        name: str,
        detector: Any,
        weight: float = 1.0,
    ) -> None:
        """Registra um detector no ensemble.

        O detector deve possuir ao menos um dos seguintes métodos:
        - ``p_value(x) -> float``
        - ``score(x) -> float``  (usado como fallback sem calibração)

        Parâmetros
        ----------
        name : str
            Identificador único do detector.
        detector : object
            Instância do detector com interface compatível.
        weight : float
            Peso do detector na combinação (reservado para futuras
            extensões de ponderação).
        """
        self._detectors[name] = {
            "detector": detector,
            "weight": weight,
        }
        logger.info("Detector '%s' adicionado ao ensemble (peso=%.2f).", name, weight)

    @staticmethod
    def _classify_severity(p_value: float) -> str:
        """Classifica o p-valor combinado em nível de severidade.

        Parâmetros
        ----------
        p_value : float
            P-valor combinado.

        Retorna
        -------
        str
            Um de: ``'normal'``, ``'watch'``, ``'warning'``, ``'critical'``.
        """
        for threshold, label in EnsembleAnomalyScorer._SEVERITY_THRESHOLDS:
            if p_value <= threshold:
                return label
        return "normal"  # fallback

    def score_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Pontua uma observação usando todos os detectores registrados.

        Para cada detector, tenta chamar ``p_value`` passando a observação
        como um array numpy. Se ``p_value`` não estiver disponível, usa
        ``score`` e aplica uma heurística exponencial para gerar um
        pseudo-p-valor.

        Parâmetros
        ----------
        observation : dict
            Dicionário ``{feature_name: value}``. Os valores são convertidos
            em um array numpy para alimentar os detectores.

        Retorna
        -------
        dict
            Chaves:
            - ``individual_scores``: dict[str, float]
            - ``individual_p_values``: dict[str, float]
            - ``combined_p_value``: float
            - ``is_anomaly``: bool (True se ``combined_p_value ≤ 0.05``)
            - ``severity``: str

        Raises
        ------
        RuntimeError
            Se nenhum detector estiver registrado.
        """
        if not self._detectors:
            raise RuntimeError("Nenhum detector registrado no ensemble.")

        # Converter observação em array
        if isinstance(observation, dict):
            obs_array = np.array(list(observation.values()), dtype=np.float64)
        else:
            obs_array = np.asarray(observation, dtype=np.float64)

        individual_scores: Dict[str, float] = {}
        individual_p_values: Dict[str, float] = {}

        for name, entry in self._detectors.items():
            det = entry["detector"]

            # Obter escore
            score_val = np.nan
            if hasattr(det, "score") and callable(det.score):
                try:
                    score_val = float(det.score(obs_array))
                except Exception as exc:
                    logger.warning("Detector '%s' falhou em score(): %s", name, exc)
            individual_scores[name] = score_val

            # Obter p-valor
            p_val = np.nan
            if hasattr(det, "p_value") and callable(det.p_value):
                try:
                    p_val = float(det.p_value(obs_array))
                except Exception as exc:
                    logger.warning("Detector '%s' falhou em p_value(): %s", name, exc)
            elif not np.isnan(score_val):
                # Heurística: p ≈ exp(-score) para detectores sem p_value
                p_val = float(np.exp(-max(score_val, 0.0)))
                logger.debug(
                    "Detector '%s': usando heurística exp(-score)=%.6e",
                    name, p_val,
                )

            # Clamp para evitar problemas em Fisher
            if np.isnan(p_val):
                p_val = 1.0  # conservador: sem evidência de anomalia
            p_val = float(np.clip(p_val, 1e-300, 1.0))
            individual_p_values[name] = p_val

        # Combinar p-valores via Fisher
        p_list = list(individual_p_values.values())
        fisher_result = self._fisher.combine(p_list)
        combined_p = fisher_result["combined_p_value"]

        severity = self._classify_severity(combined_p)
        is_anomaly = combined_p <= 0.05

        result = {
            "individual_scores": individual_scores,
            "individual_p_values": individual_p_values,
            "combined_p_value": combined_p,
            "is_anomaly": is_anomaly,
            "severity": severity,
        }

        if is_anomaly:
            logger.warning(
                "Ensemble: ANOMALIA detectada — p_combinado=%.6e, severidade=%s",
                combined_p, severity,
            )

        return result

    def score_dataframe(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
    ) -> pd.DataFrame:
        """Pontua todas as linhas de um DataFrame e adiciona colunas de anomalia.

        Colunas adicionadas ao DataFrame retornado:
        - ``anomaly_combined_p``: p-valor combinado.
        - ``anomaly_is_anomaly``: bool.
        - ``anomaly_severity``: str.
        - ``anomaly_score_<detector>``: escore individual de cada detector.
        - ``anomaly_pval_<detector>``: p-valor individual de cada detector.

        Parâmetros
        ----------
        df : pd.DataFrame
            DataFrame com os dados a serem pontuados.
        feature_cols : list[str]
            Nomes das colunas de features a serem usadas.

        Retorna
        -------
        pd.DataFrame
            Cópia do DataFrame original com as colunas de anomalia adicionadas.
        """
        if df.empty:
            logger.warning("DataFrame vazio fornecido a score_dataframe.")
            return df.copy()

        result_df = df.copy()

        combined_p_list: List[float] = []
        is_anomaly_list: List[bool] = []
        severity_list: List[str] = []
        detector_scores: Dict[str, List[float]] = {
            name: [] for name in self._detectors
        }
        detector_pvals: Dict[str, List[float]] = {
            name: [] for name in self._detectors
        }

        for idx in range(len(df)):
            row = df.iloc[idx]
            obs = {col: float(row[col]) for col in feature_cols}
            res = self.score_observation(obs)

            combined_p_list.append(res["combined_p_value"])
            is_anomaly_list.append(res["is_anomaly"])
            severity_list.append(res["severity"])

            for name in self._detectors:
                detector_scores[name].append(
                    res["individual_scores"].get(name, np.nan)
                )
                detector_pvals[name].append(
                    res["individual_p_values"].get(name, np.nan)
                )

        result_df["anomaly_combined_p"] = combined_p_list
        result_df["anomaly_is_anomaly"] = is_anomaly_list
        result_df["anomaly_severity"] = severity_list

        for name in self._detectors:
            result_df[f"anomaly_score_{name}"] = detector_scores[name]
            result_df[f"anomaly_pval_{name}"] = detector_pvals[name]

        n_anomalies = sum(is_anomaly_list)
        logger.info(
            "score_dataframe: %d/%d linhas classificadas como anômalas.",
            n_anomalies, len(df),
        )

        return result_df


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    from temporal_detector import MahalanobisScorer

    rng = np.random.default_rng(2024)

    # ---- Platt Scaling Demo ----
    print("=" * 70)
    print("  Platt Scaling -- Demonstracao")
    print("=" * 70)

    # Simular escores brutos: normais ~ N(2,1), anomalias ~ N(6,1)
    n_normal, n_anom = 500, 50
    scores_normal = rng.normal(2.0, 1.0, n_normal)
    scores_anom = rng.normal(6.0, 1.0, n_anom)
    all_scores = np.concatenate([scores_normal, scores_anom])
    all_labels = np.concatenate([np.zeros(n_normal), np.ones(n_anom)])

    platt = PlattScaling()
    platt.fit(all_scores, all_labels)
    print(f"  A={platt.A_:.4f}, B={platt.B_:.4f}")

    test_scores = np.array([1.0, 3.0, 5.0, 7.0, 9.0])
    calibrated = platt.transform(test_scores)
    for s, p in zip(test_scores, calibrated):
        print(f"  Score bruto={s:.1f} -> P(anomalia)={p:.4f}")

    # ---- Fisher Combined Test Demo ----
    print("\n" + "=" * 70)
    print("  Fisher Combined Test -- Demonstracao")
    print("=" * 70)

    fisher = FisherCombinedTest()

    # Cenário 1: p-valores grandes (sem evidência)
    pvals_ok = [0.5, 0.3, 0.8]
    r1 = fisher.combine(pvals_ok)
    print(f"  P-valores {pvals_ok}: X²={r1['test_statistic']:.4f}, "
          f"p_combinado={r1['combined_p_value']:.4f}")

    # Cenário 2: p-valores pequenos (forte evidência)
    pvals_bad = [0.001, 0.005, 0.01]
    r2 = fisher.combine(pvals_bad)
    print(f"  P-valores {pvals_bad}: X²={r2['test_statistic']:.4f}, "
          f"p_combinado={r2['combined_p_value']:.6e}")

    # ---- Ensemble Demo ----
    print("\n" + "=" * 70)
    print("  Ensemble Anomaly Scorer -- Demonstracao")
    print("=" * 70)

    # Treinar Mahalanobis
    train = rng.multivariate_normal(
        mean=[60.0, 120.0, 36.5],
        cov=[[4, 1, 0.5], [1, 25, 1], [0.5, 1, 0.3]],
        size=500,
    )
    maha = MahalanobisScorer(fit_data=train)

    # Criar ensemble
    ensemble = EnsembleAnomalyScorer()
    ensemble.add_detector("mahalanobis", maha, weight=1.0)

    # Teste pontual
    obs_normal = {"hr": 61.0, "bp": 118.0, "temp": 36.4}
    obs_anom = {"hr": 95.0, "bp": 180.0, "temp": 39.5}

    r_normal = ensemble.score_observation(obs_normal)
    r_anom = ensemble.score_observation(obs_anom)

    print(f"  Normal:  p={r_normal['combined_p_value']:.4f}, "
          f"severity={r_normal['severity']}")
    print(f"  Anômalo: p={r_anom['combined_p_value']:.6e}, "
          f"severity={r_anom['severity']}")

    # DataFrame demo
    print("\n  --- DataFrame scoring ---")
    n_rows = 200
    df_data = rng.multivariate_normal(
        mean=[60.0, 120.0, 36.5],
        cov=[[4, 1, 0.5], [1, 25, 1], [0.5, 1, 0.3]],
        size=n_rows,
    )
    # Injetar anomalias
    df_data[-10:] = rng.multivariate_normal(
        mean=[90.0, 170.0, 39.0],
        cov=[[4, 1, 0.5], [1, 25, 1], [0.5, 1, 0.3]],
        size=10,
    )

    df = pd.DataFrame(df_data, columns=["hr", "bp", "temp"])
    scored_df = ensemble.score_dataframe(df, feature_cols=["hr", "bp", "temp"])

    severity_counts = scored_df["anomaly_severity"].value_counts()
    print(f"  Distribuição de severidade:\n{severity_counts.to_string()}")
    print(f"\n  Amostra (últimas 5 linhas):")
    print(scored_df[["hr", "bp", "temp", "anomaly_combined_p", "anomaly_severity"]].tail().to_string())

    print("\n[OK] Demonstracao do ensemble concluida com sucesso.")
