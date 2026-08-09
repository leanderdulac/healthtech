"""Smoke tests do runtime TCN self-contained (Vertex custom container)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# CI leve não instala torch/flask — pular o módulo inteiro nesse ambiente.
torch = pytest.importorskip("torch")
pytest.importorskip("flask")

DEPLOY_SRC = Path(__file__).resolve().parents[1] / "src" / "integrations" / "vertex" / "deploy"
ARTIFACTS = Path(__file__).resolve().parents[1] / "data" / "vertex_deploy" / "artifacts"
MODELS = Path(__file__).resolve().parents[1] / "data" / "models"


def _import_runtime():
    import sys

    if str(DEPLOY_SRC) not in sys.path:
        sys.path.insert(0, str(DEPLOY_SRC))
    from tcn_server import TCNRuntime  # type: ignore

    return TCNRuntime


def _artifact_dir() -> Path:
    if (ARTIFACTS / "temporal_horizon_event_6h.pt").exists():
        return ARTIFACTS
    if (MODELS / "temporal_horizon_event_6h.pt").exists():
        return MODELS
    pytest.skip("Artefatos TCN ausentes — rode run_temporal_training.py")


def test_tcn_runtime_loads_and_predicts():
    TCNRuntime = _import_runtime()
    base = _artifact_dir()
    rt = TCNRuntime()
    rt.load(base)
    assert rt.loaded
    assert len(rt.models) == 3

    n_features = int(rt.meta.get("n_features", 24))
    seq = np.zeros((32, n_features), dtype=np.float32)
    # sequência estável (baseline) — deve retornar estrutura válida
    pred = rt.predict_one(seq)
    for key in (
        "prob_6h",
        "prob_24h",
        "prob_72h",
        "max_probability",
        "horizon_at_risk",
        "conformal_intervals",
        "alerta",
    ):
        assert key in pred
    assert 0.0 <= pred["prob_6h"] <= 1.0
    assert 0.0 <= pred["prob_24h"] <= 1.0
    assert 0.0 <= pred["prob_72h"] <= 1.0
    assert pred["horizon_at_risk"] in ("6h", "24h", "72h")
    assert set(pred["conformal_intervals"].keys()) == {"6h", "24h", "72h"}
    assert isinstance(pred["alerta"], bool)


def test_extract_sequence_shapes():
    TCNRuntime = _import_runtime()
    seq = np.random.randn(32, 24).astype(np.float32)
    out = TCNRuntime.extract_sequence({"sequence": seq.tolist()})
    assert out is not None
    assert out.shape == (32, 24)

    bad = TCNRuntime.extract_sequence({"foo": 1})
    assert bad is None

    batch = TCNRuntime.extract_sequence({"sequences": [seq.tolist()]})
    assert batch is not None
    assert batch.shape == (32, 24)


def test_package_artifacts_copies_required(tmp_path, monkeypatch):
    """package_artifacts deve falhar se faltar .pt; com modelos reais empacota."""
    import sys

    if str(DEPLOY_SRC) not in sys.path:
        sys.path.insert(0, str(DEPLOY_SRC))
    import deploy_tcn_custom as dep  # type: ignore

    if not (MODELS / "temporal_horizon_event_6h.pt").exists():
        pytest.skip("Modelos TCN ausentes")

    # redireciona ARTIFACTS para tmp
    monkeypatch.setattr(dep, "ARTIFACTS", tmp_path / "arts")
    arts = dep.package_artifacts()
    assert (arts / "temporal_horizon_event_6h.pt").exists()
    assert (arts / "temporal_horizon_event_24h.pt").exists()
    assert (arts / "temporal_horizon_event_72h.pt").exists()
    assert (arts / "temporal_scaler.pkl").exists() or (arts / "temporal_scaler.json").exists()
    assert (arts / "manifest.json").exists()
    manifest = (arts / "manifest.json").read_text()
    assert "tcn_per_horizon" in manifest
