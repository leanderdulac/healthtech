import logging
import os
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def get_gcp_credentials(project_id: Optional[str] = None) -> Tuple[Optional[object], Optional[str]]:
    """
    Obtém credenciais válidas do GCP:
    1. Tenta credenciais padrão do Google (ADC / IAM de Service Account em produção/Cloud Run).
    2. Fallback para o token ativo do `gcloud auth print-access-token` (dev local).

    Retorna uma tupla (credentials, resolved_project_id).
    Em ambientes sem google-auth ou sem login, retorna (None, project_id).
    """
    target_project = os.getenv("GCP_PROJECT_ID") or project_id or "healthtech-gcp-2026"

    try:
        import google.auth  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
    except ImportError:
        logger.debug("google-auth não instalado — credenciais GCP indisponíveis.")
        return None, target_project

    try:
        credentials, project = google.auth.default()
        resolved_project = project_id or os.getenv("GCP_PROJECT_ID") or project or target_project
        return credentials, resolved_project
    except Exception as e:
        logger.debug(
            "google.auth.default() não encontrou ADC (%s). Tentando gcloud CLI token...", e
        )
        try:
            token = subprocess.check_output(
                ["gcloud", "auth", "print-access-token"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if token:
                logger.info("Credencial GCP autenticada com sucesso via gcloud OAuth token.")
                return Credentials(token), target_project
        except Exception as ge:
            logger.warning("Falha ao obter token de acesso via gcloud CLI: %s", ge)

    return None, target_project
