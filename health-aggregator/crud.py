import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

import models
import schemas
from models import HealthRecord

SOURCE_MAP = {
    "apple_health": "apple",
    "apple": "apple",
    "google_fit": "google",
    "google": "google",
    "ble": "samsung",
    "samsung": "samsung",
    "fhir": "fhir",
    "tcn": "tcn",
    "stub": "samsung",
}


def normalize_source(source: str) -> str:
    return SOURCE_MAP.get(source.lower(), source.lower())


def create_record(db: Session, record: dict) -> HealthRecord:
    db_record = HealthRecord(**record)
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


def record_from_schema(payload: schemas.HealthRecordCreate) -> dict:
    data = payload.model_dump()
    data["source"] = normalize_source(data["source"])
    data["date"] = payload.timestamp.strftime("%Y-%m-%d")
    return data


def upsert_health_record(db: Session, data: Dict) -> models.HealthRecord:
    record_id = data.get("record_id")
    if record_id:
        existing = db.query(models.HealthRecord).filter(
            models.HealthRecord.record_id == record_id
        ).first()
        if existing:
            for key, val in data.items():
                if key != "id" and hasattr(existing, key) and val is not None:
                    setattr(existing, key, val)
            db.commit()
            db.refresh(existing)
            return existing

    filtered = {k: v for k, v in data.items() if hasattr(HealthRecord, k)}
    return create_record(db, filtered)


def bulk_upsert_health_records(db: Session, records: List[Dict]) -> int:
    count = 0
    for rec in records:
        upsert_health_record(db, rec)
        count += 1
    return count


def list_records(
    db: Session,
    user_id: str,
    source: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 100,
) -> List[models.HealthRecord]:
    q = db.query(models.HealthRecord).filter(models.HealthRecord.user_id == user_id)
    if source:
        q = q.filter(models.HealthRecord.source == normalize_source(source))
    if date:
        q = q.filter(models.HealthRecord.date == date)
    return q.order_by(models.HealthRecord.timestamp.desc()).limit(limit).all()


def list_user_ids(db: Session) -> List[str]:
    rows = db.query(models.HealthRecord.user_id).distinct().all()
    return [r[0] for r in rows]


def latest_by_source(db: Session, user_id: str, source: str) -> Optional[models.HealthRecord]:
    return (
        db.query(models.HealthRecord)
        .filter(
            models.HealthRecord.user_id == user_id,
            models.HealthRecord.source == normalize_source(source),
        )
        .order_by(models.HealthRecord.timestamp.desc())
        .first()
    )


def create_aggregation_run(db: Session, user_id: Optional[str], sources: List[str]) -> models.AggregationRun:
    row = models.AggregationRun(
        user_id=user_id,
        sources_json=json.dumps(sources),
        status="running",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def finish_aggregation_run(
    db: Session,
    run_id: int,
    status: str,
    records_count: int,
    detail: Dict,
) -> models.AggregationRun:
    row = db.query(models.AggregationRun).filter(models.AggregationRun.id == run_id).first()
    if not row:
        raise ValueError(f"run {run_id} not found")
    row.status = status
    row.records_count = records_count
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


def run_to_schema(row: models.AggregationRun) -> schemas.AggregationRunRead:
    return schemas.AggregationRunRead(
        id=row.id,
        user_id=row.user_id,
        sources=json.loads(row.sources_json or "[]"),
        records_count=row.records_count,
        status=row.status,
        detail=json.loads(row.detail_json or "{}"),
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def telemetry_rows_to_health_records(rows: List[Dict]) -> List[Dict]:
    """Agrupa métricas por user + source + timestamp → HealthRecord."""
    buckets: Dict[tuple, Dict] = {}

    for row in rows:
        ts = row["timestamp_utc"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        user_id = row.get("patient_id") or row.get("user_id")
        source = normalize_source(row.get("vendor") or row.get("source", "unknown"))
        date = ts.strftime("%Y-%m-%d")
        bucket_key = (user_id, source, date, ts.replace(second=0, microsecond=0))

        if bucket_key not in buckets:
            buckets[bucket_key] = {
                "record_id": f"{user_id}-{source}-{ts.isoformat()}",
                "user_id": user_id,
                "source": source,
                "timestamp": ts,
                "date": date,
                "steps": 0,
                "heart_rate_bpm": None,
                "hrv": None,
                "spo2": None,
                "calories_burned": 0,
                "sleep_duration_min": 0,
                "weight": None,
                "body_fat": None,
                "raw_data": {"events": []},
            }

        bucket = buckets[bucket_key]
        metric = row.get("metric_type", "")
        value = row.get("metric_value")

        if metric in ("heart_rate", "hr"):
            bucket["heart_rate_bpm"] = float(value)
        elif metric == "spo2":
            bucket["spo2"] = float(value)
        elif metric == "hrv":
            bucket["hrv"] = float(value)
        elif metric == "steps":
            bucket["steps"] = int(value)
        elif metric == "sleep_stage":
            bucket["sleep_duration_min"] = bucket.get("sleep_duration_min", 0) + 5

        bucket["raw_data"]["events"].append(row)

    return list(buckets.values())