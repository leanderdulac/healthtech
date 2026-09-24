#!/usr/bin/env bash
#
# Cloud Agent bootstrap for the HealthTech biomedical platform.
# Idempotent: safe to run repeatedly and against a cached/partial state.
set -euo pipefail

echo "==> HealthTech environment install"

# 1. System dependencies required to create a venv and build any sdist-only wheels.
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  echo "==> Installing system packages (python3-venv, build tools)"
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends \
    python3-venv python3-dev build-essential
fi

# 2. Project virtual environment.
if [ ! -x ".venv/bin/python" ]; then
  echo "==> Creating .venv"
  python3 -m venv .venv
fi

echo "==> Upgrading pip toolchain"
.venv/bin/python -m pip install --upgrade pip setuptools wheel

echo "==> Installing Python dependencies (requirements-dev.txt)"
.venv/bin/pip install -r requirements-dev.txt

# 3. Regenerate the vendored subset embedded in the secure image (CI enforces
#    this stays in sync via `sync_secure_vendor.py --check`).
echo "==> Syncing secure vendor subset"
.venv/bin/python scripts/sync_secure_vendor.py

# 4. Pre-cache the multilingual MiniLM encoder so the API server's RAG engine
#    boots quickly. Best-effort: never fail install if the model host is
#    unreachable (the engine falls back to hash-based encoding at runtime).
echo "==> Pre-caching sentence-transformers encoder (best-effort)"
.venv/bin/python - <<'PY' || echo "warn: encoder pre-cache skipped"
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    print("MiniLM encoder cached")
except Exception as exc:  # noqa: BLE001
    print(f"encoder pre-cache failed: {exc}")
PY

echo "==> HealthTech environment install complete"
