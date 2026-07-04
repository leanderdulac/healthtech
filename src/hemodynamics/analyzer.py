"""
Analisador de fluxo vascular via grad, div e curl.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.hemodynamics.models import (
    FlowAnalysisResult,
    FlowIrregularity,
    ScalarField3D,
    VectorField3D,
)
from src.hemodynamics.operators import (
    curl_magnitude,
    divergence,
    gradient_magnitude,
)

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = {
    "gradient_high": 8.0,
    "divergence_source": 15.0,
    "divergence_sink": -12.0,
    "curl_high": 20.0,
}


class VascularFlowAnalyzer:
    """Detecta irregularidades hemodinâmicas com operadores vetoriais."""

    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def analyze(
        self,
        pressure: ScalarField3D,
        velocity: VectorField3D,
        patient_id: str = "PAT-HEMO-001",
        scenario: str = "unknown",
    ) -> FlowAnalysisResult:
        grad_mag = gradient_magnitude(pressure)
        div = divergence(velocity)
        curl_mag = curl_magnitude(velocity)

        irregularities: List[FlowIrregularity] = []
        irregularities.extend(self._find_gradient_hotspots(grad_mag, pressure))
        irregularities.extend(self._find_divergence_sources(div, velocity))
        irregularities.extend(self._find_divergence_sinks(div, velocity))
        irregularities.extend(self._find_curl_vortices(curl_mag, velocity))

        ontology_domains = self._ontology_scores(irregularities)

        return FlowAnalysisResult(
            patient_id=patient_id,
            scenario=scenario,
            pressure_field=pressure,
            velocity_field=velocity,
            gradient_magnitude=grad_mag,
            divergence=div,
            curl_magnitude=curl_mag,
            irregularities=irregularities,
            ontology_domains=ontology_domains,
        )

    def _world_pos(self, idx: Tuple[int, int, int], grid) -> Tuple[float, float, float]:
        i, j, k = idx
        return float(grid.x[i, j, k]), float(grid.y[i, j, k]), float(grid.z[i, j, k])

    def _top_indices(self, field: np.ndarray, n: int = 3) -> List[Tuple[int, int, int]]:
        flat = np.abs(field).ravel()
        if flat.max() == 0:
            return []
        top_k = min(n, flat.size)
        indices = np.argpartition(flat, -top_k)[-top_k:]
        return [np.unravel_index(i, field.shape) for i in indices]

    def _find_gradient_hotspots(
        self, grad_mag: np.ndarray, pressure: ScalarField3D,
    ) -> List[FlowIrregularity]:
        results = []
        thresh = self.thresholds["gradient_high"]
        for idx in self._top_indices(grad_mag, n=2):
            val = float(grad_mag[idx])
            if val < thresh:
                continue
            pos = self._world_pos(idx, pressure.grid)
            results.append(FlowIrregularity(
                irregularity_type="pressure_gradient_spike",
                severity="high" if val > thresh * 1.5 else "medium",
                location=idx,
                world_position=pos,
                metric_value=val,
                threshold=thresh,
                description=f"Gradiente de pressao elevado |grad_p|={val:.1f} em {pos}",
                operator="gradient",
            ))
        return results

    def _find_divergence_sources(
        self, div: np.ndarray, velocity: VectorField3D,
    ) -> List[FlowIrregularity]:
        results = []
        thresh = self.thresholds["divergence_source"]
        for idx in self._top_indices(div, n=2):
            val = float(div[idx])
            if val < thresh:
                continue
            pos = self._world_pos(idx, velocity.grid)
            results.append(FlowIrregularity(
                irregularity_type="flow_source",
                severity="critical" if val > thresh * 1.5 else "high",
                location=idx,
                world_position=pos,
                metric_value=val,
                threshold=thresh,
                description=f"Fonte de fluxo (aneurisma?) div={val:.1f} em {pos}",
                operator="divergence",
            ))
        return results

    def _find_divergence_sinks(
        self, div: np.ndarray, velocity: VectorField3D,
    ) -> List[FlowIrregularity]:
        results = []
        thresh = self.thresholds["divergence_sink"]
        for idx in self._top_indices(-div, n=2):
            val = float(div[idx])
            if val > thresh:
                continue
            pos = self._world_pos(idx, velocity.grid)
            results.append(FlowIrregularity(
                irregularity_type="flow_sink",
                severity="high" if val < thresh * 1.5 else "medium",
                location=idx,
                world_position=pos,
                metric_value=val,
                threshold=thresh,
                description=f"Sumidouro de fluxo (estenose?) div={val:.1f} em {pos}",
                operator="divergence",
            ))
        return results

    def _find_curl_vortices(
        self, curl_mag: np.ndarray, velocity: VectorField3D,
    ) -> List[FlowIrregularity]:
        results = []
        thresh = self.thresholds["curl_high"]
        for idx in self._top_indices(curl_mag, n=2):
            val = float(curl_mag[idx])
            if val < thresh:
                continue
            pos = self._world_pos(idx, velocity.grid)
            results.append(FlowIrregularity(
                irregularity_type="vortical_flow",
                severity="high" if val > thresh * 1.5 else "medium",
                location=idx,
                world_position=pos,
                metric_value=val,
                threshold=thresh,
                description=f"Fluxo rotacional (turbulento) |curl|={val:.1f} em {pos}",
                operator="curl",
            ))
        return results

    def _ontology_scores(self, irregularities: List[FlowIrregularity]) -> Dict[str, float]:
        scores = {"cardiovascular": 0.0, "monitoring": 0.0, "imaging": 0.0}
        for ir in irregularities:
            scores["cardiovascular"] = min(1.0, scores["cardiovascular"] + 0.25)
            if ir.operator in ("gradient", "divergence"):
                scores["monitoring"] = min(1.0, scores["monitoring"] + 0.2)
            if ir.irregularity_type == "vortical_flow":
                scores["imaging"] = min(1.0, scores["imaging"] + 0.3)
        try:
            from src.ontology.registry import MedicalOntologyRegistry
            registry = MedicalOntologyRegistry()
            if registry.load():
                text = " ".join(ir.description for ir in irregularities)
                scores.update(registry.domain_scores(text))
        except Exception:
            pass
        return scores