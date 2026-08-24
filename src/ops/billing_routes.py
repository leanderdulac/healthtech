"""Rotas REST do faturamento GCP simulado."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.ops.gcp_billing_sim import load_ledger


def register_billing_routes(app: FastAPI) -> None:
    @app.get("/api/v1/billing/overview")
    def billing_overview():
        return JSONResponse(load_ledger())
