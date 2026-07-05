"""
Empacotamento de artefatos TCN para upload ao Vertex AI Model Registry.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REQUIRED_ARTIFACTS = [
    "temporal_horizon_event_6h.pt",
    "temporal_horizon_event_24h.pt",
    "temporal_horizon_event_72h.pt",
    "temporal_scaler.pkl",
    "temporal_model_meta.json",
]

OPTIONAL_ARTIFACTS = [
    "conformal_calibration.json",
]


class TCNModelPackager:
    """Prepara diretório de serving com modelos, scaler e predictor."""

    def __init__(self, model_dir: Path, output_dir: Optional[Path] = None):
        self.model_dir = Path(model_dir)
        self.output_dir = Path(output_dir or "data/vertex_deploy/artifacts")

    def validate(self) -> Dict:
        missing = [f for f in REQUIRED_ARTIFACTS if not (self.model_dir / f).exists()]
        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "found": [f for f in REQUIRED_ARTIFACTS if (self.model_dir / f).exists()],
        }

    def package(self, include_predictor: bool = True) -> Path:
        validation = self.validate()
        if not validation["valid"]:
            raise FileNotFoundError(f"Artefatos ausentes: {validation['missing']}")

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for fname in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
            src = self.model_dir / fname
            if src.exists():
                shutil.copy2(src, self.output_dir / fname)

        if include_predictor:
            self._write_serving_handler()

        manifest = {
            "model_type": "tcn_per_horizon",
            "horizons": ["6h", "24h", "72h"],
            "artifacts": [f for f in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS
                          if (self.output_dir / f).exists()],
            "predictor": "predictor.py",
            "requirements": "requirements-serving.txt",
        }
        with open(self.output_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info("Pacote TCN criado em %s", self.output_dir)
        return self.output_dir

    def _write_serving_handler(self) -> None:
        handler = self.output_dir / "predictor.py"
        shutil.copy2(
            Path(__file__).parent / "predictor.py",
            handler,
        )

        requirements = self.output_dir / "requirements-serving.txt"
        requirements.write_text(
            "torch>=2.0.0\n"
            "numpy>=1.24.0\n"
            "scikit-learn>=1.3.0\n"
            "google-cloud-aiplatform>=1.30.0\n"
        )

        serving_entry = self.output_dir / "handler.py"
        serving_entry.write_text(
            'from predictor import TCNTemporalPredictor\n'
            'predictor = TCNTemporalPredictor()\n'
        )