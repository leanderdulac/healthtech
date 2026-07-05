import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class VertexConfig:
    """Configuração unificada para integração Datalake ↔ Vertex AI."""

    project_id: str = field(
        default_factory=lambda: os.getenv("GCP_PROJECT_ID", "project-placeholder")
    )
    location: str = field(
        default_factory=lambda: os.getenv("GCP_LOCATION", "us-central1")
    )
    endpoint_id: str = field(
        default_factory=lambda: os.getenv("VERTEX_ENDPOINT_ID", "endpoint-placeholder")
    )
    model_name: str = field(
        default_factory=lambda: os.getenv("VERTEX_MODEL_NAME", "model-placeholder")
    )
    staging_bucket: str = field(default_factory=lambda: os.getenv(
        "GCS_STAGING_BUCKET",
        f"gs://{os.getenv('GCP_PROJECT_ID', 'project-placeholder')}-vertex-staging",
    ))
    gcs_input_uri: str = field(
        default_factory=lambda: os.getenv("GCS_INPUT_DATA", "gs://placeholder/input.jsonl")
    )
    gcs_output_uri: str = field(
        default_factory=lambda: os.getenv("GCS_OUTPUT_DATA", "gs://placeholder/output/")
    )
    machine_type: str = field(
        default_factory=lambda: os.getenv("VERTEX_MACHINE_TYPE", "n1-standard-4")
    )
    tcn_endpoint_id: str = field(
        default_factory=lambda: os.getenv("VERTEX_TCN_ENDPOINT_ID", "endpoint-placeholder")
    )
    gcs_model_bucket: str = field(
        default_factory=lambda: os.getenv("GCS_MODEL_BUCKET", "")
    )
    serving_container: str = field(
        default_factory=lambda: os.getenv(
            "VERTEX_SERVING_CONTAINER",
            "us-docker.pkg.dev/vertex-ai/prediction/pytorch-gpu.2-0:latest",
        )
    )

    local_export_dir: Path = field(
        default_factory=lambda: Path("data/vertex_exports")
    )
    local_model_dir: Path = field(
        default_factory=lambda: Path("data/models")
    )

    def ensure_directories(self) -> None:
        self.local_export_dir.mkdir(parents=True, exist_ok=True)
        self.local_model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_gcp_configured(self) -> bool:
        placeholders = {"project-placeholder", "endpoint-placeholder", "model-placeholder"}
        return self.project_id not in placeholders