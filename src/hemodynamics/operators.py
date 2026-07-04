"""
Operadores vetoriais: gradiente, divergência e rotacional (curl).

Implementação com diferenças centrais via numpy.gradient em malha 3D.
"""

from typing import Tuple

import numpy as np

from src.hemodynamics.models import Grid3D, ScalarField3D, VectorField3D


def gradient(scalar: ScalarField3D) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    ∇φ = ⟨∂φ/∂x, ∂φ/∂y, ∂φ/∂z⟩

    Retorna o vetor gradiente apontando para a maior subida do campo escalar.
    """
    dx, dy, dz = scalar.grid.spacing
    dphi_dx, dphi_dy, dphi_dz = np.gradient(
        scalar.values, dx, dy, dz, edge_order=2,
    )
    return dphi_dx, dphi_dy, dphi_dz


def gradient_magnitude(scalar: ScalarField3D) -> np.ndarray:
    """|∇φ| — magnitude do gradiente (taxa máxima de variação)."""
    gx, gy, gz = gradient(scalar)
    return np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)


def divergence(vector: VectorField3D) -> np.ndarray:
    """
    ∇·F = ∂Fx/∂x + ∂Fy/∂y + ∂Fz/∂z

    Positivo: fonte (fluxo saindo). Negativo: sumidouro (fluxo entrando).
    """
    dx, dy, dz = vector.grid.spacing
    dfx_dx = np.gradient(vector.fx, dx, axis=0, edge_order=2)
    dfy_dy = np.gradient(vector.fy, dy, axis=1, edge_order=2)
    dfz_dz = np.gradient(vector.fz, dz, axis=2, edge_order=2)
    return dfx_dx + dfy_dy + dfz_dz


def curl(vector: VectorField3D) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    ∇×F = ⟨∂Fz/∂y - ∂Fy/∂z, ∂Fx/∂z - ∂Fz/∂x, ∂Fy/∂x - ∂Fx/∂y⟩

    Regra da mão direita — mede rotação local do campo.
    """
    dx, dy, dz = vector.grid.spacing
    dfx_dx, dfx_dy, dfx_dz = np.gradient(vector.fx, dx, dy, dz, edge_order=2)
    dfy_dx, dfy_dy, dfy_dz = np.gradient(vector.fy, dx, dy, dz, edge_order=2)
    dfz_dx, dfz_dy, dfz_dz = np.gradient(vector.fz, dx, dy, dz, edge_order=2)

    curl_x = dfz_dy - dfy_dz
    curl_y = dfx_dz - dfz_dx
    curl_z = dfy_dx - dfx_dy
    return curl_x, curl_y, curl_z


def curl_magnitude(vector: VectorField3D) -> np.ndarray:
    """|∇×F| — intensidade rotacional."""
    cx, cy, cz = curl(vector)
    return np.sqrt(cx ** 2 + cy ** 2 + cz ** 2)


def create_grid(
    nx: int, ny: int, nz: int,
    spacing: Tuple[float, float, float] = (0.5, 0.5, 0.5),
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Grid3D:
    """Cria malha 3D regular."""
    x = np.linspace(origin[0], origin[0] + (nx - 1) * spacing[0], nx)
    y = np.linspace(origin[1], origin[1] + (ny - 1) * spacing[1], ny)
    z = np.linspace(origin[2], origin[2] + (nz - 1) * spacing[2], nz)
    xx, yy, zz = np.meshgrid(x, y, z, indexing="ij")
    return Grid3D(x=xx, y=yy, z=zz, spacing=spacing)