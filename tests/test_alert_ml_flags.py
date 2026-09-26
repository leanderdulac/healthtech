"""Flags da camada ML da matriz de alertas (piloto Next2U / API secure).

O dataset de treino no repo é sintético. Estes testes usam um stub sklearn
mínimo — não é modelo clínico nem validado.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler

from src.clinical_intelligence.alert_ingest import (
    assess_ingest_alerts,
    clear_classifier_cache,
    materialize_model_path,
    resolve_model_spec,
)
from src.clinical_intelligence.alert_matrix_dataset import FEATURE_COLUMNS, SEVERITY_LABELS


@pytest.fixture
def reset_alert_ml(monkeypatch):
    monkeypatch.delenv("ALERT_ML_ENABLED", raising=False)
    monkeypatch.delenv("ALERT_MATRIX_MODEL_PATH", raising=False)
    monkeypatch.delenv("ALERT_MATRIX_MODEL_DIR", raising=False)
    monkeypatch.delenv("ALERT_ML_ALLOW_SUPPRESS", raising=False)
    monkeypatch.delenv("ALERT_ML_ALLOW_SOFT_ALERT", raising=False)
    monkeypatch.delenv("ALERT_ML_MODEL_VERSION", raising=False)
    monkeypatch.delenv("ALERT_ML_PROVENANCE", raising=False)
    monkeypatch.delenv("ALERT_ML_CACHE_DIR", raising=False)
    clear_classifier_cache()
    yield
    clear_classifier_cache()


def _write_stub_model(tmp_path: Path) -> Path:
    """Stub rápido: preenche ml.* sem pretender qualidade clínica."""
    n_feat = len(FEATURE_COLUMNS)
    rng = np.random.RandomState(0)
    X = rng.randn(48, n_feat)
    y_sev = rng.randint(0, 4, 48)
    y_bin = rng.randint(0, 2, 48)
    scaler = StandardScaler().fit(X)
    xs = scaler.transform(X)
    enc = LabelEncoder()
    enc.fit(SEVERITY_LABELS)
    sev = HistGradientBoostingClassifier(max_iter=8, max_depth=2, random_state=0)
    sev.fit(xs, y_sev)
    fp = RandomForestClassifier(n_estimators=4, max_depth=2, random_state=0)
    fp.fit(xs, y_bin)
    alert = RandomForestClassifier(n_estimators=4, max_depth=2, random_state=0)
    alert.fit(xs, y_bin)
    path = tmp_path / "alert_matrix_classifier.pkl"
    with open(path, "wb") as fh:
        pickle.dump(
            {
                "scaler": scaler,
                "severity_encoder": enc,
                "severity_clf": sev,
                "fp_clf": fp,
                "alert_clf": alert,
                "feature_columns": list(FEATURE_COLUMNS),
                "metrics": {"note": "test-stub-unvalidated"},
            },
            fh,
        )
    return path


def _hypoxemia_kwargs():
    return dict(heart_rate=85, spo2=88, skin_temp=33.0, phantom={})


def test_ml_flag_off_uses_rules_only(reset_alert_ml, caplog):
    caplog.set_level("INFO")
    alerts = assess_ingest_alerts(**_hypoxemia_kwargs())
    assert alerts["engine"] == "alert_matrix_rules"
    assert alerts["ml"] is None
    assert alerts["is_true_alert"] is True
    assert alerts["severity"] == "critico"
    assert any("alert_ml=disabled reason=ALERT_ML_ENABLED=false" in r.message for r in caplog.records)


def test_ml_flag_on_missing_model_falls_back_to_rules(reset_alert_ml, tmp_path, monkeypatch, caplog):
    missing = tmp_path / "does-not-exist" / "alert_matrix_classifier.pkl"
    monkeypatch.setenv("ALERT_ML_ENABLED", "true")
    monkeypatch.setenv("ALERT_MATRIX_MODEL_PATH", str(missing))
    caplog.set_level("WARNING")
    alerts = assess_ingest_alerts(**_hypoxemia_kwargs())
    assert alerts["engine"] == "alert_matrix_rules"
    assert alerts["ml"] is None
    assert alerts["is_true_alert"] is True
    assert any(
        "alert_ml=disabled reason=model_missing" in r.message for r in caplog.records
    )


def test_ml_flag_on_with_stub_model_populates_ml_fields(reset_alert_ml, tmp_path, monkeypatch, caplog):
    model = _write_stub_model(tmp_path)
    monkeypatch.setenv("ALERT_ML_ENABLED", "true")
    monkeypatch.setenv("ALERT_MATRIX_MODEL_PATH", str(model))
    monkeypatch.setenv("ALERT_ML_MODEL_VERSION", "test-stub")
    caplog.set_level("INFO")
    alerts = assess_ingest_alerts(**_hypoxemia_kwargs())
    assert alerts["engine"] == "alert_matrix_ml"
    assert isinstance(alerts["ml"], dict)
    assert "ml_severity" in alerts["ml"]
    assert "ml_false_positive_prob" in alerts["ml"]
    assert "ml_true_alert_prob" in alerts["ml"]
    assert alerts["ml"]["suggestive_only"] is True
    assert alerts["ml"]["role"] == "suggestion"
    assert alerts["ml"]["provenance"] == "synthetic-unvalidated"
    assert any("alert_ml=enabled model=" in r.message for r in caplog.records)
    assert any("version=test-stub" in r.message for r in caplog.records)


def test_ml_does_not_override_three_star_severity(reset_alert_ml, tmp_path, monkeypatch):
    model = _write_stub_model(tmp_path)
    monkeypatch.setenv("ALERT_ML_ENABLED", "true")
    monkeypatch.setenv("ALERT_MATRIX_MODEL_PATH", str(model))
    alerts = assess_ingest_alerts(**_hypoxemia_kwargs())
    assert alerts["is_true_alert"] is True
    assert alerts["severity"] == "critico"
    assert (alerts.get("staff_only") or {}).get("stars") == 3


def test_ml_does_not_suppress_rule_alert_by_default(reset_alert_ml, tmp_path, monkeypatch):
    model = _write_stub_model(tmp_path)
    monkeypatch.setenv("ALERT_ML_ENABLED", "true")
    monkeypatch.setenv("ALERT_MATRIX_MODEL_PATH", str(model))
    alerts = assess_ingest_alerts(
        heart_rate=125,
        spo2=97,
        skin_temp=36.8,
        hband_ext={"blood_pressure_sys": 190, "blood_pressure_dia": 115},
        raw_telemetry={"body_temp_c": 36.8},
    )
    assert alerts["is_true_alert"] is True
    assert alerts["severity"] == "critico"
    assert alerts["decision"] != "suppressed_false_positive"


def test_resolve_model_spec_path_and_dir(reset_alert_ml, tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_MATRIX_MODEL_PATH", str(tmp_path / "custom.pkl"))
    assert resolve_model_spec().endswith("custom.pkl")
    monkeypatch.delenv("ALERT_MATRIX_MODEL_PATH")
    monkeypatch.setenv("ALERT_MATRIX_MODEL_DIR", str(tmp_path))
    assert resolve_model_spec() == str(tmp_path / "alert_matrix_classifier.pkl")
    nested = tmp_path / "bundle"
    nested.mkdir()
    assert materialize_model_path(str(nested)) == nested / "alert_matrix_classifier.pkl"


def test_gcs_cache_hit_does_not_need_client(reset_alert_ml, tmp_path, monkeypatch):
    from src.clinical_intelligence.alert_ingest import _download_gcs_uri

    cache = tmp_path / "cache"
    dest = cache / "bucket" / "alert_matrix" / "alert_matrix_classifier.pkl"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stub-bytes")
    monkeypatch.setenv("ALERT_ML_CACHE_DIR", str(cache))
    out = _download_gcs_uri("gs://bucket/alert_matrix/alert_matrix_classifier.pkl")
    assert out == dest


def test_gcs_without_client_is_load_failure(reset_alert_ml, monkeypatch, caplog):
    monkeypatch.setenv("ALERT_ML_ENABLED", "true")
    monkeypatch.setenv(
        "ALERT_MATRIX_MODEL_PATH",
        "gs://healthtech-gcp-2026-vertex-staging/alert_matrix/latest/alert_matrix_classifier.pkl",
    )

    import src.clinical_intelligence.alert_ingest as ingest

    def _boom(_uri: str):
        raise RuntimeError("gcs_client_unavailable: instale google-cloud-storage")

    monkeypatch.setattr(ingest, "_download_gcs_uri", _boom)
    caplog.set_level("WARNING")
    alerts = assess_ingest_alerts(**_hypoxemia_kwargs())
    assert alerts["engine"] == "alert_matrix_rules"
    assert any("alert_ml=disabled reason=load_failed" in r.message for r in caplog.records)


def test_classifier_load_accepts_file_path(tmp_path):
    from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier

    path = _write_stub_model(tmp_path)
    clf = AlertMatrixClassifier.load(path)
    assert clf.severity_clf is not None
    assert Path(clf.model_path_) == path
