import json
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

import models
import schemas


def get_patient(db: Session, patient_id: str) -> Optional[models.Patient]:
    return db.query(models.Patient).filter(models.Patient.patient_id == patient_id).first()


def list_patients(db: Session, skip: int = 0, limit: int = 100) -> List[models.Patient]:
    return db.query(models.Patient).offset(skip).limit(limit).all()


def create_patient(db: Session, payload: schemas.PatientCreate) -> models.Patient:
    existing = get_patient(db, payload.patient_id)
    if existing:
        existing.display_name = payload.display_name or existing.display_name
        existing.birth_year = payload.birth_year or existing.birth_year
        existing.risk_factor = payload.risk_factor
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    row = models.Patient(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_patient(db: Session, patient_id: str) -> bool:
    row = get_patient(db, patient_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def bulk_insert_telemetry(
    db: Session,
    records: List[Dict],
) -> int:
    inserted = 0
    for rec in records:
        exists = db.query(models.TelemetryRecord).filter(
            models.TelemetryRecord.event_id == rec["event_id"]
        ).first()
        if exists:
            continue
        db.add(models.TelemetryRecord(**rec))
        inserted += 1
    db.commit()
    return inserted


def list_telemetry(
    db: Session,
    patient_id: str,
    limit: int = 100,
) -> List[models.TelemetryRecord]:
    return (
        db.query(models.TelemetryRecord)
        .filter(models.TelemetryRecord.patient_id == patient_id)
        .order_by(models.TelemetryRecord.timestamp_utc.desc())
        .limit(limit)
        .all()
    )


def save_clinical_snapshot(
    db: Session,
    patient_id: str,
    conditions: List[str],
    medications: List[str],
    fhir_live: bool,
) -> models.ClinicalSnapshot:
    row = models.ClinicalSnapshot(
        patient_id=patient_id,
        conditions_json=json.dumps(conditions, ensure_ascii=False),
        medications_json=json.dumps(medications, ensure_ascii=False),
        fhir_live=1 if fhir_live else 0,
        synced_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_clinical(db: Session, patient_id: str) -> Optional[models.ClinicalSnapshot]:
    return (
        db.query(models.ClinicalSnapshot)
        .filter(models.ClinicalSnapshot.patient_id == patient_id)
        .order_by(models.ClinicalSnapshot.synced_at.desc())
        .first()
    )


def save_prediction(
    db: Session,
    patient_id: str,
    prediction: Dict,
) -> models.PredictionSnapshot:
    row = models.PredictionSnapshot(
        patient_id=patient_id,
        prob_6h=prediction.get("prob_6h", 0),
        prob_24h=prediction.get("prob_24h", 0),
        prob_72h=prediction.get("prob_72h", 0),
        horizon_at_risk=prediction.get("horizon_at_risk", ""),
        conformal_json=json.dumps(prediction.get("conformal_intervals", {})),
        modo=prediction.get("modo", ""),
        predicted_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_prediction(db: Session, patient_id: str) -> Optional[models.PredictionSnapshot]:
    return (
        db.query(models.PredictionSnapshot)
        .filter(models.PredictionSnapshot.patient_id == patient_id)
        .order_by(models.PredictionSnapshot.predicted_at.desc())
        .first()
    )


def create_aggregation_run(
    db: Session,
    patient_id: Optional[str],
    sources: List[str],
) -> models.AggregationRun:
    row = models.AggregationRun(
        patient_id=patient_id,
        sources_json=json.dumps(sources),
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_aggregation_run(
    db: Session,
    run_id: int,
    status: str,
    telemetry_count: int,
    detail: Dict,
) -> models.AggregationRun:
    row = db.query(models.AggregationRun).filter(models.AggregationRun.id == run_id).first()
    if not row:
        raise ValueError(f"run {run_id} not found")
    row.status = status
    row.telemetry_count = telemetry_count
    row.detail_json = json.dumps(detail, default=str)
    row.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def list_runs(db: Session, limit: int = 20) -> List[models.AggregationRun]:
    return (
        db.query(models.AggregationRun)
        .order_by(models.AggregationRun.started_at.desc())
        .limit(limit)
        .all()
    )


def clinical_to_schema(row: models.ClinicalSnapshot) -> schemas.ClinicalSnapshotRead:
    return schemas.ClinicalSnapshotRead(
        id=row.id,
        patient_id=row.patient_id,
        conditions=json.loads(row.conditions_json or "[]"),
        medications=json.loads(row.medications_json or "[]"),
        fhir_live=bool(row.fhir_live),
        synced_at=row.synced_at,
    )


def prediction_to_schema(row: models.PredictionSnapshot) -> schemas.PredictionRead:
    return schemas.PredictionRead(
        id=row.id,
        patient_id=row.patient_id,
        prob_6h=row.prob_6h,
        prob_24h=row.prob_24h,
        prob_72h=row.prob_72h,
        horizon_at_risk=row.horizon_at_risk,
        conformal_intervals=json.loads(row.conformal_json or "{}"),
        modo=row.modo,
        predicted_at=row.predicted_at,
    )


def run_to_schema(row: models.AggregationRun) -> schemas.AggregationRunRead:
    return schemas.AggregationRunRead(
        id=row.id,
        patient_id=row.patient_id,
        sources=json.loads(row.sources_json or "[]"),
        telemetry_count=row.telemetry_count,
        status=row.status,
        detail=json.loads(row.detail_json or "{}"),
        started_at=row.started_at,
        finished_at=row.finished_at,
    )