"""Testes dos operadores vetoriais hemodinâmicos."""

from __future__ import annotations

import numpy as np

from src.hemodynamics.models import ScalarField3D, VectorField3D
from src.hemodynamics.operators import (
    create_grid,
    curl,
    divergence,
    gradient,
    gradient_magnitude,
)


def test_create_grid_shape():
    grid = create_grid(4, 5, 6, spacing=(1.0, 1.0, 1.0))
    assert grid.x.shape == (4, 5, 6)


def test_gradient_of_linear_field():
    grid = create_grid(5, 5, 5, spacing=(1.0, 1.0, 1.0))
    # φ = x  → ∇φ ≈ (1, 0, 0)
    values = grid.x.copy()
    field = ScalarField3D(values=values, grid=grid)
    gx, gy, gz = gradient(field)
    # Interior deve ser ~1 em x
    assert np.allclose(gx[1:-1, 1:-1, 1:-1], 1.0, atol=0.15)
    assert np.allclose(gy[1:-1, 1:-1, 1:-1], 0.0, atol=0.15)
    assert np.allclose(gz[1:-1, 1:-1, 1:-1], 0.0, atol=0.15)
    mag = gradient_magnitude(field)
    assert mag.shape == values.shape


def test_divergence_uniform_flow_near_zero():
    grid = create_grid(6, 6, 6, spacing=(1.0, 1.0, 1.0))
    fx = np.ones_like(grid.x)
    fy = np.zeros_like(grid.y)
    fz = np.zeros_like(grid.z)
    vec = VectorField3D(fx=fx, fy=fy, fz=fz, grid=grid)
    div = divergence(vec)
    assert np.allclose(div[1:-1, 1:-1, 1:-1], 0.0, atol=1e-6)


def test_curl_shape():
    grid = create_grid(4, 4, 4)
    fx = np.zeros_like(grid.x)
    fy = grid.x.copy()  # fluxo com rotação potencial
    fz = np.zeros_like(grid.z)
    vec = VectorField3D(fx=fx, fy=fy, fz=fz, grid=grid)
    cx, cy, cz = curl(vec)
    assert cx.shape == grid.x.shape
