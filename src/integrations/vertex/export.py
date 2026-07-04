import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.feature_builder import FEATURE_COLUMNS, ONLINE_FEATURE_COLUMNS

logger = logging.getLogger(__name__)


class VertexDataExporter:
    """Exporta features do datalake para formatos consumidos pelo Vertex AI."""

    def __init__(self, config: VertexConfig):
        self.config = config
        self.config.ensure_directories()

    def export_batch_jsonl(self, features_df: pd.DataFrame, filename: str = "batch_input.jsonl") -> Path:
        output_path = self.config.local_export_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            for _, row in features_df.iterrows():
                instance = {col: float(row.get(col, 0)) for col in FEATURE_COLUMNS}
                instance["patient_id"] = row.get("patient_id", "unknown")
                f.write(json.dumps(instance) + "\n")

        logger.info("Batch JSONL exportado: %s (%d instâncias)", output_path, len(features_df))
        return output_path

    def export_online_jsonl(
        self,
        instances: List[Dict],
        filename: str = "online_stream.jsonl",
    ) -> Path:
        output_path = self.config.local_export_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            for inst in instances:
                record = {col: inst.get(col, 0) for col in ONLINE_FEATURE_COLUMNS}
                record["patient_id"] = inst.get("patient_id", "unknown")
                record["timestamp"] = inst.get("timestamp", datetime.utcnow().isoformat())
                f.write(json.dumps(record) + "\n")

        logger.info("Online JSONL exportado: %s (%d instâncias)", output_path, len(instances))
        return output_path

    def export_training_csv(self, features_df: pd.DataFrame, filename: str = "training_data.csv") -> Path:
        output_path = self.config.local_export_dir / filename
        export_cols = ["patient_id"] + FEATURE_COLUMNS + ["risk_label", "clinical_risk_level"]
        available = [c for c in export_cols if c in features_df.columns]
        features_df[available].to_csv(output_path, index=False)
        logger.info("Training CSV exportado: %s", output_path)
        return output_path

    def get_gcs_upload_instructions(self, local_path: Path) -> Dict[str, str]:
        bucket = self.config.staging_bucket.replace("gs://", "").split("/")[0]
        blob_name = f"vertex-input/{local_path.name}"
        return {
            "local_path": str(local_path.resolve()),
            "gcs_uri": f"gs://{bucket}/{blob_name}",
            "upload_command": f"gsutil cp {local_path} gs://{bucket}/{blob_name}",
        }