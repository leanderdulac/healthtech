"""
Simulador de campos hemodinâmicos 3D — fluxo vascular sintético.
"""

import numpy as np

from src.hemodynamics.models import Grid3D, ScalarField3D, VectorField3D
from src.hemodynamics.operators import create_grid


class VascularFlowSimulator:
    """
    Gera campos de pressão e velocidade para cenários vasculares:
      - normal: fluxo laminar em tubo reto
      - stenosis: estenose (sumidouro / gradiente alto)
      - aneurysm: aneurisma (fonte / divergência positiva)
      - turbulent: bifurcação com vórtices (curl alto)
    """

    SCENARIOS = ("normal", "stenosis", "aneurysm", "turbulent")

    def __init__(self, nx: int = 40, ny: int = 24, nz: int = 24, spacing: float = 0.5):
        self.nx, self.ny, self.nz = nx, ny, nz
        self.spacing = (spacing, spacing, spacing)
        self.grid = create_grid(nx, ny, nz, spacing=self.spacing)

    def simulate(self, scenario: str = "normal") -> tuple:
        if scenario not in self.SCENARIOS:
            raise ValueError(f"Cenário inválido: {scenario}. Use: {self.SCENARIOS}")

        x, y, z = self.grid.x, self.grid.y, self.grid.z
        cx, cy, cz = self.nx * self.spacing[0] / 2, self.ny * self.spacing[1] / 2, self.nz * self.spacing[2] / 2

        dist_yz = np.sqrt((y - cy) ** 2 + (z - cz) ** 2)
        vessel_radius = 4.0
        in_vessel = dist_yz < vessel_radius

        pressure = 120.0 - 0.8 * x + 5.0 * np.exp(-dist_yz ** 2 / 8)
        vx = np.where(in_vessel, 25.0 * (1 - (dist_yz / vessel_radius) ** 2), 0.0)
        vy = np.zeros_like(vx)
        vz = np.zeros_like(vx)

        if scenario == "stenosis":
            stenosis_mask = (x > 12) & (x < 16) & in_vessel
            vx = np.where(stenosis_mask, vx * 2.5, vx)
            pressure = np.where(stenosis_mask, pressure + 35, pressure)
            vx = np.where(stenosis_mask & (dist_yz > vessel_radius * 0.6), vx * 0.3, vx)

        elif scenario == "aneurysm":
            aneurysm_center = (10.0, cy, cz)
            dist_a = np.sqrt(
                (x - aneurysm_center[0]) ** 2
                + (y - aneurysm_center[1]) ** 2
                + (z - aneurysm_center[2]) ** 2
            )
            bulge = dist_a < 3.0
            vx = np.where(bulge, vx * 0.4, vx)
            vy = np.where(bulge, 3.0 * np.sin(2 * np.pi * y / self.ny), vy)
            vz = np.where(bulge, 3.0 * np.cos(2 * np.pi * z / self.nz), vz)
            pressure = np.where(bulge, pressure - 20, pressure)

        elif scenario == "turbulent":
            bifurcation = (x > 14) & (x < 20) & in_vessel
            vy = np.where(bifurcation, 8.0 * np.sin(4 * np.pi * y / self.ny), vy)
            vz = np.where(bifurcation, 8.0 * np.cos(4 * np.pi * z / self.nz), vz)
            vx = np.where(bifurcation, vx * 0.7, vx)

        pressure_field = ScalarField3D(
            values=pressure.astype(np.float64),
            grid=self.grid,
            name="blood_pressure_mmhg",
        )
        velocity_field = VectorField3D(
            fx=vx.astype(np.float64),
            fy=vy.astype(np.float64),
            fz=vz.astype(np.float64),
            grid=self.grid,
            name="blood_velocity_cms",
        )
        return pressure_field, velocity_field