from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np


@dataclass
class Grid3D:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0)

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self.x.shape


@dataclass
class ScalarField3D:
    values: np.ndarray
    grid: Grid3D
    name: str = "phi"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "shape": list(self.values.shape),
            "min": float(np.nanmin(self.values)),
            "max": float(np.nanmax(self.values)),
            "mean": float(np.nanmean(self.values)),
        }


@dataclass
class VectorField3D:
    fx: np.ndarray
    fy: np.ndarray
    fz: np.ndarray
    grid: Grid3D
    name: str = "velocity"

    @property
    def magnitude(self) -> np.ndarray:
        return np.sqrt(self.fx ** 2 + self.fy ** 2 + self.fz ** 2)

    def to_dict(self) -> Dict[str, Any]:
        mag = self.magnitude
        return {
            "name": self.name,
            "shape": list(self.fx.shape),
            "max_magnitude": float(np.nanmax(mag)),
            "mean_magnitude": float(np.nanmean(mag)),
        }


@dataclass
class FlowIrregularity:
    irregularity_type: str
    severity: str
    location: Tuple[int, int, int]
    world_position: Tuple[float, float, float]
    metric_value: float
    threshold: float
    description: str
    operator: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["location"] = tuple(int(v) for v in self.location)
        d["world_position"] = tuple(float(v) for v in self.world_position)
        d["metric_value"] = float(self.metric_value)
        d["threshold"] = float(self.threshold)
        return d


@dataclass
class FlowAnalysisResult:
    patient_id: str
    scenario: str
    pressure_field: ScalarField3D
    velocity_field: VectorField3D
    gradient_magnitude: np.ndarray
    divergence: np.ndarray
    curl_magnitude: np.ndarray
    irregularities: List[FlowIrregularity] = field(default_factory=list)
    ontology_domains: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patient_id": self.patient_id,
            "scenario": self.scenario,
            "pressure": self.pressure_field.to_dict(),
            "velocity": self.velocity_field.to_dict(),
            "gradient_max": float(np.nanmax(self.gradient_magnitude)),
            "divergence_max": float(np.nanmax(np.abs(self.divergence))),
            "curl_max": float(np.nanmax(self.curl_magnitude)),
            "irregularities_count": len(self.irregularities),
            "irregularities": [i.to_dict() for i in self.irregularities],
            "ontology_domains": self.ontology_domains,
        }