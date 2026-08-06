"""
api_server.py — Entry point da plataforma full.

Delega para a factory `saude_responsiva_secure` com APP_MODE=full
(dashboard, WebSocket, phantom/Vertex, middlewares de segurança).

Uso:
  uvicorn src.api_server:app --port 8080
  # equivalente a:
  APP_MODE=full uvicorn app.main:app --port 8080
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Project root + pacote secure no PYTHONPATH
_ROOT = Path(__file__).resolve().parents[1]
_SECURE = _ROOT / "saude_responsiva_secure"
for _p in (str(_ROOT), str(_SECURE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Monólito completo por padrão neste entry point
os.environ.setdefault("APP_MODE", "full")

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

get_settings.cache_clear()
app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
