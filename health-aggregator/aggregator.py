"""
Motor de agregação — normalização, persistência e agregação diária com pandas.
"""

import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

import crud
import schemas
from models import HealthRecord

logger = logging.getLogger(__name__)

HEALTHTECH_ROOT = Path(__file__).resolve().parent.parent


def _ensure_healthtech_path() -> bool:
    root = str(HEALTHTECH_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return (HEALTHTECH_ROOT / "src").exists()


class HealthAggregator:

    @staticmethod
    def normalize_and_save(db: Session, records: list[dict], source: str, user_id: str):
        for rec in records:
            ts = rec.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts is None:
                ts = datetime.utcnow()

            record = HealthRecord(
                user_id=user_id,
                source=crud.normalize_source(source),
                timestamp=ts,
                date=ts.strftime("%Y-%m-%d"),
                steps=rec.get("steps", 0),
                heart_rate_bpm=rec.get("heart_rate_bpm"),
                hrv=rec.get("hrv"),
                spo2=rec.get("spo2"),
                calories_burned=rec.get("calories_burned", 0),
                sleep_duration_min=rec.get("sleep_duration_min", 0),
                weight=rec.get("weight"),
                body_fat=rec.get("body_fat"),
                raw_data=rec,
            )
            db.add(record)
        db.commit()

    @staticmethod
    def get_daily_aggregate(
        db: Session,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        records = db.query(HealthRecord).filter(
            HealthRecord.user_id == user_id,
            HealthRecord.date.between(
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            ),
        ).all()

        if not records:
            return []

        df = pd.DataFrame([{
            "date": r.date,
            "steps": r.steps,
            "heart_rate_bpm": r.heart_rate_bpm,
            "calories_burned": r.calories_burned,
            "spo2": r.spo2,
            "sleep_duration_min": r.sleep_duration_min,
        } for r in records])

        daily = df.groupby("date").agg({
            "steps": "sum",
            "heart_rate_bpm": "mean",
            "calories_burned": "sum",
            "spo2": "mean",
            "sleep_duration_min": "sum",
        }).round(2).reset_index()

        daily["overall_score"] = daily.apply(
            lambda x: round((
                min(100, x["steps"] / 10000 * 100) +
                min(100, x["sleep_duration_min"] / 480 * 100) +
                (100 - abs((x["heart_rate_bpm"] or 70) - 70) * 1.5)
            ) / 3, 1),
            axis=1,
        )

        return daily.to_dict(orient="records")

    @staticmethod
    def daily_to_schema(rows: list[dict]) -> List[schemas.DailyAggregate]:
        return [
            schemas.DailyAggregate(
                date=row["date"],
                total_steps=int(row["steps"]),
                avg_heart_rate=float(row["heart_rate_bpm"] or 0),
                total_calories=float(row["calories_burned"] or 0),
                avg_spo2=float(row["spo2"] or 0),
                total_sleep_min=int(row["sleep_duration_min"] or 0),
                overall_score=float(row["overall_score"]),
            )
            for row in rows
        ]

    DEFAULT_SOURCES = ["apple_health", "google_fit", "ble"]

    def __init__(self, db: Session):
        self.db = db
        self.healthtech_available = _ensure_healthtech_path()

    def aggregate(self, request: schemas.AggregateRequest) -> schemas.UserHealthSummary:
        user_id = request.user_id
        sources = request.sources or self.DEFAULT_SOURCES
        if request.sync_clinical and "fhir" not in sources:
            sources = sources + ["fhir"]
        if request.run_prediction and "tcn" not in sources:
            sources = sources + ["tcn"]

        run = crud.create_aggregation_run(self.db, user_id, sources)
        detail: Dict = {}
        saved_count = 0
        user_ids: List[str] = []

        try:
            if any(s in sources for s in self.DEFAULT_SOURCES):
                ingest = self._run_ingestion(user_id, sources, request.run_silver_gold)
                detail["ingestion"] = ingest
                for uid, recs in ingest.get("records_by_user", {}).items():
                    for source, batch in recs.items():
                        self.normalize_and_save(self.db, batch, source, uid)
                        saved_count += len(batch)
                user_ids.extend(ingest.get("users", []))

            if not user_ids and user_id:
                user_ids = [user_id]

            if "fhir" in sources:
                detail["clinical"] = self._sync_clinical(user_ids or [user_id])

            if "tcn" in sources and request.run_prediction:
                detail["prediction"] = self._run_prediction(user_ids)

            primary = (user_ids or [user_id or "UNKNOWN"])[0]
            summary = self.build_summary(primary, sources)

            crud.finish_aggregation_run(
                self.db, run.id, "completed", saved_count, detail,
            )
            return summary

        except Exception as e:
            logger.exception("Agregação falhou")
            crud.finish_aggregation_run(
                self.db, run.id, "failed", saved_count, {"error": str(e), **detail},
            )
            raise

    def build_summary(
        self,
        user_id: str,
        sources: Optional[List[str]] = None,
        days: int = 30,
    ) -> schemas.UserHealthSummary:
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        daily_rows = self.get_daily_aggregate(self.db, user_id, start, end)
        daily = self.daily_to_schema(daily_rows)

        records = crud.list_records(self.db, user_id, limit=500)
        latest_metrics: Dict[str, float] = {}
        for row in records:
            if row.heart_rate_bpm and "heart_rate_bpm" not in latest_metrics:
                latest_metrics["heart_rate_bpm"] = row.heart_rate_bpm
            if row.spo2 and "spo2" not in latest_metrics:
                latest_metrics["spo2"] = row.spo2
            if row.hrv and "hrv" not in latest_metrics:
                latest_metrics["hrv"] = row.hrv
            if row.steps and "steps" not in latest_metrics:
                latest_metrics["steps"] = float(row.steps)

        clinical_row = crud.latest_by_source(self.db, user_id, "fhir")
        prediction_row = crud.latest_by_source(self.db, user_id, "tcn")

        return schemas.UserHealthSummary(
            user_id=user_id,
            record_count=len(records),
            latest_metrics=latest_metrics,
            sources=sources or list({r.source for r in records}),
            clinical=clinical_row.raw_data if clinical_row else None,
            prediction=prediction_row.raw_data if prediction_row else None,
            daily=daily,
            aggregated_at=datetime.now(timezone.utc),
        )

    def _run_ingestion(
        self,
        user_id: Optional[str],
        sources: List[str],
        run_silver_gold: bool,
    ) -> Dict:
        if not self.healthtech_available:
            return self._stub_ingestion(user_id, sources)

        from src.ingestion.real.orchestrator import RealIngestionOrchestrator

        wearable_sources = [s for s in sources if s in ("apple_health", "google_fit", "ble")]
        if not wearable_sources:
            return {"records_by_user": {}, "users": []}

        orchestrator = RealIngestionOrchestrator(sources=wearable_sources)
        collection = orchestrator.collect_all(patient_id=user_id)
        all_records = collection.get("records", [])

        if all_records and run_silver_gold:
            orchestrator.datalake.run_from_bronze(all_records)
        elif all_records:
            orchestrator.ingestor.ingest_stream(all_records)

        telemetry_rows = []
        for rec in all_records:
            telemetry_rows.append({
                "patient_id": rec.patient_id,
                "source": rec.source.value if hasattr(rec.source, "value") else str(rec.source),
                "metric_type": rec.metric_type.value if hasattr(rec.metric_type, "value") else str(rec.metric_type),
                "metric_value": rec.metric_value,
                "vendor": rec.vendor,
                "timestamp_utc": rec.timestamp_utc,
            })

        buckets = crud.telemetry_rows_to_health_records(telemetry_rows)
        records_by_user: Dict[str, Dict[str, list]] = {}

        for bucket in buckets:
            uid = bucket["user_id"]
            source = bucket["source"]
            rec = {
                "timestamp": bucket["timestamp"],
                "steps": bucket.get("steps", 0),
                "heart_rate_bpm": bucket.get("heart_rate_bpm"),
                "hrv": bucket.get("hrv"),
                "spo2": bucket.get("spo2"),
                "calories_burned": bucket.get("calories_burned", 0),
                "sleep_duration_min": bucket.get("sleep_duration_min", 0),
                "weight": bucket.get("weight"),
                "body_fat": bucket.get("body_fat"),
            }
            records_by_user.setdefault(uid, {}).setdefault(source, []).append(rec)

        users = list(records_by_user.keys())
        return {
            "collected": len(all_records),
            "users": users,
            "records_by_user": records_by_user,
            "source_results": collection.get("sources", {}),
        }

    def _sync_clinical(self, user_ids: List[Optional[str]]) -> Dict:
        if not self.healthtech_available:
            return {"status": "stub", "users": 0}

        from src.integrations.clinical.clinical_bridge import ClinicalDataBridge
        from src.integrations.clinical.config import ClinicalIntegrationConfig

        config = ClinicalIntegrationConfig(
            local_cache_dir=str(HEALTHTECH_ROOT / "data" / "clinical_cache"),
        )
        bridge = ClinicalDataBridge(config=config)
        synced = {}

        for uid in user_ids:
            if not uid:
                continue
            try:
                baseline = bridge.sync_patient(uid)
                now = datetime.now(timezone.utc)
                self.normalize_and_save(self.db, [{
                    "timestamp": now,
                    "raw_data": {
                        "conditions": baseline.clinical_conditions,
                        "medications": baseline.medications,
                        "risk_factor": baseline.risk_factor,
                        "fhir_live": bridge.client.is_live,
                    },
                }], "fhir", uid)
                synced[uid] = baseline.clinical_conditions
            except Exception as e:
                logger.warning("FHIR sync falhou para %s: %s", uid, e)

        return {"status": "ok", "users": len(synced), "baselines": synced}

    def _run_prediction(self, user_ids: List[str]) -> Dict:
        if not self.healthtech_available:
            return {"status": "stub"}

        from src.clinical_intelligence.temporal_features import TemporalFeatureBuilder
        from src.clinical_intelligence.temporal_model import TemporalModelWrapper
        from src.datalake.config import LakehouseConfig
        from src.datalake.extraction.filters import QueryFilters
        from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
        from src.ingestion.real.profile_factory import profiles_from_ids

        model_dir = HEALTHTECH_ROOT / "data" / "models"
        if not (model_dir / "temporal_horizon_event_6h.pt").exists():
            return {"status": "skipped", "reason": "tcn_models_missing"}

        wrapper = TemporalModelWrapper(model_dir)
        builder = TemporalFeatureBuilder(seq_len=32, subsample=30, feature_stride=4)
        datalake = DatalakeOrchestrator(LakehouseConfig())

        predictions = {}
        for uid in user_ids:
            vitals = datalake.query_engine.extract("vitals", QueryFilters(patient_id=uid))
            if vitals.empty:
                continue
            profiles = profiles_from_ids([uid])
            baseline = builder.pipeline._profile_to_baseline(profiles[0])
            X, _ = builder.build_patient_sequences(vitals, baseline)
            if len(X) == 0:
                continue
            pred = wrapper.predict_single(X[-1])
            now = datetime.now(timezone.utc)
            self.normalize_and_save(self.db, [{
                "timestamp": now,
                "raw_data": pred,
            }], "tcn", uid)
            predictions[uid] = pred

        return {"status": "ok", "predictions": predictions}

    @staticmethod
    def _stub_ingestion(user_id: Optional[str], sources: List[str]) -> Dict:
        uid = user_id or "PAT-STUB-001"
        now = datetime.now(timezone.utc)
        rec = {
            "timestamp": now,
            "heart_rate_bpm": 72.0,
            "spo2": 97.0,
        }
        return {
            "collected": 1,
            "users": [uid],
            "records_by_user": {uid: {"samsung": [rec]}},
            "source_results": {s: {"status": "stub"} for s in sources},
        }