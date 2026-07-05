"""
Motor de agregação — unifica wearables, FHIR clínico e predição TCN → HealthRecord.
"""

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

import crud
import schemas

logger = logging.getLogger(__name__)

HEALTHTECH_ROOT = Path(__file__).resolve().parent.parent


def _ensure_healthtech_path() -> bool:
    root = str(HEALTHTECH_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return (HEALTHTECH_ROOT / "src").exists()


class HealthAggregator:
    """Coleta multi-fonte e persiste em health_records (PostgreSQL)."""

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
        health_records: List[Dict] = []
        user_ids: List[str] = []

        try:
            if any(s in sources for s in self.DEFAULT_SOURCES):
                ingest = self._run_ingestion(user_id, sources, request.run_silver_gold)
                detail["ingestion"] = ingest
                health_records.extend(ingest.get("health_records", []))
                user_ids.extend(ingest.get("users", []))

            if not user_ids and user_id:
                user_ids = [user_id]

            if health_records:
                crud.bulk_upsert_health_records(self.db, health_records)

            if "fhir" in sources:
                detail["clinical"] = self._sync_clinical(user_ids or [user_id])

            if "tcn" in sources and request.run_prediction:
                detail["prediction"] = self._run_prediction(user_ids)

            primary = (user_ids or [user_id or "UNKNOWN"])[0]
            summary = self.build_summary(primary, sources)

            crud.finish_aggregation_run(
                self.db, run.id, "completed", len(health_records), detail,
            )
            return summary

        except Exception as e:
            logger.exception("Agregação falhou")
            crud.finish_aggregation_run(
                self.db, run.id, "failed", len(health_records), {"error": str(e), **detail},
            )
            raise

    def build_summary(
        self,
        user_id: str,
        sources: Optional[List[str]] = None,
    ) -> schemas.UserHealthSummary:
        records = crud.list_records(self.db, user_id, limit=500)
        daily = crud.daily_aggregation(self.db, user_id)

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
            return {"health_records": [], "users": []}

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
                "event_id": rec.event_id,
                "patient_id": rec.patient_id,
                "source": rec.source.value if hasattr(rec.source, "value") else str(rec.source),
                "metric_type": rec.metric_type.value if hasattr(rec.metric_type, "value") else str(rec.metric_type),
                "metric_value": rec.metric_value,
                "unit": rec.unit,
                "vendor": rec.vendor,
                "timestamp_utc": rec.timestamp_utc,
            })

        health_records = crud.telemetry_rows_to_health_records(telemetry_rows)
        users = list({r["user_id"] for r in health_records})

        return {
            "collected": len(all_records),
            "users": users,
            "health_records": health_records,
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
                record = {
                    "record_id": str(uuid.uuid4()),
                    "user_id": uid,
                    "source": "fhir",
                    "timestamp": now,
                    "date": now.strftime("%Y-%m-%d"),
                    "raw_data": {
                        "conditions": baseline.clinical_conditions,
                        "medications": baseline.medications,
                        "risk_factor": baseline.risk_factor,
                        "fhir_live": bridge.client.is_live,
                    },
                }
                crud.upsert_health_record(self.db, record)
                synced[uid] = record["raw_data"]
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
            record = {
                "record_id": str(uuid.uuid4()),
                "user_id": uid,
                "source": "tcn",
                "timestamp": now,
                "date": now.strftime("%Y-%m-%d"),
                "raw_data": pred,
            }
            crud.upsert_health_record(self.db, record)
            predictions[uid] = pred

        return {"status": "ok", "predictions": predictions}

    @staticmethod
    def _stub_ingestion(user_id: Optional[str], sources: List[str]) -> Dict:
        uid = user_id or "PAT-STUB-001"
        now = datetime.now(timezone.utc)
        rows = [{
            "patient_id": uid,
            "source": "ble",
            "vendor": "samsung",
            "metric_type": "heart_rate",
            "metric_value": 72.0,
            "timestamp_utc": now,
        }]
        health_records = crud.telemetry_rows_to_health_records(rows)
        return {
            "collected": 1,
            "users": [uid],
            "health_records": health_records,
            "source_results": {s: {"status": "stub"} for s in sources},
        }