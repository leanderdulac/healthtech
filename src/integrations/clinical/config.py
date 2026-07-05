import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class ClinicalIntegrationConfig:
    """Configuração para integração com FHIR Server em produção."""

    fhir_server_url: str = field(
        default_factory=lambda: os.getenv("FHIR_SERVER_URL", "http://localhost:8080/fhir")
    )
    fhir_server_token: str = field(
        default_factory=lambda: os.getenv("FHIR_SERVER_TOKEN", "")
    )
    fhir_version: str = field(
        default_factory=lambda: os.getenv("FHIR_VERSION", "R4")
    )
    local_cache_dir: str = field(
        default_factory=lambda: os.getenv("CLINICAL_CACHE_DIR", "data/clinical_cache")
    )
    sync_batch_size: int = field(
        default_factory=lambda: int(os.getenv("CLINICAL_SYNC_BATCH_SIZE", "50"))
    )

    @property
    def is_configured(self) -> bool:
        has_remote = bool(self.fhir_server_url) and "localhost" not in self.fhir_server_url
        return has_remote or bool(self.fhir_server_token)