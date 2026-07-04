import json
import logging
from pathlib import Path
from typing import Dict, List

from src.clinical_intelligence.models import ClinicalIntelligenceResult

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("data/clinical_intelligence")


class ClinicalIntelligenceStorage:
    def __init__(self, output_dir: Path = DEFAULT_OUTPUT):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: ClinicalIntelligenceResult) -> str:
        path = self.output_dir / f"prediction_{result.patient_id}_{result.scenario}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Predicao clinica salva em %s", path)
        return str(path)

    def save_batch_summary(self, results: List[ClinicalIntelligenceResult]) -> str:
        summary = {
            "patients_analyzed": len(results),
            "predictions": [
                {
                    "patient_id": r.patient_id,
                    "fusion_score": r.fusion_score,
                    "ghost_count": len(r.ghost_signals),
                    "top_prediction": r.predictions[0].to_dict() if r.predictions else None,
                    "fuzzy_summary": r.fuzzy.linguistic_summary,
                }
                for r in results
            ],
        }
        path = self.output_dir / "batch_summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        return str(path)