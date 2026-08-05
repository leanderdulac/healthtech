import pytest
from src.utils.gcp_auth import get_gcp_credentials


def test_get_gcp_credentials():
    creds, project_id = get_gcp_credentials(project_id="healthtech-gcp-2026")
    assert project_id == "healthtech-gcp-2026"
    # Deve retornar objeto de credencial válido (seja ADC ou via gcloud CLI token)
    assert creds is not None
