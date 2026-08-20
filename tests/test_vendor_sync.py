"""Garante que o subset vendido na imagem secure não fique defasado."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_secure_vendor.py"


def test_vendor_src_matches_monorepo_clinical_intelligence():
    assert SCRIPT.is_file()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
