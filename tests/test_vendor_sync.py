"""Garante que o subset vendido na imagem secure não fique defasado."""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_secure_vendor.py"
VENDOR = ROOT / "saude_responsiva_secure" / "_vendor_src"
SECURE_APP = ROOT / "saude_responsiva_secure" / "app"

VENDORED_OPS = (
    "timestamps.py",
    "operational_patients.py",
    "patients_routes.py",
    "live_devices.py",
    "device_registry.py",
)
EXCLUDED_OPS = (
    "billing_routes.py",
    "gcp_billing_sim.py",
    "live_watch_bridge.py",
)

# Layout Docker: COPY _vendor_src/ → /app/src  +  COPY app/ → /app/app
# PYTHONPATH=/app  (sem o monorepo).
_SECURE_IMAGE_SMOKE = r"""
import inspect
import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("AUTH_DISABLED", "false")
os.environ.setdefault("APP_MODE", "secure")
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32c")

from src.ops.timestamps import stamp_ingest
from src.ops.operational_patients import list_patients
from src.ops.patients_routes import router as patients_router
from src.ops.device_registry import upsert_frame
from src.ops.live_devices import summarize_frame

assert callable(stamp_ingest)
assert callable(upsert_frame)
assert callable(summarize_frame)
sig = inspect.signature(list_patients)
for name in (
    "allowed_patient_ids",
    "territories",
    "require_defined_territory",
    "fail_closed_without_constraint",
):
    assert name in sig.parameters, name

route_paths = {getattr(r, "path", "") for r in patients_router.routes}
assert any(p.rstrip("/").endswith("/patients") or p.endswith("/patients") for p in route_paths), route_paths
assert any("{patient_id}" in p for p in route_paths), route_paths

from app.config import get_settings

get_settings.cache_clear()
from app.main import create_app
from fastapi.testclient import TestClient

application = create_app()
openapi_paths = set((application.openapi() or {}).get("paths") or {})
assert "/api/v1/patients" in openapi_paths, sorted(openapi_paths)
assert "/api/v1/patients/{patient_id}" in openapi_paths, sorted(openapi_paths)
assert "/api/v1/wearables/ingest" in openapi_paths, sorted(openapi_paths)

client = TestClient(application)
ingest = client.post(
    "/api/v1/wearables/ingest",
    headers={"X-API-Key": "ht_ingest_test_key_32chars_long_token"},
    json={"patient_id": "PAT-VENDOR-001", "heart_rate": 72.0},
)
assert ingest.status_code == 200, ingest.text
body = ingest.json()
assert body.get("patient_id") == "PAT-VENDOR-001"
assert body.get("timestamp")
assert body.get("received_at")

listed = client.get(
    "/api/v1/patients",
    headers={"X-API-Key": "ht_read_test_key_32chars_long_token"},
)
assert listed.status_code != 404, listed.text
assert listed.status_code == 200, listed.text
payload = listed.json()
assert payload.get("total") == 0
assert payload.get("items") == []
assert payload.get("patients") == []
print("secure-image-ops-ok")
"""


def test_vendor_src_matches_monorepo_subset():
    assert SCRIPT.is_file()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_vendor_ops_manifest_is_minimal():
    ops_dir = VENDOR / "ops"
    assert ops_dir.is_dir()
    present = {p.name for p in ops_dir.glob("*.py")}
    assert present == set(VENDORED_OPS) | {"__init__.py"}
    for name in EXCLUDED_OPS:
        assert not (ops_dir / name).is_file(), name
    assert not (VENDOR / "ops" / "billing_routes.py").is_file()


def test_secure_image_pythonpath_imports_ops_and_registers_patients(tmp_path):
    """Cópia _vendor_src → src como o Dockerfile; monorepo fora do PYTHONPATH."""
    app_root = tmp_path / "app"
    shutil.copytree(VENDOR, app_root / "src")
    shutil.copytree(SECURE_APP, app_root / "app")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(app_root)
    env["ENVIRONMENT"] = "development"
    env["AUTH_DISABLED"] = "false"
    env["APP_MODE"] = "secure"
    result = subprocess.run(
        [sys.executable, "-c", _SECURE_IMAGE_SMOKE],
        cwd=str(app_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "secure-image-ops-ok" in (result.stdout or "")
    assert "src.ops indisponível" not in (result.stderr or "")


def test_vendored_list_patients_keeps_authz_before_pagination_signature():
    """Não enfraquecer o contrato do PR #8 no subset que a imagem leva."""
    import importlib.util

    path = VENDOR / "ops" / "operational_patients.py"
    spec = importlib.util.spec_from_file_location(
        "vendor_operational_patients", path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    sig = inspect.signature(mod.list_patients)
    assert "allowed_patient_ids" in sig.parameters
    assert "fail_closed_without_constraint" in sig.parameters
    assert "require_defined_territory" in sig.parameters
