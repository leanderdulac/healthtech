"""
Módulo de Hemodinâmica Computacional e Física Cardiovascular.
"""

from src.hemodynamics.models import Grid3D, ScalarField3D, VectorField3D, FlowIrregularity
from src.hemodynamics.operators import VectorCalculus3D
from src.hemodynamics.analyzer import VascularFlowAnalyzer
from src.hemodynamics.simulator import VascularFlowSimulator
from src.hemodynamics.windkessel import (
    Windkessel4EParams,
    Windkessel4ESimulator,
    BaroreflexParams,
)

HemodynamicsAnalyzer = VascularFlowAnalyzer
HemodynamicsSimulator = VascularFlowSimulator

__all__ = [
    "Grid3D",
    "ScalarField3D",
    "VectorField3D",
    "FlowIrregularity",
    "VectorCalculus3D",
    "VascularFlowAnalyzer",
    "VascularFlowSimulator",
    "HemodynamicsAnalyzer",
    "HemodynamicsSimulator",
    "Windkessel4EParams",
    "Windkessel4ESimulator",
    "BaroreflexParams",
]
