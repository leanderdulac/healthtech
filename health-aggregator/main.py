"""
Health Data Aggregator API

Uso:
  cd health-aggregator
  uvicorn main:app --reload --port 8000
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

import models  # noqa: F401 — registra tabelas no Base
import crud
import schemas
from aggregator import HealthAggregator
from database import Base, engine, get_db
from models import AggregationRun
from schemas import DailyAggregate, HealthRecordCreate

app = FastAPI(title="Health Data Aggregator API")

Base.metadata.create_all(bind=engine)


@app.post("/ingest/")
async def ingest_records(records: list[HealthRecordCreate], db: Session = Depends(get_db)):
    """Recebe dados de qualquer fonte e normaliza."""
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
):
    if not start_date:
        start_date = datetime.now() - timedelta(days=30)
    if not end_date:
        end_date = datetime.now()

    rows = HealthAggregator.get_daily_aggregate(db, user_id, start_date, end_date)
    return HealthAggregator.daily_to_schema(rows)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Health Aggregator"}


# --- Endpoints estendidos (integração Healthtech) ---

@app.post("/records", response_model=schemas.HealthRecordResponse)
async def create_record_endpoint(
    payload: HealthRecordCreate,
    db: Session = Depends(get_db),
):
    return crud.create_record(db, crud.record_from_schema(payload))


@app.get("/records/{user_id}", response_model=List[schemas.HealthRecordResponse])
async def get_records(
    user_id: str,
    source: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return crud.list_records(db, user_id, source=source, date=date, limit=limit)


@app.post("/aggregate", response_model=schemas.UserHealthSummary)
async def run_full_aggregation(
    payload: schemas.AggregateRequest,
    db: Session = Depends(get_db),
):
    """Pipeline completo: Apple/Google/BLE + FHIR + TCN."""
    agg = HealthAggregator(db)
    try:
        return agg.aggregate(payload)
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@app.get("/runs", response_model=List[schemas.AggregationRunRead])
async def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    return [crud.run_to_schema(r) for r in crud.list_runs(db, limit=limit)]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)