"""
Gerenciador de deploy Vertex AI — upload GCS + Model Registry + Endpoint TCN.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.deploy.packager import TCNModelPackager
from src.integrations.vertex.deploy.predictor import TCNTemporalPredictor

logger = logging.getLogger(__name__)


class VertexTCNEndpointManager:
    """
    Orquestra empacotamento, upload GCS e deploy dos 3 TCNs no Vertex AI.

    Suporta:
      - deploy local (smoke test do predictor)
      - upload para GCS + Model Registry
      - criação/atualização de Endpoint
    """

    def __init__(self, config: Optional[VertexConfig] = None):
        self.config = config or VertexConfig()
        self.config.ensure_directories()
        self.packager = TCNModelPackager(self.config.local_model_dir)
        self.deploy_dir = Path("data/vertex_deploy")
        self.deploy_dir.mkdir(parents=True, exist_ok=True)

    @property
    def gcs_model_bucket(self) -> str:
        return os.getenv(
            "GCS_MODEL_BUCKET",
            self.config.staging_bucket.replace("gs://", "").split("/")[0],
        )

    @property
    def tcn_endpoint_id(self) -> str:
        return os.getenv("VERTEX_TCN_ENDPOINT_ID", self.config.endpoint_id)

    def validate_artifacts(self) -> Dict:
        return self.packager.validate()

    def package(self) -> Path:
        return self.packager.package()

    def smoke_test_local(self, sequence: Optional[List] = None) -> Dict:
        """Testa predictor localmente antes do deploy GCP."""
        artifacts = self.package()
        predictor = TCNTemporalPredictor()
        predictor.load(str(artifacts))

        if sequence is None:
            import numpy as np
            n_features = 24
            sequence = np.random.randn(32, n_features).tolist()

        result = predictor.predict([{"sequence": sequence}])
        return {
            "status": "ok",
            "prediction": result[0],
            "artifacts_dir": str(artifacts),
        }

    def upload_to_gcs(self, artifacts_dir: Optional[Path] = None) -> str:
        """Upload artefatos para GCS staging bucket."""
        artifacts = artifacts_dir or self.package()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        gcs_prefix = f"tcn_models/{timestamp}"

        try:
            from google.cloud import storage
        except ImportError:
            logger.warning("google-cloud-storage não instalado — simulando URI GCS")
            return f"gs://{self.gcs_model_bucket}/{gcs_prefix}"

        client = storage.Client(project=self.config.project_id)
        bucket_name = self.gcs_model_bucket.replace("gs://", "")
        bucket = client.bucket(bucket_name)

        for fpath in Path(artifacts).rglob("*"):
            if fpath.is_file():
                blob_path = f"{gcs_prefix}/{fpath.relative_to(artifacts)}"
                blob = bucket.blob(blob_path)
                blob.upload_from_filename(str(fpath))

        uri = f"gs://{bucket_name}/{gcs_prefix}"
        logger.info("Artefatos enviados para %s", uri)
        self._save_deploy_state({"gcs_uri": uri, "uploaded_at": datetime.utcnow().isoformat()})
        return uri

    def deploy_to_vertex(
        self,
        gcs_uri: Optional[str] = None,
        display_name: str = "healthtech-tcn-temporal",
        sync: bool = False,
    ) -> Dict:
        """
        Registra modelo e faz deploy no Vertex AI Endpoint.

        Requer credenciais GCP configuradas (gcloud auth application-default login).
        """
        if not self.config.is_gcp_configured:
            return {
                "status": "skipped",
                "reason": "GCP não configurado — defina GCP_PROJECT_ID no .env",
                "local_smoke": self.smoke_test_local(),
            }

        artifacts = self.package()
        artifact_uri = gcs_uri or self.upload_to_gcs(artifacts)

        try:
            from google.cloud import aiplatform

            aiplatform.init(
                project=self.config.project_id,
                location=self.config.location,
                staging_bucket=self.config.staging_bucket,
            )

            serving_container = os.getenv(
                "VERTEX_SERVING_CONTAINER",
                "us-docker.pkg.dev/vertex-ai/prediction/pytorch-gpu.2-0:latest",
            )

            model = aiplatform.Model.upload(
                display_name=display_name,
                artifact_uri=artifact_uri,
                serving_container_image_uri=serving_container,
                serving_container_predict_route="/predict",
                serving_container_health_route="/health",
                serving_container_ports=[8080],
                description="3 TCNs independentes — horizontes 6h/24h/72h",
                sync=sync,
            )

            endpoint = None
            endpoint_id = self.tcn_endpoint_id
            if endpoint_id and "placeholder" not in endpoint_id:
                endpoint = aiplatform.Endpoint(endpoint_id)
                deployed = endpoint.deploy(
                    model=model,
                    deployed_model_display_name=f"{display_name}-v1",
                    machine_type=self.config.machine_type,
                    min_replica_count=1,
                    max_replica_count=2,
                    traffic_percentage=100,
                    sync=sync,
                )
            else:
                endpoint = model.deploy(
                    machine_type=self.config.machine_type,
                    min_replica_count=1,
                    max_replica_count=2,
                    sync=sync,
                )
                deployed = endpoint

            result = {
                "status": "deployed",
                "model_resource": model.resource_name,
                "endpoint_resource": endpoint.resource_name if endpoint else None,
                "artifact_uri": artifact_uri,
                "gcs_uri": artifact_uri,
            }
            self._save_deploy_state(result)
            return result

        except Exception as e:
            logger.exception("Deploy Vertex falhou")
            return {
                "status": "failed",
                "error": str(e),
                "artifact_uri": artifact_uri,
                "local_smoke": self.smoke_test_local(),
            }

    def _save_deploy_state(self, state: Dict) -> None:
        path = self.deploy_dir / "deploy_state.json"
        existing = {}
        if path.exists():
            with open(path) as f:
                existing = json.load(f)
        existing.update(state)
        existing["updated_at"] = datetime.utcnow().isoformat()
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)