"""
Health Aggregator — API REST para agregação multimodal de saúde.

Uso:
  cd health-aggregator
  uvicorn main:app --reload --port 8090
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

import crud
import schemas
from aggregator import HEALTHTECH_ROOT, HealthAggregator
from database import get_db, init_db
from models import AggregationRun, HealthRecord

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Health Aggregator iniciado — healthtech root: %s", HEALTHTECH_ROOT)
    yield


app = FastAPI(
    title="Health Aggregator",
    description="Agrega telemetria wearable (apple/google/samsung), FHIR e TCN em health_records",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=schemas.HealthResponse)
def health_check():
    return schemas.HealthResponse(
        status="ok",
        healthtech_root=str(HEALTHTECH_ROOT) if HEALTHTECH_ROOT.exists() else None,
    )


@app.get("/users", response_model=List[str])
def list_users(db: Session = Depends(get_db)):
    return crud.list_user_ids(db)


@app.post("/records", response_model=schemas.HealthRecordResponse)
def create_record(payload: schemas.HealthRecordCreate, db: Session = Depends(get_db)):
    return crud.create_health_record(db, payload)


@app.get("/records/{user_id}", response_model=List[schemas.HealthRecordResponse])
def get_records(
    user_id: str,
    source: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return crud.list_records(db, user_id, source=source, date=date, limit=limit)


@app.get("/users/{user_id}/summary", response_model=schemas.UserHealthSummary)
def get_summary(user_id: str, db: Session = Depends(get_db)):
    agg = HealthAggregator(db)
    return agg.build_summary(user_id)


@app.get("/users/{user_id}/daily", response_model=List[schemas.DailyAggregate])
def get_daily(
    user_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
):
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    rows = HealthAggregator.get_daily_aggregate(db, user_id, start, end)
    return HealthAggregator.daily_to_schema(rows)


@app.post("/aggregate", response_model=schemas.UserHealthSummary)
def run_aggregation(payload: schemas.AggregateRequest, db: Session = Depends(get_db)):
    agg = HealthAggregator(db)
    try:
        return agg.aggregate(payload)
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@app.get("/runs", response_model=List[schemas.AggregationRunRead])
def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    return [crud.run_to_schema(r) for r in crud.list_runs(db, limit=limit)]


@app.get("/runs/{run_id}", response_model=schemas.AggregationRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)):
    row = db.query(AggregationRun).filter(AggregationRun.id == run_id).first()
    if not row:
        raise HTTPException(404, "Run não encontrado")
    return crud.run_to_schema(row)