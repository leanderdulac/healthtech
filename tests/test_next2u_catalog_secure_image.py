"""Catálogo Next2U na imagem secure (piloto só-regras, sem ML).

Sem ``data/models/next2u_expanded_matrix.json`` na imagem, ``load_base_meta()``
devolve ``{}`` e as 158 regras caem para 1★/leve com nome placeholder —
ex.: SpO2 88 classificado como ``leve``. Estes testes travam:

* a cópia do catálogo em ``saude_responsiva_secure/`` (contexto do build) é o
  catálogo real, idêntico ao de ``data/models/``;
* o Dockerfile secure copia o JSON para o caminho que o loader lê (/app);
* log ``alert_matrix_catalog=loaded`` (INFO) / ``=missing`` (WARNING);
* SpO2 88 + FC 72 com catálogo → ``critico`` (n2u_034, hipoxemia importante).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

# alert_matrix_rules primeiro: ele importa next2u_bases no nível do módulo.
from src.clinical_intelligence.alert_matrix_rules import (  # noqa: I001
    AlertMatrixEngine,
    VitalSnapshot,
)
from src.clinical_intelligence import next2u_bases
from src.clinical_intelligence.next2u_bases import build_rules, load_base_meta

ROOT = Path(__file__).resolve().parents[1]
REPO_CATALOG = ROOT / "data" / "models" / "next2u_expanded_matrix.json"
SECURE_DIR = ROOT / "saude_responsiva_secure"
SECURE_CATALOG = SECURE_DIR / "data" / "models" / "next2u_expanded_matrix.json"
DOCKERFILE = SECURE_DIR / "Dockerfile"
EXPECTED_MATRIX_VERSION = "next2u-158-971-2026-08-16"
LOGGER_NAME = "src.clinical_intelligence.next2u_bases"


def _fired(rules, snap):
    return [r for r in rules if r["predicate"](snap)]


def _spo2_88_hr_72() -> VitalSnapshot:
    return VitalSnapshot(hr=72, spo2=88)


def test_secure_catalog_is_the_real_catalog_and_matches_repo():
    assert SECURE_CATALOG.is_file(), SECURE_CATALOG
    assert SECURE_CATALOG.read_bytes() == REPO_CATALOG.read_bytes()
    cat = json.loads(SECURE_CATALOG.read_text(encoding="utf-8"))
    assert cat["n_base_alerts"] == 158
    assert cat["n_expanded_patterns"] == 971
    assert len(cat["patterns"]) == 971
    assert len({p["base_id"] for p in cat["patterns"]}) == 158
    version = (
        f"next2u-{cat['n_base_alerts']}-{cat['n_expanded_patterns']}-{cat['version']}"
    )
    assert version == EXPECTED_MATRIX_VERSION


def test_secure_dockerfile_copies_catalog_where_loader_reads_it():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "WORKDIR /app" in text
    assert (
        "data/models/next2u_expanded_matrix.json "
        "/app/data/models/next2u_expanded_matrix.json"
    ) in text
    # Loader lê relativo ao CWD (/app na imagem).
    assert next2u_bases.DEFAULT_CATALOG_PATH == Path(
        "data/models/next2u_expanded_matrix.json"
    )
    # Piloto só-regras: nada de modelo ML na imagem por este caminho.
    assert "alert_matrix_classifier.pkl" not in text


def test_catalog_present_logs_loaded_and_has_158_rules(caplog):
    next2u_bases._CATALOG_STATUS_LOGGED.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        meta = load_base_meta(SECURE_CATALOG)
    assert len(meta) == 158
    assert meta[34]["base_stars"] == 3
    assert meta[34]["profile_id"] == 3
    msgs = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    loaded = [m for m in msgs if "alert_matrix_catalog=loaded" in m]
    assert len(loaded) == 1, msgs
    assert f"path={SECURE_CATALOG}" in loaded[0]
    assert "rules=158" in loaded[0]
    assert "version=2026-08-16" in loaded[0]
    assert not any("alert_matrix_catalog=missing" in m for m in msgs)


def test_catalog_missing_logs_warning_and_falls_back(tmp_path, caplog):
    missing = tmp_path / "data" / "models" / "next2u_expanded_matrix.json"
    next2u_bases._CATALOG_STATUS_LOGGED.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        rules = build_rules(missing)
    warnings = [
        r
        for r in caplog.records
        if r.name == LOGGER_NAME
        and r.levelno == logging.WARNING
        and "alert_matrix_catalog=missing" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert f"path={missing}" in warnings[0].getMessage()
    # Comportamento que se via em produção sem o JSON.
    fired = _fired(rules, _spo2_88_hr_72())
    by_id = {r["rule_id"]: r for r in fired}
    assert "n2u_034" in by_id
    assert by_id["n2u_034"]["severity"] == "leve"
    assert by_id["n2u_034"]["name"] == "Possível padrão clínico 034"
    assert by_id["n2u_034"]["category"] == "pa_alta"


def test_catalog_status_logged_once_per_path(caplog):
    next2u_bases._CATALOG_STATUS_LOGGED.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        load_base_meta(SECURE_CATALOG)
        load_base_meta(SECURE_CATALOG)
    loaded = [
        r for r in caplog.records if "alert_matrix_catalog=loaded" in r.getMessage()
    ]
    assert len(loaded) == 1


def test_spo2_88_hr_72_is_critico_with_secure_catalog():
    rules = build_rules(SECURE_CATALOG)
    assert len(rules) == 158
    assert not any(r["name"].startswith("Possível padrão clínico") for r in rules)
    fired = _fired(rules, _spo2_88_hr_72())
    assert fired
    top = max(fired, key=lambda r: {"leve": 1, "moderado": 2, "critico": 3}[r["severity"]])
    assert top["severity"] == "critico"
    by_id = {r["rule_id"]: r for r in fired}
    assert by_id["n2u_034"]["severity"] == "critico"
    assert by_id["n2u_034"]["category"] == "spo2"
    assert by_id["n2u_034"]["name"] == "Possível hipoxemia importante"


def test_engine_spo2_88_hr_72_is_critico():
    # ALERT_RULES carregado no import a partir do CWD (raiz do repo no CI).
    res = AlertMatrixEngine().evaluate(_spo2_88_hr_72())
    assert res.is_true_alert
    assert res.max_severity == "critico"
    assert res.primary_rule_id == "n2u_034"
