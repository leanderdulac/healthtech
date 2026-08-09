#!/usr/bin/env python3
"""
Deploy TCN self-contained custom container no Vertex AI.

Passos:
  1. Empacota artefatos (.pt, scaler, conformal) → GCS
  2. Build + push imagem Docker (Flask+torch) → Artifact Registry
  3. Model.upload + Endpoint.create/deploy (NÃO sobrescreve IsolationForest)
  4. Smoke predict + grava deploy_state
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.utils.gcp_auth import get_gcp_credentials  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("deploy-tcn")

PROJECT = os.getenv("GCP_PROJECT_ID", "healthtech-gcp-2026")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
STAGING = os.getenv("GCS_STAGING_BUCKET", f"gs://{PROJECT}-vertex-staging")
REPO = os.getenv("VERTEX_TCN_AR_REPO", "cloud-run-source-deploy")
IMAGE_NAME = os.getenv("VERTEX_TCN_IMAGE", "healthtech-tcn-server")
MACHINE = os.getenv("VERTEX_MACHINE_TYPE", "n1-standard-4")
DISPLAY = "healthtech-tcn-temporal"

DEPLOY_DIR = ROOT / "data" / "vertex_deploy"
ARTIFACTS = DEPLOY_DIR / "artifacts"
MODELS = ROOT / "data" / "models"
DEPLOY_SRC = ROOT / "src" / "integrations" / "vertex" / "deploy"

REQUIRED = [
    "temporal_horizon_event_6h.pt",
    "temporal_horizon_event_24h.pt",
    "temporal_horizon_event_72h.pt",
    "temporal_scaler.pkl",
    "temporal_model_meta.json",
]
OPTIONAL = ["conformal_calibration.json", "temporal_scaler.json"]


def _export_scaler_json() -> None:
    """Gera temporal_scaler.json portátil a partir do .pkl (evita mismatch sklearn)."""
    pkl = MODELS / "temporal_scaler.pkl"
    out = MODELS / "temporal_scaler.json"
    if not pkl.exists():
        return
    try:
        import pickle

        with open(pkl, "rb") as f:
            scaler = pickle.load(f)
        data = {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "n_features": int(len(scaler.mean_)),
        }
        out.write_text(json.dumps(data))
        logger.info("Exported portable scaler → %s", out)
    except Exception as e:
        logger.warning("Não foi possível exportar scaler JSON: %s", e)


def package_artifacts() -> Path:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    _export_scaler_json()
    for fname in REQUIRED:
        src = MODELS / fname
        if not src.exists():
            raise FileNotFoundError(f"Missing {src}")
        shutil.copy2(src, ARTIFACTS / fname)
    for fname in OPTIONAL:
        src = MODELS / fname
        if src.exists():
            shutil.copy2(src, ARTIFACTS / fname)
    # copy conformal from models or existing
    conf = MODELS / "conformal_calibration.json"
    if not conf.exists():
        conf = DEPLOY_DIR / "artifacts" / "conformal_calibration.json"
    if conf.exists():
        shutil.copy2(conf, ARTIFACTS / "conformal_calibration.json")
    manifest = {
        "model_type": "tcn_per_horizon",
        "horizons": ["6h", "24h", "72h"],
        "artifacts": [f for f in REQUIRED + OPTIONAL if (ARTIFACTS / f).exists()],
        "server": "tcn_server.py",
    }
    (ARTIFACTS / "manifest.json").write_text(json.dumps(manifest, indent=2))
    logger.info("Packaged artifacts → %s", ARTIFACTS)
    return ARTIFACTS


def smoke_local() -> Dict:
    """Importa runtime localmente e prevê sequência aleatória."""
    sys.path.insert(0, str(DEPLOY_SRC))
    from tcn_server import TCNRuntime  # type: ignore

    rt = TCNRuntime()
    rt.load(package_artifacts())
    import numpy as np

    seq = np.random.randn(32, 24).astype("float32")
    pred = rt.predict_one(seq)
    return {"status": "ok", "prediction": pred}


def upload_gcs(artifacts: Path) -> str:
    from google.cloud import storage

    creds, proj = get_gcp_credentials(PROJECT)
    client = storage.Client(project=proj or PROJECT, credentials=creds)
    bucket_name = STAGING.replace("gs://", "").split("/")[0]
    bucket = client.bucket(bucket_name)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = f"tcn_models/{ts}"
    for fpath in artifacts.rglob("*"):
        if fpath.is_file():
            blob = bucket.blob(f"{prefix}/{fpath.relative_to(artifacts)}")
            blob.upload_from_filename(str(fpath))
            logger.info("Uploaded %s", blob.name)
    uri = f"gs://{bucket_name}/{prefix}"
    logger.info("GCS artifact_uri=%s", uri)
    return uri


def ensure_ar_auth() -> str:
    image = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}/{IMAGE_NAME}:latest"
    subprocess.check_call(
        ["gcloud", "auth", "configure-docker", f"{LOCATION}-docker.pkg.dev", "-q"],
        cwd=str(ROOT),
    )
    return image


def build_and_push_image() -> str:
    image = ensure_ar_auth()
    dockerfile = DEPLOY_SRC / "Dockerfile.tcn"
    # build context = deploy dir (tcn_server.py + Dockerfile)
    cmd = [
        "docker",
        "build",
        "-f",
        str(dockerfile),
        "-t",
        image,
        str(DEPLOY_SRC),
    ]
    logger.info("Building image: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    logger.info("Pushing %s", image)
    subprocess.check_call(["docker", "push", image])
    return image


def deploy_vertex(artifact_uri: str, image_uri: str, sync: bool = True) -> Dict:
    from google.cloud import aiplatform

    creds, proj = get_gcp_credentials(PROJECT)
    aiplatform.init(
        project=proj or PROJECT,
        location=LOCATION,
        staging_bucket=STAGING,
        credentials=creds,
    )

    model = aiplatform.Model.upload(
        display_name=DISPLAY,
        artifact_uri=artifact_uri,
        serving_container_image_uri=image_uri,
        serving_container_predict_route="/predict",
        serving_container_health_route="/health",
        serving_container_ports=[8080],
        # NÃO sobrescrever AIP_STORAGE_URI — o Vertex injeta gs://... dos artefatos.
        serving_container_environment_variables={
            "AIP_HEALTH_ROUTE": "/health",
            "AIP_PREDICT_ROUTE": "/predict",
        },
        description="TCN multi-horizon 6h/24h/72h custom container",
        sync=True,
    )
    logger.info("Model uploaded: %s", model.resource_name)

    # Sempre cria endpoint NOVO para não tocar no IsolationForest
    endpoint = model.deploy(
        deployed_model_display_name=f"{DISPLAY}-v1",
        machine_type=MACHINE,
        min_replica_count=1,
        max_replica_count=1,
        traffic_percentage=100,
        sync=sync,
    )
    logger.info("Endpoint: %s", endpoint.resource_name)

    result = {
        "status": "deployed",
        "model_type": "tcn_per_horizon",
        "model_resource": model.resource_name,
        "endpoint_resource": endpoint.resource_name,
        "VERTEX_TCN_ENDPOINT_ID": endpoint.resource_name,
        "VERTEX_TCN_MODEL_NAME": model.resource_name,
        "artifact_uri": artifact_uri,
        "image_uri": image_uri,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
    }

    # smoke predict
    try:
        import numpy as np

        seq = np.random.randn(32, 24).astype(float).tolist()
        pred = endpoint.predict(instances=[{"sequence": seq}])
        result["predictions_smoke"] = pred.predictions
        logger.info("Smoke predictions: %s", pred.predictions)
    except Exception as e:
        logger.warning("Smoke predict falhou (endpoint pode ainda estar aquecendo): %s", e)
        result["predictions_smoke_error"] = str(e)

    # merge state — preserva IsolationForest keys
    state_path = DEPLOY_DIR / "deploy_state.json"
    existing = {}
    if state_path.exists():
        existing = json.loads(state_path.read_text())
    existing.update({
        "tcn_status": result["status"],
        "tcn_model_resource": result["model_resource"],
        "tcn_endpoint_resource": result["endpoint_resource"],
        "VERTEX_TCN_ENDPOINT_ID": result["VERTEX_TCN_ENDPOINT_ID"],
        "VERTEX_TCN_MODEL_NAME": result["VERTEX_TCN_MODEL_NAME"],
        "tcn_artifact_uri": artifact_uri,
        "tcn_image_uri": image_uri,
        "tcn_deployed_at": result["deployed_at"],
        "tcn_predictions_smoke": result.get("predictions_smoke"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    state_path.write_text(json.dumps(existing, indent=2, default=str))
    logger.info("Saved %s", state_path)
    return result


def main(argv: Optional[list] = None) -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--smoke-only", action="store_true")
    p.add_argument("--upload-only", action="store_true")
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--deploy", action="store_true")
    p.add_argument("--sync", action="store_true", default=True)
    p.add_argument("--skip-build", action="store_true", help="Reusa imagem latest já publicada")
    args = p.parse_args(argv)

    arts = package_artifacts()

    if args.smoke_only:
        print(json.dumps(smoke_local(), indent=2, default=str))
        return 0

    if args.upload_only:
        uri = upload_gcs(arts)
        print(uri)
        return 0

    if args.build_only:
        image = build_and_push_image()
        print(image)
        return 0

    if not args.deploy:
        print(json.dumps(smoke_local(), indent=2, default=str))
        return 0

    uri = upload_gcs(arts)
    if args.skip_build:
        image = f"{LOCATION}-docker.pkg.dev/{PROJECT}/{REPO}/{IMAGE_NAME}:latest"
    else:
        image = build_and_push_image()
    result = deploy_vertex(uri, image, sync=args.sync)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "deployed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
