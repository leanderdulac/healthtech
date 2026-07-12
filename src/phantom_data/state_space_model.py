"""
state_space_model.py — Modelos de Espaço de Estados com Filtros de Kalman

Este módulo implementa filtros de Kalman estendido (EKF) e unscented (UKF)
para inferência de estados fisiológicos latentes ("phantom data") a partir
de leituras de dispositivos vestíveis.

Modelos incluídos:
    - ExtendedKalmanFilter: Filtro de Kalman Estendido para sistemas não-lineares
    - UnscentedKalmanFilter: Filtro de Kalman Unscented com pontos sigma de Van der Merwe
    - PhysiologicalTransitionModel: Dinâmica de Ornstein-Uhlenbeck para estados fisiológicos
    - WearableObservationModel: Mapeamento de estados latentes para observações de sensores

Dependências:
    numpy, scipy
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

import numpy as np
from scipy import linalg

logger = logging.getLogger(__name__)


class ExtendedKalmanFilter:
    """
    Filtro de Kalman Estendido (EKF) para sistemas não-lineares.

    O EKF lineariza as funções de transição e observação através de seus
    Jacobianos, permitindo a aplicação do framework de Kalman a dinâmicas
    não-lineares.

    Equações fundamentais:
        Predição:
            x̂⁻ = f(x̂⁺)
            P⁻ = F · P⁺ · Fᵀ + Q

        Atualização:
            K = P⁻ · Hᵀ · (H · P⁻ · Hᵀ + R)⁻¹
            x̂⁺ = x̂⁻ + K · (z - h(x̂⁻))
            P⁺ = (I - K · H) · P⁻

    Onde:
        x̂ = vetor de estado estimado
        P = matriz de covariância do estado
        Q = covariância do ruído do processo
        R = covariância do ruído de medição
        F = Jacobiano da função de transição
        H = Jacobiano da função de observação
        K = ganho de Kalman
        z = vetor de observação

    Attributes:
        dim_x: Dimensão do vetor de estado.
        dim_z: Dimensão do vetor de observação.
        dt: Intervalo temporal entre predições.
        x: Vetor de estado atual (dim_x,).
        P: Matriz de covariância do estado (dim_x, dim_x).
        Q: Matriz de covariância do ruído do processo (dim_x, dim_x).
        R: Matriz de covariância do ruído de medição (dim_z, dim_z).
    """

    def __init__(self, dim_x: int, dim_z: int, dt: float = 1.0) -> None:
        """
        Inicializa o Filtro de Kalman Estendido.

        Args:
            dim_x: Dimensão do espaço de estados (número de variáveis latentes).
            dim_z: Dimensão do espaço de observações (número de sensores).
            dt: Passo temporal entre atualizações consecutivas (segundos).

        Raises:
            ValueError: Se dim_x ou dim_z forem menores que 1, ou dt ≤ 0.
        """
        if dim_x < 1:
            raise ValueError(f"dim_x deve ser ≥ 1, recebido: {dim_x}")
        if dim_z < 1:
            raise ValueError(f"dim_z deve ser ≥ 1, recebido: {dim_z}")
        if dt <= 0:
            raise ValueError(f"dt deve ser > 0, recebido: {dt}")

        self.dim_x: int = dim_x
        self.dim_z: int = dim_z
        self.dt: float = dt

        # Vetor de estado — inicializado em zero
        self.x: np.ndarray = np.zeros(dim_x)

        # Covariância do estado — identidade (incerteza inicial unitária)
        self.P: np.ndarray = np.eye(dim_x)

        # Covariância do ruído do processo
        self.Q: np.ndarray = np.eye(dim_x) * 0.01

        # Covariância do ruído de medição
        self.R: np.ndarray = np.eye(dim_z) * 0.1

        # Estado predito (armazenado entre predict e update)
        self._x_pred: np.ndarray = np.zeros(dim_x)
        self._P_pred: np.ndarray = np.eye(dim_x)

        logger.info(
            "EKF inicializado: dim_x=%d, dim_z=%d, dt=%.3f",
            dim_x, dim_z, dt,
        )

    def predict(
        self,
        f_func: Callable[[np.ndarray], np.ndarray],
        F_jacobian: Callable[[np.ndarray], np.ndarray],
    ) -> None:
        """
        Etapa de predição do EKF.

        Propaga o estado e a covariância através do modelo de transição:
            x̂⁻ = f(x̂⁺)
            P⁻ = F · P⁺ · Fᵀ + Q

        Onde F = ∂f/∂x é o Jacobiano da função de transição avaliado
        no estado atual.

        Args:
            f_func: Função de transição de estado f(x) → x_pred.
            F_jacobian: Função que retorna o Jacobiano ∂f/∂x avaliado em x.
        """
        try:
            F = F_jacobian(self.x)
            self._x_pred = f_func(self.x)
            self._P_pred = F @ self.P @ F.T + self.Q

            # Forçar simetria numérica da covariância predita
            self._P_pred = 0.5 * (self._P_pred + self._P_pred.T)

            logger.debug(
                "EKF predict: x_pred=%s, trace(P_pred)=%.4f",
                self._x_pred, np.trace(self._P_pred),
            )
        except Exception as e:
            logger.error("Erro na etapa de predição do EKF: %s", e)
            raise

    def update(
        self,
        z: np.ndarray,
        h_func: Callable[[np.ndarray], np.ndarray],
        H_jacobian: Callable[[np.ndarray], np.ndarray],
    ) -> None:
        """
        Etapa de atualização (correção) do EKF.

        Incorpora a observação z para corrigir o estado predito:
            Inovação: ỹ = z - h(x̂⁻)
            Covariância da inovação: S = H · P⁻ · Hᵀ + R
            Ganho de Kalman: K = P⁻ · Hᵀ · S⁻¹
            Estado atualizado: x̂⁺ = x̂⁻ + K · ỹ
            Covariância atualizada: P⁺ = (I - K · H) · P⁻

        Para estabilidade numérica, utiliza-se a forma de Joseph:
            P⁺ = (I - K·H) · P⁻ · (I - K·H)ᵀ + K · R · Kᵀ

        Args:
            z: Vetor de observação (dim_z,).
            h_func: Função de observação h(x) → z_pred.
            H_jacobian: Função que retorna o Jacobiano ∂h/∂x avaliado em x.

        Raises:
            ValueError: Se a dimensão de z não corresponder a dim_z.
        """
        z = np.asarray(z, dtype=float)
        if z.shape[0] != self.dim_z:
            raise ValueError(
                f"Dimensão de z ({z.shape[0]}) não corresponde a dim_z ({self.dim_z})"
            )

        try:
            H = H_jacobian(self._x_pred)
            z_pred = h_func(self._x_pred)

            # Inovação (resíduo de medição)
            y = z - z_pred

            # Covariância da inovação
            S = H @ self._P_pred @ H.T + self.R

            # Ganho de Kalman — resolve via sistema linear para estabilidade
            try:
                K = self._P_pred @ H.T @ np.linalg.inv(S)
            except np.linalg.LinAlgError:
                logger.warning(
                    "Inversão de S falhou; usando pseudo-inversa para estabilidade."
                )
                K = self._P_pred @ H.T @ np.linalg.pinv(S)

            # Atualização do estado
            self.x = self._x_pred + K @ y

            # Atualização da covariância — forma de Joseph para estabilidade
            I_KH = np.eye(self.dim_x) - K @ H
            self.P = I_KH @ self._P_pred @ I_KH.T + K @ self.R @ K.T

            # Forçar simetria
            self.P = 0.5 * (self.P + self.P.T)

            logger.debug(
                "EKF update: inovação=%s, trace(P)=%.4f",
                y, np.trace(self.P),
            )
        except Exception as e:
            logger.error("Erro na etapa de atualização do EKF: %s", e)
            raise

    def get_state(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Retorna o estado estimado atual e a matriz de covariância.

        Returns:
            Tupla (x, P) onde:
                x: Cópia do vetor de estado estimado (dim_x,).
                P: Cópia da matriz de covariância (dim_x, dim_x).
        """
        return self.x.copy(), self.P.copy()


class UnscentedKalmanFilter:
    """
    Filtro de Kalman Unscented (UKF) com pontos sigma de Van der Merwe.

    O UKF utiliza uma transformação determinística (pontos sigma) para
    capturar a média e a covariância de distribuições propagadas por
    funções não-lineares, sem necessidade de Jacobianos.

    Algoritmo de geração de pontos sigma (Van der Merwe):
        λ = α² · (n + κ) - n

        Pontos sigma (2n+1 pontos):
            χ₀ = x̄
            χᵢ = x̄ + (√((n+λ)·P))ᵢ    para i = 1..n
            χᵢ = x̄ - (√((n+λ)·P))ᵢ₋ₙ  para i = n+1..2n

        Pesos para a média:
            Wₘ⁰ = λ / (n + λ)
            Wₘⁱ = 1 / (2·(n + λ))   para i = 1..2n

        Pesos para a covariância:
            Wc⁰ = λ / (n + λ) + (1 - α² + β)
            Wcⁱ = 1 / (2·(n + λ))   para i = 1..2n

    Parâmetros padrão:
        α = 0.001 (controla a dispersão dos pontos sigma)
        β = 2 (ótimo para distribuições Gaussianas)
        κ = 0

    Attributes:
        dim_x: Dimensão do vetor de estado.
        dim_z: Dimensão do vetor de observação.
        alpha, beta, kappa: Parâmetros de escalonamento.
        x: Vetor de estado atual.
        P: Matriz de covariância do estado.
        Q: Covariância do ruído do processo.
        R: Covariância do ruído de medição.
    """

    def __init__(
        self,
        dim_x: int,
        dim_z: int,
        dt: float = 1.0,
        alpha: float = 0.001,
        beta: float = 2.0,
        kappa: float = 0.0,
    ) -> None:
        """
        Inicializa o Filtro de Kalman Unscented.

        Args:
            dim_x: Dimensão do espaço de estados.
            dim_z: Dimensão do espaço de observações.
            dt: Passo temporal entre atualizações.
            alpha: Parâmetro de dispersão dos pontos sigma (0 < α ≤ 1).
            beta: Incorpora conhecimento prévio da distribuição (β=2 para Gaussiana).
            kappa: Parâmetro de escalonamento secundário (tipicamente 0 ou 3-n).

        Raises:
            ValueError: Se parâmetros estiverem fora dos intervalos válidos.
        """
        if dim_x < 1:
            raise ValueError(f"dim_x deve ser ≥ 1, recebido: {dim_x}")
        if dim_z < 1:
            raise ValueError(f"dim_z deve ser ≥ 1, recebido: {dim_z}")
        if dt <= 0:
            raise ValueError(f"dt deve ser > 0, recebido: {dt}")
        if alpha <= 0 or alpha > 1:
            raise ValueError(f"alpha deve estar em (0, 1], recebido: {alpha}")

        self.dim_x: int = dim_x
        self.dim_z: int = dim_z
        self.dt: float = dt
        self.alpha: float = alpha
        self.beta: float = beta
        self.kappa: float = kappa

        # Número de pontos sigma
        self.n_sigma: int = 2 * dim_x + 1

        # Parâmetro de escalonamento composto
        # λ = α²·(n + κ) - n
        self.lambda_: float = alpha ** 2 * (dim_x + kappa) - dim_x

        # Inicialização dos pesos
        self.W_m: np.ndarray = np.zeros(self.n_sigma)
        self.W_c: np.ndarray = np.zeros(self.n_sigma)
        self._compute_weights()

        # Estado e covariância
        self.x: np.ndarray = np.zeros(dim_x)
        self.P: np.ndarray = np.eye(dim_x)
        self.Q: np.ndarray = np.eye(dim_x) * 0.01
        self.R: np.ndarray = np.eye(dim_z) * 0.1

        # Estados preditos (armazenados entre predict e update)
        self._x_pred: np.ndarray = np.zeros(dim_x)
        self._P_pred: np.ndarray = np.eye(dim_x)
        self._sigma_points_pred: np.ndarray = np.zeros((self.n_sigma, dim_x))

        logger.info(
            "UKF inicializado: dim_x=%d, dim_z=%d, α=%.4f, β=%.1f, κ=%.1f",
            dim_x, dim_z, alpha, beta, kappa,
        )

    def _compute_weights(self) -> None:
        """
        Calcula os pesos para média e covariância dos pontos sigma.

        Fórmulas:
            Wₘ⁰ = λ / (n + λ)
            Wc⁰ = λ / (n + λ) + (1 - α² + β)
            Wₘⁱ = Wcⁱ = 1 / (2·(n + λ))   para i = 1..2n
        """
        n = self.dim_x
        lam = self.lambda_

        self.W_m[0] = lam / (n + lam)
        self.W_c[0] = lam / (n + lam) + (1.0 - self.alpha ** 2 + self.beta)

        weight = 1.0 / (2.0 * (n + lam))
        self.W_m[1:] = weight
        self.W_c[1:] = weight

        logger.debug(
            "Pesos UKF: W_m[0]=%.6f, W_c[0]=%.6f, W[i]=%.6f",
            self.W_m[0], self.W_c[0], weight,
        )

    def _compute_sigma_points(self) -> np.ndarray:
        """
        Gera 2n+1 pontos sigma a partir do estado e covariância atuais.

        Utiliza decomposição de Cholesky da matriz (n+λ)·P para garantir
        que os pontos sigma estejam corretamente escalonados.

        Fórmula:
            L = cholesky((n + λ) · P)
            χ₀ = x̄
            χᵢ = x̄ + Lᵢ      para i = 1..n
            χᵢ₊ₙ = x̄ - Lᵢ    para i = 1..n

        Returns:
            Matriz de pontos sigma (2n+1, dim_x).

        Raises:
            np.linalg.LinAlgError: Se P não for positiva definida.
        """
        n = self.dim_x
        sigma_points = np.zeros((self.n_sigma, n))

        # Escalonar a covariância
        scaled_P = (n + self.lambda_) * self.P

        # Forçar simetria antes da decomposição
        scaled_P = 0.5 * (scaled_P + scaled_P.T)

        # Adicionar regularização mínima para estabilidade numérica
        scaled_P += np.eye(n) * 1e-10

        try:
            L = linalg.cholesky(scaled_P, lower=True)
        except linalg.LinAlgError:
            logger.warning(
                "Cholesky falhou; tentando com eigenvalue floor para "
                "garantir definição positiva."
            )
            eigvals, eigvecs = np.linalg.eigh(scaled_P)
            eigvals = np.maximum(eigvals, 1e-8)
            scaled_P = eigvecs @ np.diag(eigvals) @ eigvecs.T
            L = linalg.cholesky(scaled_P, lower=True)

        # Ponto central
        sigma_points[0] = self.x

        # Pontos deslocados
        for i in range(n):
            sigma_points[i + 1] = self.x + L[:, i]
            sigma_points[n + i + 1] = self.x - L[:, i]

        return sigma_points

    def predict(self, f_func: Callable[[np.ndarray], np.ndarray]) -> None:
        """
        Etapa de predição do UKF via transformação unscented.

        Procedimento:
            1. Gera pontos sigma χ a partir de (x, P)
            2. Propaga cada ponto: χ*ᵢ = f(χᵢ)
            3. Calcula média predita: x̂⁻ = Σ Wₘⁱ · χ*ᵢ
            4. Calcula covariância predita:
               P⁻ = Σ Wcⁱ · (χ*ᵢ - x̂⁻)(χ*ᵢ - x̂⁻)ᵀ + Q

        Args:
            f_func: Função de transição de estado f(x) → x_pred.
        """
        try:
            sigma_points = self._compute_sigma_points()

            # Propagar pontos sigma
            sigma_points_pred = np.zeros_like(sigma_points)
            for i in range(self.n_sigma):
                sigma_points_pred[i] = f_func(sigma_points[i])

            # Média predita ponderada
            self._x_pred = np.zeros(self.dim_x)
            for i in range(self.n_sigma):
                self._x_pred += self.W_m[i] * sigma_points_pred[i]

            # Covariância predita ponderada
            self._P_pred = np.zeros((self.dim_x, self.dim_x))
            for i in range(self.n_sigma):
                diff = sigma_points_pred[i] - self._x_pred
                self._P_pred += self.W_c[i] * np.outer(diff, diff)
            self._P_pred += self.Q

            # Forçar simetria
            self._P_pred = 0.5 * (self._P_pred + self._P_pred.T)

            # Salvar pontos sigma propagados para uso na atualização
            self._sigma_points_pred = sigma_points_pred

            logger.debug(
                "UKF predict: x_pred=%s, trace(P_pred)=%.4f",
                self._x_pred, np.trace(self._P_pred),
            )
        except Exception as e:
            logger.error("Erro na predição do UKF: %s", e)
            raise

    def update(
        self,
        z: np.ndarray,
        h_func: Callable[[np.ndarray], np.ndarray],
    ) -> None:
        """
        Etapa de atualização do UKF via transformação unscented.

        Procedimento:
            1. Transforma pontos sigma preditos pelo modelo de observação:
               Zᵢ = h(χ*ᵢ)
            2. Calcula média da observação predita:
               ẑ = Σ Wₘⁱ · Zᵢ
            3. Covariância da inovação:
               S = Σ Wcⁱ · (Zᵢ - ẑ)(Zᵢ - ẑ)ᵀ + R
            4. Covariância cruzada estado-observação:
               Pxz = Σ Wcⁱ · (χ*ᵢ - x̂⁻)(Zᵢ - ẑ)ᵀ
            5. Ganho de Kalman: K = Pxz · S⁻¹
            6. Atualização: x̂⁺ = x̂⁻ + K·(z - ẑ)
            7. P⁺ = P⁻ - K · S · Kᵀ

        Args:
            z: Vetor de observação (dim_z,).
            h_func: Função de observação h(x) → z_pred.

        Raises:
            ValueError: Se a dimensão de z não corresponder a dim_z.
        """
        z = np.asarray(z, dtype=float)
        if z.shape[0] != self.dim_z:
            raise ValueError(
                f"Dimensão de z ({z.shape[0]}) não corresponde a dim_z ({self.dim_z})"
            )

        try:
            # Transformar pontos sigma preditos pelo modelo de observação
            sigma_z = np.zeros((self.n_sigma, self.dim_z))
            for i in range(self.n_sigma):
                sigma_z[i] = h_func(self._sigma_points_pred[i])

            # Média da observação predita
            z_pred = np.zeros(self.dim_z)
            for i in range(self.n_sigma):
                z_pred += self.W_m[i] * sigma_z[i]

            # Covariância da inovação S
            S = np.zeros((self.dim_z, self.dim_z))
            for i in range(self.n_sigma):
                dz = sigma_z[i] - z_pred
                S += self.W_c[i] * np.outer(dz, dz)
            S += self.R

            # Covariância cruzada estado-observação Pxz
            Pxz = np.zeros((self.dim_x, self.dim_z))
            for i in range(self.n_sigma):
                dx = self._sigma_points_pred[i] - self._x_pred
                dz = sigma_z[i] - z_pred
                Pxz += self.W_c[i] * np.outer(dx, dz)

            # Ganho de Kalman
            try:
                K = Pxz @ np.linalg.inv(S)
            except np.linalg.LinAlgError:
                logger.warning(
                    "Inversão de S falhou no UKF; usando pseudo-inversa."
                )
                K = Pxz @ np.linalg.pinv(S)

            # Inovação
            y = z - z_pred

            # Atualização do estado e covariância
            self.x = self._x_pred + K @ y
            self.P = self._P_pred - K @ S @ K.T

            # Forçar simetria
            self.P = 0.5 * (self.P + self.P.T)

            logger.debug(
                "UKF update: inovação=%s, trace(P)=%.4f",
                y, np.trace(self.P),
            )
        except Exception as e:
            logger.error("Erro na atualização do UKF: %s", e)
            raise

    def get_state(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Retorna o estado estimado atual e a matriz de covariância.

        Returns:
            Tupla (x, P) onde:
                x: Cópia do vetor de estado estimado (dim_x,).
                P: Cópia da matriz de covariância (dim_x, dim_x).
        """
        return self.x.copy(), self.P.copy()


class PhysiologicalTransitionModel:
    """
    Modelo de transição fisiológica baseado no processo de Ornstein-Uhlenbeck.

    Modela a dinâmica de variáveis fisiológicas latentes como processos
    de reversão à média, capturando a tendência natural do corpo de manter
    homeostase.

    O processo de Ornstein-Uhlenbeck (OU) é descrito pela SDE:
        dx = θ · (μ - x) · dt + σ · dW

    Onde:
        θ (theta) = taxa de reversão à média (quão rápido retorna ao equilíbrio)
        μ (mu) = valor de equilíbrio (set-point fisiológico)
        σ (sigma) = coeficiente de difusão (volatilidade intrínseca)
        dW = incremento de Wiener (ruído Browniano)

    A discretização de Euler fornece:
        x[k+1] = x[k] + θ · (μ - x[k]) · Δt

    Vetor de estado (5 dimensões):
        [0] PAS  — Pressão Arterial Sistólica (mmHg)
        [1] PAD  — Pressão Arterial Diastólica (mmHg)
        [2] SpO2 — Saturação de Oxigênio (%)
        [3] Tono Vagal — Atividade parassimpática (u.a.)
        [4] Glicose — Nível de glicose sanguínea (mg/dL)

    Attributes:
        state_names: Lista dos nomes dos estados.
        dim_x: Dimensão do vetor de estado (5).
        mu: Valores de equilíbrio fisiológico.
        theta: Taxas de reversão à média.
        sigma: Coeficientes de difusão.
    """

    STATE_NAMES: list[str] = [
        "systolic_bp", "diastolic_bp", "spo2", "vagal_tone", "glucose",
    ]

    def __init__(self) -> None:
        """
        Inicializa o modelo de transição com parâmetros fisiológicos padrão.

        Valores de equilíbrio (μ):
            PAS = 120 mmHg, PAD = 80 mmHg, SpO2 = 97%,
            Tono Vagal = 50 u.a., Glicose = 100 mg/dL

        Taxas de reversão (θ):
            Calibradas para refletir a velocidade de regulação homeostática
            de cada variável. Valores maiores indicam regulação mais rápida.

        Coeficientes de difusão (σ):
            Representam a variabilidade intrínseca de cada variável fisiológica.
        """
        self.dim_x: int = 5

        # Valores de equilíbrio (set-points fisiológicos)
        self.mu: np.ndarray = np.array([120.0, 80.0, 97.0, 50.0, 100.0])

        # Taxas de reversão à média
        # PAS e PAD: regulação barorreceptora (~minutos)
        # SpO2: regulação respiratória (~segundos)
        # Tono vagal: modulação autonômica (~segundos)
        # Glicose: regulação insulínica (~dezenas de minutos)
        self.theta: np.ndarray = np.array([0.05, 0.05, 0.1, 0.08, 0.02])

        # Coeficientes de difusão (volatilidade)
        self.sigma: np.ndarray = np.array([2.0, 1.5, 0.5, 3.0, 5.0])

        logger.info(
            "PhysiologicalTransitionModel inicializado: μ=%s, θ=%s",
            self.mu, self.theta,
        )

    def f(self, x: np.ndarray, dt: float) -> np.ndarray:
        """
        Função de transição de estado (discretização de Euler do processo OU).

        Fórmula para cada componente i:
            x_new[i] = x[i] + θ[i] · (μ[i] - x[i]) · Δt

        Essa equação modela a reversão à média: quando x[i] > μ[i],
        o termo (μ[i] - x[i]) é negativo, puxando x de volta ao equilíbrio.

        Args:
            x: Vetor de estado atual (dim_x,).
            dt: Passo temporal (segundos).

        Returns:
            Vetor de estado predito (dim_x,).
        """
        x = np.asarray(x, dtype=float)
        if x.shape[0] != self.dim_x:
            raise ValueError(
                f"Dimensão do estado ({x.shape[0]}) != dim_x ({self.dim_x})"
            )

        x_new = x + self.theta * (self.mu - x) * dt
        return x_new

    def F_jacobian(self, x: np.ndarray, dt: float) -> np.ndarray:
        """
        Jacobiano analítico da função de transição.

        Para o processo OU discretizado:
            f_i(x) = x_i + θ_i · (μ_i - x_i) · Δt

        O Jacobiano é uma matriz diagonal:
            F_ii = ∂f_i/∂x_i = 1 - θ_i · Δt
            F_ij = 0  para i ≠ j (estados independentes neste modelo)

        Args:
            x: Vetor de estado atual (dim_x,) — não utilizado diretamente
                pois o Jacobiano é independente do estado neste modelo linear.
            dt: Passo temporal (segundos).

        Returns:
            Matriz Jacobiana (dim_x, dim_x) — diagonal.
        """
        diag = 1.0 - self.theta * dt
        return np.diag(diag)

    def get_process_noise(self, dt: float) -> np.ndarray:
        """
        Calcula a matriz de covariância do ruído do processo Q para o passo dt.

        Para o processo OU, a variância do ruído discretizado é:
            Q_ii = σ_i² · (1 - exp(-2·θ_i·Δt)) / (2·θ_i)

        Aproximação para Δt pequeno:
            Q_ii ≈ σ_i² · Δt

        Args:
            dt: Passo temporal (segundos).

        Returns:
            Matriz Q (dim_x, dim_x) — diagonal.
        """
        # Variância exata do processo OU discretizado
        q_diag = np.zeros(self.dim_x)
        for i in range(self.dim_x):
            if self.theta[i] > 1e-10:
                q_diag[i] = (
                    self.sigma[i] ** 2
                    * (1.0 - np.exp(-2.0 * self.theta[i] * dt))
                    / (2.0 * self.theta[i])
                )
            else:
                # Para θ → 0, aproximação linear
                q_diag[i] = self.sigma[i] ** 2 * dt

        return np.diag(q_diag)


class WearableObservationModel:
    """
    Modelo de observação para dispositivos vestíveis.

    Mapeia os estados fisiológicos latentes (não observáveis diretamente)
    para as medições dos sensores vestíveis.

    Vetor de observação (4 dimensões):
        [0] Frequência Cardíaca (FC) — batimentos por minuto
        [1] HRV RMSSD — variabilidade da frequência cardíaca (ms)
        [2] Temperatura cutânea — graus Celsius
        [3] Nível de atividade — unidade arbitrária (exógena)

    Relações fisiológicas (modelo linearizado):
        FC ≈ 60 + 0.3·(PAS-120) - 0.2·(VagalTone-50) + 0.1·(Glicose-100)
            → Reflexo barorreceptor: ↑PAS → ↑FC (resposta compensatória)
            → Tono vagal: ↑vagal → ↓FC (predominância parassimpática)
            → Glicose: ↑glicose → ↑FC (resposta simpática metabólica)

        HRV_RMSSD ≈ 40 + 0.8·(VagalTone-50) - 0.15·(PAS-120)
            → Tono vagal: ↑vagal → ↑HRV (maior modulação parassimpática)
            → PAS: ↑PAS → ↓HRV (estresse cardiovascular)

        Temp_cutânea ≈ 33 + 0.01·(SpO2-97) + 0.005·(VagalTone-50)
            → SpO2: ↑SpO2 → ↑temperatura (melhor perfusão periférica)
            → Vagal: ↑vagal → ↑temperatura (vasodilatação periférica)

        Atividade ≈ 0.0 (variável exógena, pass-through)
            → Não modelada; medida diretamente pelo acelerômetro

    Attributes:
        dim_z: Dimensão do vetor de observação (4).
        dim_x: Dimensão do vetor de estado esperado (5).
        observation_names: Nomes das observações.
    """

    OBSERVATION_NAMES: list[str] = [
        "heart_rate", "hrv_rmssd", "skin_temp", "activity_level",
    ]

    def __init__(self) -> None:
        """
        Inicializa o modelo de observação com os baselines fisiológicos.

        Baselines (valores nominais quando estados estão no equilíbrio):
            FC = 60 bpm, HRV RMSSD = 40 ms, Temp = 33°C, Atividade = 0
        """
        self.dim_z: int = 4
        self.dim_x: int = 5

        # Baselines das observações
        self.hr_baseline: float = 60.0
        self.hrv_baseline: float = 40.0
        self.temp_baseline: float = 33.0
        self.activity_baseline: float = 0.0

        # Equilíbrios dos estados (para cálculo dos desvios)
        self.state_eq: np.ndarray = np.array([120.0, 80.0, 97.0, 50.0, 100.0])

        logger.info("WearableObservationModel inicializado.")

    def h(self, x: np.ndarray) -> np.ndarray:
        """
        Função de observação: mapeia estados latentes para medições dos sensores.

        Fórmulas:
            z[0] = FC = 60 + 0.3·(x[0]-120) - 0.2·(x[3]-50) + 0.1·(x[4]-100)
            z[1] = HRV = 40 + 0.8·(x[3]-50) - 0.15·(x[0]-120)
            z[2] = Temp = 33 + 0.01·(x[2]-97) + 0.005·(x[3]-50)
            z[3] = Atividade = 0.0 (pass-through)

        Onde x = [PAS, PAD, SpO2, VagalTone, Glicose]

        Args:
            x: Vetor de estado (5,).

        Returns:
            Vetor de observação predita (4,).
        """
        x = np.asarray(x, dtype=float)
        if x.shape[0] != self.dim_x:
            raise ValueError(
                f"Dimensão do estado ({x.shape[0]}) != dim_x ({self.dim_x})"
            )

        sbp, _dbp, spo2, vagal, glucose = x
        sbp_dev = sbp - 120.0
        vagal_dev = vagal - 50.0
        spo2_dev = spo2 - 97.0
        glucose_dev = glucose - 100.0

        z = np.array([
            self.hr_baseline + 0.3 * sbp_dev - 0.2 * vagal_dev + 0.1 * glucose_dev,
            self.hrv_baseline + 0.8 * vagal_dev - 0.15 * sbp_dev,
            self.temp_baseline + 0.01 * spo2_dev + 0.005 * vagal_dev,
            self.activity_baseline,
        ])

        return z

    def H_jacobian(self, x: np.ndarray) -> np.ndarray:
        """
        Jacobiano analítico da função de observação.

        Como h(x) é linear nos estados, o Jacobiano é constante:

            H = ∂h/∂x = | ∂FC/∂PAS   ∂FC/∂PAD   ∂FC/∂SpO2   ∂FC/∂Vagal   ∂FC/∂Glicose  |
                         | ∂HRV/∂PAS  ∂HRV/∂PAD  ∂HRV/∂SpO2  ∂HRV/∂Vagal  ∂HRV/∂Glicose |
                         | ∂T/∂PAS    ∂T/∂PAD    ∂T/∂SpO2    ∂T/∂Vagal    ∂T/∂Glicose   |
                         | ∂A/∂PAS    ∂A/∂PAD    ∂A/∂SpO2    ∂A/∂Vagal    ∂A/∂Glicose   |

              = |  0.3    0.0   0.0    -0.2    0.1  |
                | -0.15   0.0   0.0     0.8    0.0  |
                |  0.0    0.0   0.01    0.005  0.0  |
                |  0.0    0.0   0.0     0.0    0.0  |

        Args:
            x: Vetor de estado (5,) — não utilizado (Jacobiano constante).

        Returns:
            Matriz Jacobiana (4, 5).
        """
        H = np.array([
            [0.3,   0.0,  0.0,   -0.2,   0.1],    # ∂FC/∂x
            [-0.15, 0.0,  0.0,    0.8,   0.0],    # ∂HRV/∂x
            [0.0,   0.0,  0.01,   0.005, 0.0],    # ∂Temp/∂x
            [0.0,   0.0,  0.0,    0.0,   0.0],    # ∂Atividade/∂x
        ])
        return H

    def get_measurement_noise(self) -> np.ndarray:
        """
        Retorna a matriz de covariância do ruído de medição R.

        As variâncias refletem a precisão típica dos sensores vestíveis:
            FC: σ² = 4.0 (±2 bpm)
            HRV RMSSD: σ² = 25.0 (±5 ms)
            Temperatura: σ² = 0.04 (±0.2°C)
            Atividade: σ² = 1.0 (±1 unidade)

        Returns:
            Matriz R (4, 4) — diagonal.
        """
        return np.diag([4.0, 25.0, 0.04, 1.0])


if __name__ == "__main__":
    # ==========================================================================
    # Demonstração do sistema de espaço de estados com Filtro de Kalman
    # ==========================================================================
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 70)
    print("  DEMONSTRAÇÃO — State-Space Models com Kalman Filters")
    print("=" * 70)

    # Inicializar modelos
    transition = PhysiologicalTransitionModel()
    observation = WearableObservationModel()

    # --- Demonstração EKF ---
    print("\n--- Extended Kalman Filter (EKF) ---")
    ekf = ExtendedKalmanFilter(dim_x=5, dim_z=4, dt=1.0)
    ekf.x = transition.mu.copy()  # Estado inicial = equilíbrio
    ekf.Q = transition.get_process_noise(dt=1.0)
    ekf.R = observation.get_measurement_noise()

    # Simular observações ruidosas
    np.random.seed(42)
    true_state = np.array([125.0, 82.0, 96.5, 45.0, 110.0])
    z_true = observation.h(true_state)
    z_noisy = z_true + np.random.multivariate_normal(
        np.zeros(4), observation.get_measurement_noise(),
    )

    print(f"  Estado verdadeiro:   {true_state}")
    print(f"  Observação ruidosa:  {z_noisy}")

    # Executar predição e atualização
    ekf.predict(
        f_func=lambda x: transition.f(x, dt=1.0),
        F_jacobian=lambda x: transition.F_jacobian(x, dt=1.0),
    )
    ekf.update(z_noisy, observation.h, observation.H_jacobian)

    x_est, P_est = ekf.get_state()
    print(f"  Estado estimado:     {x_est}")
    print(f"  Incertezas (√diag):  {np.sqrt(np.diag(P_est))}")

    # --- Demonstração UKF ---
    print("\n--- Unscented Kalman Filter (UKF) ---")
    ukf = UnscentedKalmanFilter(dim_x=5, dim_z=4, dt=1.0)
    ukf.x = transition.mu.copy()
    ukf.Q = transition.get_process_noise(dt=1.0)
    ukf.R = observation.get_measurement_noise()

    ukf.predict(f_func=lambda x: transition.f(x, dt=1.0))
    ukf.update(z_noisy, observation.h)

    x_est_ukf, P_est_ukf = ukf.get_state()
    print(f"  Estado estimado:     {x_est_ukf}")
    print(f"  Incertezas (√diag):  {np.sqrt(np.diag(P_est_ukf))}")

    # --- Demonstração de convergência ---
    print("\n--- Convergência com múltiplas observações (EKF) ---")
    ekf2 = ExtendedKalmanFilter(dim_x=5, dim_z=4, dt=1.0)
    ekf2.x = transition.mu.copy()
    ekf2.Q = transition.get_process_noise(dt=1.0)
    ekf2.R = observation.get_measurement_noise()

    for step in range(10):
        z_step = observation.h(true_state) + np.random.multivariate_normal(
            np.zeros(4), observation.get_measurement_noise(),
        )
        ekf2.predict(
            f_func=lambda x: transition.f(x, dt=1.0),
            F_jacobian=lambda x: transition.F_jacobian(x, dt=1.0),
        )
        ekf2.update(z_step, observation.h, observation.H_jacobian)

        x_conv, P_conv = ekf2.get_state()
        err = np.linalg.norm(x_conv - true_state)
        print(f"  Passo {step + 1:2d}: erro={err:.3f}, trace(P)={np.trace(P_conv):.4f}")

    print("\n✓ Demonstração concluída com sucesso.")
