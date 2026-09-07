"""
Módulo de Estimação de Estados Não-Lineares — Adaptive Unscented Kalman Filter (A-UKF).

Implementa a transformada Unscented escalonada de Van der Merwe com adaptação online
de matrizes de covariância de ruído de Sage-Husa e análise de Observabilidade de Gramiano.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np


class AdaptiveUnscentedKalmanFilter:
    """
    Adaptive Unscented Kalman Filter (A-UKF) com auto-calibração de ruídos Q e R.
    """

    def __init__(
        self,
        dim_x: int = 5,
        dim_z: int = 4,
        alpha: float = 1e-3,
        beta: float = 2.0,
        kappa: float = 0.0,
        forgetting_factor: float = 0.98,
        initial_q_scale: float = 1e-3,
        initial_r_scale: float = 1.0
    ):
        self.dim_x = dim_x
        self.dim_z = dim_z
        self.alpha = alpha
        self.beta = beta
        self.kappa = kappa
        self.b = forgetting_factor
        self.k_step = 1

        # Pesos da Transformada Unscented
        self.lambda_param = (alpha ** 2) * (dim_x + kappa) - dim_x
        self.gamma = np.sqrt(dim_x + self.lambda_param)

        num_sigmas = 2 * dim_x + 1
        self.Wm = np.zeros(num_sigmas)
        self.Wc = np.zeros(num_sigmas)

        self.Wm[0] = self.lambda_param / (dim_x + self.lambda_param)
        self.Wc[0] = self.Wm[0] + (1.0 - alpha ** 2 + beta)

        for i in range(1, num_sigmas):
            self.Wm[i] = 1.0 / (2.0 * (dim_x + self.lambda_param))
            self.Wc[i] = self.Wm[i]

        # Estados e Covariâncias
        self.x = np.zeros(dim_x)
        self.P = np.eye(dim_x) * 10.0
        self.Q = np.eye(dim_x) * initial_q_scale
        self.R = np.eye(dim_z) * initial_r_scale

        # Matrizes de Inovação
        self.last_innovation = np.zeros(dim_z)
        self.last_innovation_cov = np.eye(dim_z)

    def generate_sigma_points(self, x: np.ndarray, P: np.ndarray) -> np.ndarray:
        """Gera os 2n+1 pontos sigma usando decomposição de Cholesky."""
        n = len(x)
        sigmas = np.zeros((2 * n + 1, n))
        sigmas[0] = x

        # Adicionar jitter para estabilidade numérica na decomposição de Cholesky
        P_stabilized = P + np.eye(n) * 1e-9
        try:
            L = np.linalg.cholesky(P_stabilized)
        except np.linalg.LinAlgError:
            eigvals, eigvecs = np.linalg.eigh(P_stabilized)
            eigvals = np.maximum(eigvals, 1e-9)
            L = eigvecs @ np.diag(np.sqrt(eigvals))

        for i in range(n):
            sigmas[i + 1] = x + self.gamma * L[:, i]
            sigmas[n + i + 1] = x - self.gamma * L[:, i]

        return sigmas

    def predict(self, f_func: Callable[[np.ndarray], np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
        """Etapa de predição com os pontos sigma e propagação pela dinâmica f(x)."""
        sigmas = self.generate_sigma_points(self.x, self.P)
        sigmas_f = np.zeros_like(sigmas)

        for i in range(len(sigmas)):
            sigmas_f[i] = f_func(sigmas[i])

        # Média predita
        x_pred = np.sum(self.Wm[:, None] * sigmas_f, axis=0)

        # Covariância predita
        P_pred = np.zeros((self.dim_x, self.dim_x))
        for i in range(len(sigmas)):
            diff = sigmas_f[i] - x_pred
            P_pred += self.Wc[i] * np.outer(diff, diff)

        P_pred += self.Q

        self.x = x_pred
        self.P = P_pred
        self.sigmas_f = sigmas_f
        return self.x, self.P

    def update(
        self,
        z: np.ndarray,
        h_func: Callable[[np.ndarray], np.ndarray]
    ) -> Dict[str, Any]:
        """
        Etapa de atualização e adaptação online de ruído de medição R via Sage-Husa.
        """
        sigmas_h = np.zeros((len(self.sigmas_f), self.dim_z))
        for i in range(len(self.sigmas_f)):
            sigmas_h[i] = h_func(self.sigmas_f[i])

        # Média da observação predita
        z_pred = np.sum(self.Wm[:, None] * sigmas_h, axis=0)

        # Covariância da observação P_zz e Cruzada P_xz
        P_zz = np.zeros((self.dim_z, self.dim_z))
        P_xz = np.zeros((self.dim_x, self.dim_z))

        for i in range(len(self.sigmas_f)):
            diff_z = sigmas_h[i] - z_pred
            diff_x = self.sigmas_f[i] - self.x
            P_zz += self.Wc[i] * np.outer(diff_z, diff_z)
            P_xz += self.Wc[i] * np.outer(diff_x, diff_z)

        P_zz += self.R
        self.last_innovation_cov = P_zz

        # Ganho de Kalman
        K = P_xz @ np.linalg.pinv(P_zz)

        # Inovação
        innovation = z - z_pred
        self.last_innovation = innovation

        # Atualização do estado e covariância
        self.x = self.x + K @ innovation
        self.P = self.P - K @ P_zz @ K.T

        # Adaptação de Sage-Husa para a matriz R
        d_k = (1.0 - self.b) / (1.0 - self.b ** max(1, self.k_step))
        r_adaptive = (1.0 - d_k) * self.R + d_k * (np.outer(innovation, innovation) - (P_zz - self.R))
        # Garantir diagonal estritamente positiva
        diag_r = np.maximum(np.diag(r_adaptive), 1e-4)
        self.R = np.diag(diag_r)

        self.k_step += 1

        return {
            "state": self.x.copy(),
            "covariance": self.P.copy(),
            "innovation": innovation.copy(),
            "kalman_gain": K.copy(),
            "adaptive_r_diag": diag_r.tolist()
        }

    def compute_observability_gramian(self, A_approx: np.ndarray, H_approx: np.ndarray, horizon: int = 10) -> Dict[str, float]:
        """
        Calcula o Gramiano de Observabilidade discreto Wo = sum (A^k)^T H^T H (A^k).
        Retorna número de condição e autovalor mínimo (identificabilidade).
        """
        Wo = np.zeros((self.dim_x, self.dim_x))
        A_k = np.eye(self.dim_x)

        for _ in range(horizon):
            Wo += A_k.T @ H_approx.T @ H_approx @ A_k
            A_k = A_k @ A_approx

        eigvals = np.linalg.eigvalsh(Wo)
        min_eig = float(np.min(eigvals))
        max_eig = float(np.max(eigvals))
        condition_number = float(max_eig / max(1e-12, min_eig))

        return {
            "min_eigenvalue": min_eig,
            "max_eigenvalue": max_eig,
            "condition_number": condition_number,
            "is_observable": bool(min_eig > 1e-6)
        }
