"""
Health Data Aggregator API

Uso:
  cd health-aggregator
  uvicorn main:app --reload --port 8000

Segurança:
  - Header X-API-Key quando API_KEY estiver definida (obrigatório em produção)
  - AUTH_DISABLED=true apenas em desenvolvimento
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# Raiz do monorepo Healthtech para auth compartilhado
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import models  # noqa: F401 — registra tabelas no Base
import crud
import schemas
from aggregator import HealthAggregator
from database import Base, engine, get_db
from schemas import DailyAggregate, HealthRecordCreate
from src.security.auth import (
    cors_allow_credentials,
    get_cors_origins,
    require_api_key,
    validate_secret_salt,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Health Data Aggregator API",
    version="1.1.0",
    description="Agregação multimodal de telemetria wearable + FHIR + TCN.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins() or ["http://localhost:8000"],
    allow_credentials=cors_allow_credentials(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*", "X-API-Key"],
)

# Schema: preferir Alembic em produção; create_all apenas como bootstrap de dev
Base.metadata.create_all(bind=engine)


@app.on_event("startup")
async def _startup_security_checks() -> None:
    validate_secret_salt(raise_in_production=True)
    logger.info("Health Aggregator iniciado (CORS origins=%s)", get_cors_origins())


@app.post("/ingest/")
async def ingest_records(
    records: list[HealthRecordCreate],
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(require_api_key),
):
    """Recebe dados de qualquer fonte e normaliza."""
    if len(records) > 5000:
        raise HTTPException(413, detail="Máximo de 5000 registros por request.")
    for record in records:
        HealthAggregator.normalize_and_save(
            db,
            [record.model_dump()],
            record.source,
            record.user_id,
        )
    return {"status": "success", "ingested": len(records)}


@app.get("/aggregate/daily/{user_id}", response_model=list[DailyAggregate])
async def get_aggregate(
    user_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(require_api_key),
):
    if not start_date:
        start_date = datetime.now(timezone.utc) - timedelta(days=30)
    if not end_date:
        end_date = datetime.now(timezone.utc)

    rows = HealthAggregator.get_daily_aggregate(db, user_id, start_date, end_date)
    return HealthAggregator.daily_to_schema(rows)


@app.get("/health")
async def health_check():
    """Endpoint público (sem API key) para probes de orquestradores."""
    return {"status": "healthy", "service": "Health Aggregator"}


# --- Endpoints estendidos (integração Healthtech) ---

@app.post("/records", response_model=schemas.HealthRecordResponse)
async def create_record_endpoint(
    payload: HealthRecordCreate,
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(require_api_key),
):
    return crud.create_record(db, crud.record_from_schema(payload))


@app.get("/records/{user_id}", response_model=List[schemas.HealthRecordResponse])
async def get_records(
    user_id: str,
    source: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(require_api_key),
):
    limit = min(max(limit, 1), 1000)
    return crud.list_records(db, user_id, source=source, date=date, limit=limit)


@app.post("/aggregate", response_model=schemas.UserHealthSummary)
async def run_full_aggregation(
    payload: schemas.AggregateRequest,
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(require_api_key),
):
    """Pipeline completo: Apple/Google/BLE + FHIR + TCN."""
    agg = HealthAggregator(db)
    try:
        return agg.aggregate(payload)
    except Exception as e:
        logger.exception("Agregação falhou")
        raise HTTPException(500, detail=str(e)) from e


@app.get("/runs", response_model=List[schemas.AggregationRunRead])
async def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    _api_key: Optional[str] = Depends(require_api_key),
):
    limit = min(max(limit, 1), 100)
    return [crud.run_to_schema(r) for r in crud.list_runs(db, limit=limit)]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
