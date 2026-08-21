#!/usr/bin/env python3
"""Envia artefatos do classificador Next2U / matriz de alertas para o GCS.

Uso:
  python run_alert_matrix_gcs_upload.py
  GCS_STAGING_BUCKET=gs://healthtech-gcp-2026-vertex-staging python run_alert_matrix_gcs_upload.py

Sobe o modelo treinado + catálogo 971 padrões para:
  gs://<project>-vertex-staging/alert_matrix/<timestamp>/
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.utils.gcp_auth import get_gcp_credentials  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("alert-matrix-gcs")

PROJECT = os.getenv("GCP_PROJECT_ID", "healthtech-gcp-2026")
STAGING = os.getenv("GCS_STAGING_BUCKET", f"gs://{PROJECT}-vertex-staging")
MODELS = ROOT / "data" / "models"

FILES = [
    "alert_matrix_classifier.pkl",
    "alert_matrix_classifier_meta.json",
    "alert_matrix_training_summary.json",
    "alert_matrix_rules.json",
    "next2u_expanded_matrix.json",
    "next2u_communication_guardrails.json",
]


def main() -> int:
    missing = [f for f in FILES if not (MODELS / f).exists()]
    if missing:
        logger.error("Arquivos ausentes: %s", missing)
        return 1

    creds, proj = get_gcp_credentials(PROJECT)
    if creds is None:
        logger.error(
            "Sem credenciais GCP. Rode `gcloud auth application-default login` "
            "ou defina GOOGLE_APPLICATION_CREDENTIALS."
        )
        return 2

    from google.cloud import storage  # type: ignore

    client = storage.Client(project=proj or PROJECT, credentials=creds)
    bucket_name = STAGING.replace("gs://", "").split("/")[0]
    bucket = client.bucket(bucket_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = f"alert_matrix/{ts}"

    uploaded = []
    for fname in FILES:
        src = MODELS / fname
        blob = bucket.blob(f"{prefix}/{fname}")
        blob.upload_from_filename(str(src))
        uri = f"gs://{bucket_name}/{prefix}/{fname}"
        uploaded.append(uri)
        logger.info("Uploaded %s", uri)

    latest = bucket.blob("alert_matrix/latest.json")
    manifest = {
        "prefix": f"gs://{bucket_name}/{prefix}",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "files": uploaded,
        "model": "alert_matrix_classifier",
        "n_expanded_patterns": 971,
        "n_base_alerts": 158,
    }
    latest.upload_from_string(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    logger.info("Manifest gs://%s/alert_matrix/latest.json", bucket_name)

    state_path = ROOT / "data" / "vertex_deploy" / "deploy_state.json"
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    state["alert_matrix_gcs_prefix"] = f"gs://{bucket_name}/{prefix}"
    state["alert_matrix_uploaded_at"] = manifest["uploaded_at"]
    state["updated_at"] = manifest["uploaded_at"]
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
