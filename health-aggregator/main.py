"""
Health Aggregator — API REST para agregação multimodal de saúde.

Uso:
  cd health-aggregator
  uvicorn main:app --reload --port 8090
"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

import crud
import schemas
from aggregator import HEALTHTECH_ROOT, HealthAggregator
from database import get_db, init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Health Aggregator iniciado — healthtech root: %s", HEALTHTECH_ROOT)
    yield


app = FastAPI(
    title="Health Aggregator",
    description="Agrega telemetria wearable, dados clínicos FHIR e predições TCN",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=schemas.HealthResponse)
def health_check():
    return schemas.HealthResponse(
        status="ok",
        healthtech_root=str(HEALTHTECH_ROOT) if HEALTHTECH_ROOT.exists() else None,
    )


@app.get("/patients", response_model=List[schemas.PatientRead])
def list_patients(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_patients(db, skip=skip, limit=limit)


@app.post("/patients", response_model=schemas.PatientRead)
def create_patient(payload: schemas.PatientCreate, db: Session = Depends(get_db)):
    return crud.create_patient(db, payload)


@app.get("/patients/{patient_id}", response_model=schemas.PatientRead)
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    row = crud.get_patient(db, patient_id)
    if not row:
        raise HTTPException(404, f"Paciente {patient_id} não encontrado")
    return row


@app.delete("/patients/{patient_id}")
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    if not crud.delete_patient(db, patient_id):
        raise HTTPException(404, f"Paciente {patient_id} não encontrado")
    return {"status": "deleted", "patient_id": patient_id}


@app.get("/patients/{patient_id}/telemetry", response_model=List[schemas.TelemetryRead])
def get_telemetry(patient_id: str, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_telemetry(db, patient_id, limit=limit)


@app.get("/patients/{patient_id}/summary", response_model=schemas.PatientHealthSummary)
def get_summary(patient_id: str, db: Session = Depends(get_db)):
    agg = HealthAggregator(db)
    return agg.build_summary(patient_id)


@app.get("/patients/{patient_id}/clinical", response_model=schemas.ClinicalSnapshotRead)
def get_clinical(patient_id: str, db: Session = Depends(get_db)):
    row = crud.latest_clinical(db, patient_id)
    if not row:
        raise HTTPException(404, "Snapshot clínico não encontrado")
    return crud.clinical_to_schema(row)


@app.get("/patients/{patient_id}/prediction", response_model=schemas.PredictionRead)
def get_prediction(patient_id: str, db: Session = Depends(get_db)):
    row = crud.latest_prediction(db, patient_id)
    if not row:
        raise HTTPException(404, "Predição TCN não encontrada")
    return crud.prediction_to_schema(row)


@app.post("/aggregate", response_model=schemas.PatientHealthSummary)
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
    from models import AggregationRun
    row = db.query(AggregationRun).filter(AggregationRun.id == run_id).first()
    if not row:
        raise HTTPException(404, "Run não encontrado")
    return crud.run_to_schema(row)