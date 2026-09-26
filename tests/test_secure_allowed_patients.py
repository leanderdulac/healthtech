"""Allow-list wildcard vs unset na API secure (anti-IDOR).

`get_allowed_patients()` precisa devolver `{"*"}` para wildcard — `set()` é
tratado como unset e, em produção, `check_patient_authorization` nega
chaves sem escopo admin (READ_API_KEY inclusa).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))

from app.config import Settings  # noqa: E402
from app.security.auth import check_patient_authorization  # noqa: E402

READ_KEY = "ht_read_real_configured_secret_value"
INGEST_KEY = "ht_ingest_real_configured_secret_value"
ADMIN_KEY = "ht_admin_real_configured_secret_value_32"


def _prod_settings(**kwargs) -> Settings:
    return Settings(
        environment="production",
        auth_disabled=False,
        read_api_key=READ_KEY,
        ingest_api_key=INGEST_KEY,
        admin_api_key=ADMIN_KEY,
        **kwargs,
    )


def test_get_allowed_patients_wildcard_is_star_not_empty():
    for raw in ("*", "ALL", "all", " * ", "*,PAT-X"):
        assert Settings(allowed_patient_ids=raw).get_allowed_patients() == {"*"}


def test_get_allowed_patients_unset_is_empty():
    assert Settings(allowed_patient_ids="").get_allowed_patients() == set()
    assert Settings(allowed_patient_ids="  ").get_allowed_patients() == set()


def test_get_allowed_patients_finite_csv():
    assert Settings(allowed_patient_ids="PAT-A, PAT-B").get_allowed_patients() == {
        "PAT-A",
        "PAT-B",
    }


def test_production_wildcard_allows_read_key_patient_detail():
    settings = _prod_settings(allowed_patient_ids="*")
    assert settings.get_allowed_patients() == {"*"}
    assert check_patient_authorization(READ_KEY, "PAT-DETAIL-1", settings) is True
    assert check_patient_authorization(INGEST_KEY, "PAT-DETAIL-1", settings) is True


def test_production_all_token_allows_read_key_patient_detail():
    settings = _prod_settings(allowed_patient_ids="ALL")
    assert settings.get_allowed_patients() == {"*"}
    assert check_patient_authorization(READ_KEY, "PAT-DETAIL-2", settings) is True


def test_production_unset_denies_non_admin_read_key():
    settings = _prod_settings(allowed_patient_ids="")
    assert settings.get_allowed_patients() == set()
    assert check_patient_authorization(READ_KEY, "PAT-ANY", settings) is False
    assert check_patient_authorization(INGEST_KEY, "PAT-ANY", settings) is False
    assert check_patient_authorization(ADMIN_KEY, "PAT-ANY", settings) is True


def test_production_finite_allowlist_still_idors():
    settings = _prod_settings(allowed_patient_ids="PAT-X,PAT-Y")
    assert check_patient_authorization(READ_KEY, "PAT-X", settings) is True
    assert check_patient_authorization(READ_KEY, "PAT-Z", settings) is False
