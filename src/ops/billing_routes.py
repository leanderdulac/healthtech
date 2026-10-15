"""Rotas REST do faturamento GCP.

A rota fica fechada. O orçamento simulado não sai por HTTP.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.ops.gcp_billing_sim import load_ledger


def register_billing_routes(app: FastAPI) -> None:
    @app.get("/api/v1/billing/overview")
    def billing_overview():
        if os.environ.get("HEALTHTECH_BILLING_SIM") != "1":
            return JSONResponse({"available": False}, status_code=404)
        try:
            return JSONResponse(load_ledger())
        except FileNotFoundError:
            return JSONResponse({"available": False}, status_code=404)
