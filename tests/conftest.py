"""Path setup. O backend WEARABLE_TEST_DB vive no conftest da raiz."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
for path in (SECURE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
