import json
import logging
from pathlib import Path
from typing import Dict, List

from src.hemodynamics.models import FlowAnalysisResult

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("data/hemodynamics")


class HemodynamicsStorage:
    def __init__(self, output_dir: Path = DEFAULT_OUTPUT):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_analysis(self, result: FlowAnalysisResult, summary: Dict) -> Dict[str, str]:
        paths = {}
        analysis_path = self.output_dir / f"analysis_{result.patient_id}_{result.scenario}.json"
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        paths["analysis"] = str(analysis_path)

        summary_path = self.output_dir / f"summary_{result.scenario}.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        paths["summary"] = str(summary_path)

        logger.info("Analise hemodinamica salva em %s", analysis_path)
        return paths

    def save_fhir_flags(self, flags: List[dict], scenario: str) -> str:
        path = self.output_dir / f"fhir_flags_{scenario}.json"
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [{"resource": f} for f in flags],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
        return str(path)