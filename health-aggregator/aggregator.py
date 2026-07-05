"""
Motor de agregação — unifica wearables, FHIR clínico e predição TCN do Healthtech.
"""

import json
import logging
import sys
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
    """Coleta multi-fonte, persiste no SQLite e retorna visão unificada do paciente."""

    DEFAULT_SOURCES = ["apple_health", "google_fit", "ble"]

    def __init__(self, db: Session):
        self.db = db
        self.healthtech_available = _ensure_healthtech_path()

    def aggregate(
        self,
        request: schemas.AggregateRequest,
    ) -> schemas.PatientHealthSummary:
        sources = request.sources or self.DEFAULT_SOURCES
        if request.sync_clinical and "fhir" not in sources:
            sources = sources + ["fhir"]
        if request.run_prediction and "tcn" not in sources:
            sources = sources + ["tcn"]

        run = crud.create_aggregation_run(self.db, request.patient_id, sources)
        detail: Dict = {"sources": {}}
        telemetry_rows: List[Dict] = []
        patient_ids: List[str] = []

        try:
            if any(s in sources for s in self.DEFAULT_SOURCES):
                ingest = self._run_ingestion(request.patient_id, sources, request.run_silver_gold)
                detail["ingestion"] = ingest
                telemetry_rows.extend(ingest.get("telemetry_rows", []))
                patient_ids.extend(ingest.get("patients", []))

            if not patient_ids and request.patient_id:
                patient_ids = [request.patient_id]

            for pid in set(patient_ids):
                crud.create_patient(self.db, schemas.PatientCreate(patient_id=pid))

            if telemetry_rows:
                crud.bulk_insert_telemetry(self.db, telemetry_rows)

            clinical_data = None
            if "fhir" in sources:
                clinical_data = self._sync_clinical(patient_ids or [request.patient_id])
                detail["clinical"] = clinical_data

            prediction_data = None
            if "tcn" in sources and request.run_prediction:
                prediction_data = self._run_prediction(patient_ids)
                detail["prediction"] = prediction_data

            primary = (patient_ids or [request.patient_id or "UNKNOWN"])[0]
            summary = self.build_summary(primary, sources)

            crud.finish_aggregation_run(
                self.db, run.id, "completed", len(telemetry_rows), detail,
            )
            return summary

        except Exception as e:
            logger.exception("Agregação falhou")
            crud.finish_aggregation_run(
                self.db, run.id, "failed", len(telemetry_rows), {"error": str(e), **detail},
            )
            raise

    def build_summary(
        self,
        patient_id: str,
        sources: Optional[List[str]] = None,
    ) -> schemas.PatientHealthSummary:
        patient = crud.get_patient(self.db, patient_id)
        telemetry = crud.list_telemetry(self.db, patient_id, limit=500)
        clinical = crud.latest_clinical(self.db, patient_id)
        prediction = crud.latest_prediction(self.db, patient_id)

        latest_metrics: Dict[str, float] = {}
        for row in telemetry:
            if row.metric_type not in latest_metrics:
                latest_metrics[row.metric_type] = row.metric_value

        return schemas.PatientHealthSummary(
            patient_id=patient_id,
            display_name=patient.display_name if patient else "",
            telemetry_count=len(telemetry),
            latest_metrics=latest_metrics,
            clinical=crud.clinical_to_schema(clinical) if clinical else None,
            prediction=crud.prediction_to_schema(prediction) if prediction else None,
            sources=sources or [],
            aggregated_at=datetime.now(timezone.utc),
        )

    def _run_ingestion(
        self,
        patient_id: Optional[str],
        sources: List[str],
        run_silver_gold: bool,
    ) -> Dict:
        if not self.healthtech_available:
            return self._stub_ingestion(patient_id, sources)

        from src.ingestion.real.orchestrator import RealIngestionOrchestrator

        wearable_sources = [s for s in sources if s in ("apple_health", "google_fit", "ble")]
        if not wearable_sources:
            return {"telemetry_rows": [], "patients": []}

        orchestrator = RealIngestionOrchestrator(sources=wearable_sources)
        collection = orchestrator.collect_all(patient_id=patient_id)
        all_records = collection.get("records", [])

        if all_records and run_silver_gold:
            orchestrator.datalake.run_from_bronze(all_records)
        elif all_records:
            orchestrator.ingestor.ingest_stream(all_records)

        rows = []
        for rec in all_records:
            rows.append({
                "event_id": rec.event_id,
                "patient_id": rec.patient_id,
                "source": rec.source.value if hasattr(rec.source, "value") else str(rec.source),
                "metric_type": rec.metric_type.value if hasattr(rec.metric_type, "value") else str(rec.metric_type),
                "metric_value": rec.metric_value,
                "unit": rec.unit,
                "vendor": rec.vendor,
                "timestamp_utc": rec.timestamp_utc,
            })

        patients = list({r["patient_id"] for r in rows})

        return {
            "collected": collection.get("collected", len(rows)),
            "patients": patients,
            "telemetry_rows": rows,
            "source_results": collection.get("sources", {}),
        }

    def _sync_clinical(self, patient_ids: List[Optional[str]]) -> Dict:
        if not self.healthtech_available:
            return {"status": "stub", "patients": 0}

        from src.integrations.clinical.clinical_bridge import ClinicalDataBridge
        from src.integrations.clinical.config import ClinicalIntegrationConfig

        config = ClinicalIntegrationConfig(
            local_cache_dir=str(HEALTHTECH_ROOT / "data" / "clinical_cache"),
        )
        bridge = ClinicalDataBridge(config=config)
        synced = {}
        for pid in patient_ids:
            if not pid:
                continue
            try:
                baseline = bridge.sync_patient(pid)
            except Exception as e:
                logger.warning("FHIR sync falhou para %s: %s", pid, e)
                continue
            crud.save_clinical_snapshot(
                self.db, pid,
                baseline.clinical_conditions,
                baseline.medications,
                bridge.client.is_live,
            )
            synced[pid] = {
                "conditions": baseline.clinical_conditions,
                "medications": baseline.medications,
                "risk_factor": baseline.risk_factor,
            }
        return {"status": "ok", "patients": len(synced), "baselines": synced}

    def _run_prediction(self, patient_ids: List[str]) -> Dict:
        if not self.healthtech_available:
            return {"status": "stub"}

        from pathlib import Path as P
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
        for pid in patient_ids:
            vitals = datalake.query_engine.extract("vitals", QueryFilters(patient_id=pid))
            if vitals.empty:
                continue
            profiles = profiles_from_ids([pid])
            baseline = builder.pipeline._profile_to_baseline(profiles[0])
            X, _ = builder.build_patient_sequences(vitals, baseline)
            if len(X) == 0:
                continue
            pred = wrapper.predict_single(X[-1])
            crud.save_prediction(self.db, pid, pred)
            predictions[pid] = pred

        return {"status": "ok", "predictions": predictions}

    @staticmethod
    def _stub_ingestion(patient_id: Optional[str], sources: List[str]) -> Dict:
        pid = patient_id or "PAT-STUB-001"
        now = datetime.now(timezone.utc)
        rows = [{
            "event_id": f"stub-{pid}-hr",
            "patient_id": pid,
            "source": "stub",
            "metric_type": "heart_rate",
            "metric_value": 72.0,
            "unit": "bpm",
            "vendor": "stub",
            "timestamp_utc": now,
        }]
        return {
            "collected": 1,
            "patients": [pid],
            "telemetry_rows": rows,
            "source_results": {s: {"status": "stub"} for s in sources},
        }