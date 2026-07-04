"""
Geração de alertas clínicos e recursos FHIR a partir da análise hemodinâmica.
"""

import uuid
from datetime import datetime
from typing import Dict, List

from src.datalake.schemas.gold import GoldPatientAlert
from src.hemodynamics.models import FlowAnalysisResult, FlowIrregularity
from src.fhir.mappers import gold_alert_to_flag


class HemodynamicsAlertGenerator:
    """Converte irregularidades hemodinâmicas em alertas Gold + FHIR Flag."""

    METRIC_MAP = {
        "pressure_gradient_spike": "heart_rate",
        "flow_source": "heart_rate",
        "flow_sink": "heart_rate",
        "vortical_flow": "hrv",
    }

    def generate_gold_alerts(self, result: FlowAnalysisResult) -> List[GoldPatientAlert]:
        now = datetime.utcnow()
        alerts = []
        for ir in result.irregularities:
            alerts.append(GoldPatientAlert(
                alert_id=f"HEMO-{uuid.uuid4().hex[:12]}",
                patient_id=result.patient_id,
                alert_type=ir.irregularity_type,
                severity=ir.severity,
                metric_type=self.METRIC_MAP.get(ir.irregularity_type, "heart_rate"),
                trigger_value=ir.metric_value,
                threshold=ir.threshold,
                window_start=now,
                window_end=now,
                duration_minutes=0.0,
                devices_involved=["hemodynamics_analyzer"],
                created_at=now,
            ))
        return alerts

    def generate_fhir_flags(self, result: FlowAnalysisResult) -> List[dict]:
        flags = []
        for alert in self.generate_gold_alerts(result):
            flag = gold_alert_to_flag(alert)
            flag["code"]["text"] = next(
                (ir.description for ir in result.irregularities
                 if ir.irregularity_type == alert.alert_type),
                alert.alert_type,
            )
            flags.append(flag)
        return flags

    def summary(self, result: FlowAnalysisResult) -> Dict:
        return {
            "patient_id": result.patient_id,
            "scenario": result.scenario,
            "operators": {
                "gradient_max": float(result.gradient_magnitude.max()),
                "divergence_range": [
                    float(result.divergence.min()),
                    float(result.divergence.max()),
                ],
                "curl_max": float(result.curl_magnitude.max()),
            },
            "irregularities": len(result.irregularities),
            "alerts_generated": len(result.irregularities),
            "ontology_domains": result.ontology_domains,
            "by_operator": self._count_by_operator(result.irregularities),
        }

    @staticmethod
    def _count_by_operator(irregularities: List[FlowIrregularity]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for ir in irregularities:
            counts[ir.operator] = counts.get(ir.operator, 0) + 1
        return counts