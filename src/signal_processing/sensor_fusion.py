"""
sensor_fusion.py — Fusão Bayesiana de Sensores
===============================================

Este módulo implementa fusão de dados multi-sensor usando princípios Bayesianos,
especificamente a ponderação por variância inversa (inverse-variance weighting),
que é a solução ótima de mínima variância para combinar estimativas independentes.

Fundamentos Matemáticos:
    Dado um conjunto de K sensores com leituras {z_k} e variâncias {σ²_k},
    a estimativa fusionada ótima (BLUE — Best Linear Unbiased Estimator) é:

        x̂_fused = Σ(w_k · z_k),  onde w_k = (1/σ²_k) / Σ(1/σ²_j)

    A variância da estimativa fusionada é:

        σ²_fused = 1 / Σ(1/σ²_k)

    Esta formulação é equivalente à atualização Bayesiana com priors gaussianos
    conjugados e garante que sensores mais precisos recebem maior peso.

Estimativa Adaptativa de Variância:
    A variância de cada sensor é estimada online via EWMA (Exponentially
    Weighted Moving Average):

        σ²_{t+1} = λ·σ²_t + (1-λ)·(z_t - x̂_t)²

    onde λ ∈ (0,1) controla a memória do estimador. Valores próximos a 1
    dão mais peso ao histórico; valores menores adaptam mais rapidamente.

Detecção de Outliers:
    Implementa o teste de Grubbs para detecção de valores anômalos em
    janelas temporais, baseado na estatística:

        G = max|x_i - x̄| / s

    comparada com o valor crítico da distribuição t-Student.

Referências:
    - Durrant-Whyte, H. (2001). Multi Sensor Data Fusion.
    - Grubbs, F.E. (1950). Sample Criteria for Testing Outlying Observations.
    - Welch, G. & Bishop, G. (1995). An Introduction to the Kalman Filter.
"""

import logging
from typing import Optional

import numpy as np
from scipy import stats

# Compatibilidade: importação condicional de pandas
try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

# Configuração do logger para o módulo
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class AdaptiveSensorFusion:
    """
    Fusão adaptativa de múltiplos sensores usando ponderação Bayesiana.

    Combina leituras de K sensores em uma estimativa única, ótima no sentido
    de mínima variância (BLUE), com estimativa adaptativa de variância per-sensor
    via EWMA e detecção de outliers via teste de Grubbs.

    Formulação da Fusão:
        x̂ = Σ(w_k · z_k),   w_k = (1/σ²_k) / Σ(1/σ²_j)
        σ²_fused = 1 / Σ(1/σ²_k)

    Atualização EWMA de Variância:
        σ²_new = λ·σ²_old + (1-λ)·(z - x̂)²

    Parâmetros:
        sensor_ids (list[str]): Identificadores dos sensores.
        lambda_ewma (float): Fator de decaimento EWMA (0 < λ < 1). Padrão: 0.95.
        initial_variance (float): Variância inicial assumida para todos os sensores.

    Exemplo:
        >>> fusion = AdaptiveSensorFusion(
        ...     sensor_ids=["wrist_ppg", "chest_ecg", "finger_spo2"],
        ...     lambda_ewma=0.95,
        ...     initial_variance=4.0,
        ... )
        >>> result = fusion.fuse_readings({
        ...     "wrist_ppg": 72.3,
        ...     "chest_ecg": 71.8,
        ...     "finger_spo2": 74.1,
        ... })
        >>> print(f"Fusão: {result['fused_estimate']:.2f} BPM")
    """

    def __init__(
        self,
        sensor_ids: list[str],
        lambda_ewma: float = 0.95,
        initial_variance: float = 4.0,
    ) -> None:
        """
        Inicializa o sistema de fusão de sensores.

        Parâmetros:
            sensor_ids: Lista de identificadores únicos dos sensores.
            lambda_ewma: Fator de suavização EWMA para variância (0 < λ < 1).
                Valores altos (>0.9) dão mais peso ao histórico.
                Valores baixos (<0.5) adaptam-se rapidamente a mudanças.
            initial_variance: Variância inicial assumida para todos os sensores
                antes de calibração online. Unidade: mesma do sinal ao quadrado.

        Levanta:
            ValueError: Se sensor_ids estiver vazio ou lambda_ewma fora de (0,1).
        """
        if not sensor_ids:
            raise ValueError("sensor_ids não pode ser vazio.")
        if not 0.0 < lambda_ewma < 1.0:
            raise ValueError(
                f"lambda_ewma deve estar em (0,1), recebido: {lambda_ewma}"
            )
        if initial_variance <= 0:
            raise ValueError(
                f"initial_variance deve ser positivo, recebido: {initial_variance}"
            )

        self.sensor_ids: list[str] = list(sensor_ids)
        self.lambda_ewma: float = lambda_ewma
        self.initial_variance: float = initial_variance

        # Estado: variância estimada por sensor (inicialização uniforme)
        self.variances: dict[str, float] = {
            sid: initial_variance for sid in sensor_ids
        }

        # Histórico de leituras para diagnóstico
        self._history: dict[str, list[float]] = {sid: [] for sid in sensor_ids}

        logger.info(
            "Fusão de sensores inicializada: %d sensores, λ=%.3f, σ²₀=%.2f",
            len(sensor_ids), lambda_ewma, initial_variance,
        )

    def update_variance(
        self,
        sensor_id: str,
        reading: float,
        current_estimate: float,
    ) -> float:
        """
        Atualiza a variância estimada de um sensor via EWMA.

        Formulação:
            σ²_{new} = λ · σ²_{old} + (1 - λ) · (z - x̂)²

        onde z é a leitura do sensor, x̂ é a estimativa atual, e λ é o
        fator de decaimento exponencial.

        Parâmetros:
            sensor_id: Identificador do sensor.
            reading: Leitura atual do sensor.
            current_estimate: Estimativa fusionada atual (ou melhor estimativa
                disponível do valor real).

        Retorna:
            Nova variância estimada do sensor.

        Levanta:
            KeyError: Se sensor_id não estiver registrado.
        """
        if sensor_id not in self.variances:
            raise KeyError(f"Sensor desconhecido: '{sensor_id}'")

        # Resíduo quadrático (erro de inovação)
        innovation_sq: float = (reading - current_estimate) ** 2

        # Atualização EWMA: média exponencial ponderada do quadrado dos resíduos
        old_var: float = self.variances[sensor_id]
        new_var: float = (
            self.lambda_ewma * old_var
            + (1.0 - self.lambda_ewma) * innovation_sq
        )

        self.variances[sensor_id] = new_var

        logger.debug(
            "Variância atualizada [%s]: %.4f → %.4f (inovação²=%.4f)",
            sensor_id, old_var, new_var, innovation_sq,
        )

        return new_var

    def fuse_readings(
        self,
        readings: dict[str, float],
    ) -> dict[str, object]:
        """
        Realiza fusão Bayesiana de leituras de múltiplos sensores.

        Implementa o estimador BLUE (Best Linear Unbiased Estimator):
            x̂_fused = Σ(w_k · z_k)
            w_k = (1/σ²_k) / Σ(1/σ²_j)
            σ²_fused = 1 / Σ(1/σ²_k)

        Também executa detecção de outliers via teste de Grubbs nos
        valores das leituras atuais.

        Parâmetros:
            readings: Dicionário {sensor_id: leitura} com leituras atuais.
                Não é necessário que todos os sensores reportem em cada ciclo.

        Retorna:
            Dicionário com:
                'fused_estimate' (float): Estimativa fusionada ótima.
                'fused_variance' (float): Variância da estimativa fusionada.
                'weights' (dict[str, float]): Peso atribuído a cada sensor.
                'outlier_flags' (dict[str, bool]): Flag de outlier por sensor.
                'n_sensors' (int): Número de sensores que contribuíram.

        Levanta:
            ValueError: Se readings estiver vazio.
            KeyError: Se algum sensor_id não estiver registrado.
        """
        if not readings:
            raise ValueError("readings não pode ser vazio.")

        # Validar que todos os sensores estão registrados
        unknown = set(readings.keys()) - set(self.sensor_ids)
        if unknown:
            raise KeyError(f"Sensores desconhecidos: {unknown}")

        active_ids: list[str] = list(readings.keys())
        values: np.ndarray = np.array([readings[sid] for sid in active_ids])

        # Detecção de outliers nas leituras atuais
        outlier_mask: np.ndarray = self.grubbs_test(values)
        outlier_flags: dict[str, bool] = {
            sid: bool(outlier_mask[i]) for i, sid in enumerate(active_ids)
        }

        # Pesos por variância inversa (precision weighting)
        precisions: np.ndarray = np.array([
            1.0 / self.variances[sid] for sid in active_ids
        ])
        total_precision: float = precisions.sum()
        weights_array: np.ndarray = precisions / total_precision

        weights: dict[str, float] = {
            sid: float(weights_array[i]) for i, sid in enumerate(active_ids)
        }

        # Estimativa fusionada: média ponderada por precisão
        fused_estimate: float = float(np.dot(weights_array, values))

        # Variância fusionada: inverso da precisão total
        fused_variance: float = 1.0 / total_precision

        # Atualizar variâncias de todos os sensores ativos
        for sid in active_ids:
            self.update_variance(sid, readings[sid], fused_estimate)
            self._history[sid].append(readings[sid])

        # Logging de outliers detectados
        n_outliers: int = sum(outlier_flags.values())
        if n_outliers > 0:
            outlier_sensors = [
                sid for sid, flag in outlier_flags.items() if flag
            ]
            logger.warning(
                "Outliers detectados em %d sensor(es): %s",
                n_outliers, outlier_sensors,
            )

        logger.debug(
            "Fusão realizada: x̂=%.3f, σ²=%.4f, n_sensores=%d, outliers=%d",
            fused_estimate, fused_variance, len(active_ids), n_outliers,
        )

        return {
            "fused_estimate": fused_estimate,
            "fused_variance": fused_variance,
            "weights": weights,
            "outlier_flags": outlier_flags,
            "n_sensors": len(active_ids),
        }

    @staticmethod
    def grubbs_test(
        values: np.ndarray,
        alpha: float = 0.05,
    ) -> np.ndarray:
        """
        Teste de Grubbs para detecção de outliers em um conjunto de valores.

        O teste de Grubbs detecta um único outlier em um conjunto de dados
        assumido como normalmente distribuído. A estatística do teste é:

            G = max|x_i - x̄| / s

        onde x̄ é a média amostral e s é o desvio padrão amostral.

        O valor crítico é derivado da distribuição t-Student:

            G_crit = ((N-1)/√N) · √(t²_{α/(2N), N-2} / (N-2+t²_{α/(2N), N-2}))

        Se G > G_crit, o ponto com maior desvio é classificado como outlier.

        Parâmetros:
            values: Array de valores numéricos para teste.
            alpha: Nível de significância (probabilidade de falso positivo).
                Padrão: 0.05 (confiança de 95%).

        Retorna:
            np.ndarray booleano com True para valores classificados como outlier.

        Notas:
            - Para N < 3, retorna array de False (teste não aplicável).
            - A implementação atual detecta no máximo 1 outlier por chamada.
              Para detecção iterativa, aplique repetidamente.
        """
        values_arr: np.ndarray = np.asarray(values, dtype=np.float64)
        n: int = len(values_arr)
        outlier_mask: np.ndarray = np.zeros(n, dtype=bool)

        # Teste de Grubbs requer pelo menos 3 observações
        if n < 3:
            return outlier_mask

        mean_val: float = float(np.mean(values_arr))
        std_val: float = float(np.std(values_arr, ddof=1))

        # Se desvio padrão é zero, não há outliers
        if std_val < 1e-12:
            return outlier_mask

        # Estatística de Grubbs: G = max|x_i - x̄| / s
        deviations: np.ndarray = np.abs(values_arr - mean_val)
        max_idx: int = int(np.argmax(deviations))
        g_stat: float = float(deviations[max_idx] / std_val)

        # Valor crítico usando distribuição t-Student
        # t² com α/(2N) e (N-2) graus de liberdade
        t_alpha: float = stats.t.ppf(1.0 - alpha / (2.0 * n), n - 2)
        t_sq: float = t_alpha ** 2

        g_critical: float = ((n - 1) / np.sqrt(n)) * np.sqrt(
            t_sq / (n - 2 + t_sq)
        )

        if g_stat > g_critical:
            outlier_mask[max_idx] = True
            logger.debug(
                "Grubbs: outlier detectado no índice %d "
                "(G=%.3f > G_crit=%.3f, valor=%.3f)",
                max_idx, g_stat, g_critical, values_arr[max_idx],
            )

        return outlier_mask

    def reset(self) -> None:
        """Reinicializa todas as variâncias e limpa o histórico."""
        self.variances = {sid: self.initial_variance for sid in self.sensor_ids}
        self._history = {sid: [] for sid in self.sensor_ids}
        logger.info("Estado de fusão reinicializado.")


def reconciliar_dados_bayesiano(
    df: "pd.DataFrame",
    janela_tempo_segundos: float = 5.0,
) -> "pd.DataFrame":
    """
    Reconciliação Bayesiana de dados multi-sensor (drop-in replacement).

    Substitui a reconciliação por média aritmética simples por fusão
    Bayesiana com ponderação por variância inversa, resultando em estimativas
    mais robustas e com menor variância.

    Algoritmo:
        1. Identifica colunas numéricas de sensor no DataFrame
        2. Para cada janela temporal (agrupamento por timestamps):
            a. Calcula fusão Bayesiana das leituras
            b. Atualiza variâncias online via EWMA
            c. Flaggeia outliers via teste de Grubbs
        3. Retorna DataFrame com coluna 'valor_fusionado' e metadados

    Parâmetros:
        df: DataFrame pandas com colunas de sensores e opcionalmente
            uma coluna 'timestamp' ou índice temporal.
        janela_tempo_segundos: Tamanho da janela temporal para agrupamento
            de leituras simultâneas. Padrão: 5.0 segundos.

    Retorna:
        DataFrame com colunas adicionais:
            - 'valor_fusionado': Estimativa Bayesiana ótima
            - 'variancia_fusionada': Variância da estimativa
            - 'n_sensores_ativos': Sensores que contribuíram
            - 'tem_outlier': Se algum outlier foi detectado na janela

    Levanta:
        ImportError: Se pandas não estiver disponível.
        ValueError: Se não houver colunas numéricas de sensor.
    """
    if not _HAS_PANDAS:
        raise ImportError(
            "pandas é necessário para reconciliar_dados_bayesiano. "
            "Instale com: pip install pandas"
        )

    # Identificar colunas de sensores (numéricas, excluindo metadados comuns)
    metadata_cols: set[str] = {
        "timestamp", "time", "datetime", "date", "id", "user_id",
        "device_id", "session_id",
    }
    sensor_cols: list[str] = [
        col for col in df.select_dtypes(include=[np.number]).columns
        if col.lower() not in metadata_cols
    ]

    if not sensor_cols:
        raise ValueError(
            "Nenhuma coluna numérica de sensor encontrada no DataFrame. "
            f"Colunas disponíveis: {list(df.columns)}"
        )

    logger.info(
        "Reconciliação Bayesiana: %d sensores detectados: %s",
        len(sensor_cols), sensor_cols,
    )

    # Inicializar fusão adaptativa
    fusion = AdaptiveSensorFusion(
        sensor_ids=sensor_cols,
        lambda_ewma=0.95,
        initial_variance=4.0,
    )

    # Processar cada linha (ou janela temporal)
    fused_values: list[float] = []
    fused_variances: list[float] = []
    n_sensors_list: list[int] = []
    outlier_list: list[bool] = []

    for idx in range(len(df)):
        row = df.iloc[idx]

        # Construir dicionário de leituras (excluir NaN)
        readings: dict[str, float] = {}
        for col in sensor_cols:
            val = row[col]
            if not (pd.isna(val) if _HAS_PANDAS else np.isnan(val)):
                readings[col] = float(val)

        if len(readings) >= 1:
            if len(readings) == 1:
                # Sensor único: usar diretamente
                single_val = next(iter(readings.values()))
                fused_values.append(single_val)
                fused_variances.append(
                    fusion.variances[next(iter(readings.keys()))]
                )
                n_sensors_list.append(1)
                outlier_list.append(False)
            else:
                result = fusion.fuse_readings(readings)
                fused_values.append(result["fused_estimate"])
                fused_variances.append(result["fused_variance"])
                n_sensors_list.append(result["n_sensors"])
                outlier_list.append(any(result["outlier_flags"].values()))
        else:
            # Sem leituras válidas
            fused_values.append(np.nan)
            fused_variances.append(np.nan)
            n_sensors_list.append(0)
            outlier_list.append(False)

    # Criar DataFrame de resultado
    result_df = df.copy()
    result_df["valor_fusionado"] = fused_values
    result_df["variancia_fusionada"] = fused_variances
    result_df["n_sensores_ativos"] = n_sensors_list
    result_df["tem_outlier"] = outlier_list

    logger.info(
        "Reconciliação concluída: %d registros processados, "
        "%.1f%% com outliers",
        len(result_df),
        100 * sum(outlier_list) / max(len(outlier_list), 1),
    )

    return result_df


if __name__ == "__main__":
    # Configuração de logging para demonstração
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    print("=" * 70)
    print("DEMONSTRAÇÃO: Fusão Bayesiana de Sensores")
    print("=" * 70)

    # --- 1. Fusão Adaptativa Básica ---
    print("\n--- 1. Fusão de 3 Sensores de Frequência Cardíaca ---")
    fusion = AdaptiveSensorFusion(
        sensor_ids=["wrist_ppg", "chest_ecg", "finger_spo2"],
        lambda_ewma=0.95,
        initial_variance=4.0,
    )

    # Simular 20 ciclos de leitura
    rng = np.random.default_rng(42)
    true_hr = 72.0
    print(f"   HR verdadeiro: {true_hr} BPM\n")

    for cycle in range(20):
        # Simular sensores com diferentes níveis de ruído
        readings = {
            "wrist_ppg": true_hr + rng.normal(0, 2.5),    # σ=2.5
            "chest_ecg": true_hr + rng.normal(0, 1.0),    # σ=1.0 (mais preciso)
            "finger_spo2": true_hr + rng.normal(0, 3.0),  # σ=3.0
        }

        # Injetar outlier no ciclo 10
        if cycle == 10:
            readings["wrist_ppg"] += 15.0  # Outlier!

        result = fusion.fuse_readings(readings)

        if cycle % 5 == 0 or cycle == 10:
            print(f"   Ciclo {cycle:2d}: x̂={result['fused_estimate']:.2f} BPM, "
                  f"σ²={result['fused_variance']:.4f}")
            weights_str = ", ".join(
                f"{k}={v:.3f}" for k, v in result["weights"].items()
            )
            print(f"            Pesos: {weights_str}")
            if any(result["outlier_flags"].values()):
                outliers = [k for k, v in result["outlier_flags"].items() if v]
                print(f"            ⚠ Outliers: {outliers}")

    # Variâncias finais aprendidas
    print(f"\n   Variâncias finais aprendidas:")
    for sid, var in fusion.variances.items():
        print(f"     {sid}: σ²={var:.4f} (σ={np.sqrt(var):.3f})")

    # --- 2. Teste de Grubbs ---
    print("\n--- 2. Teste de Grubbs ---")
    normal_data = np.array([71.2, 72.1, 71.8, 72.5, 71.9, 72.0])
    outlier_data = np.array([71.2, 72.1, 71.8, 95.0, 71.9, 72.0])

    mask_normal = AdaptiveSensorFusion.grubbs_test(normal_data)
    mask_outlier = AdaptiveSensorFusion.grubbs_test(outlier_data)

    print(f"   Dados normais:  {normal_data}")
    print(f"   Outliers:       {mask_normal} → Nenhum detectado")
    print(f"   Dados c/ outlier: {outlier_data}")
    print(f"   Outliers:         {mask_outlier} → Índice {np.where(mask_outlier)[0]}")

    # --- 3. Reconciliação Bayesiana de DataFrame ---
    if _HAS_PANDAS:
        print("\n--- 3. Reconciliação Bayesiana (DataFrame) ---")
        df_test = pd.DataFrame({
            "sensor_a": [72.1, 71.5, 73.2, 71.8, 95.0],
            "sensor_b": [71.8, 72.0, 72.5, 71.2, 72.1],
            "sensor_c": [72.3, 71.7, 72.8, 71.5, 71.9],
        })
        print(f"   DataFrame de entrada:\n{df_test.to_string(index=True)}\n")

        df_reconciled = reconciliar_dados_bayesiano(df_test)
        print(f"   DataFrame reconciliado:")
        print(f"   {df_reconciled[['valor_fusionado', 'variancia_fusionada', 'tem_outlier']].to_string(index=True)}")
    else:
        print("\n--- 3. Reconciliação Bayesiana (SKIPPED — pandas não instalado) ---")

    print("\n" + "=" * 70)
    print("Demonstração concluída com sucesso.")
    print("=" * 70)
