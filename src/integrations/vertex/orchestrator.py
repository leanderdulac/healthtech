import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator, PipelineResult
from src.datalake.utils.telemetry_simulator import SimulationConfig
from src.integrations.vertex.batch_pipeline import VertexBatchPipeline
from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.export import VertexDataExporter
from src.integrations.vertex.feature_builder import DatalakeFeatureBuilder
from src.integrations.vertex.local_model import LocalAnomalyModel
from src.integrations.vertex.online_pipeline import VertexOnlinePipeline
from src.integrations.vertex.training_pipeline import VertexTrainingPipeline
from src.integrations.bigquery_bridge import BigQueryBridge
from src.ontology.fhir_bridge import OntologyFhirBridge
from src.ontology.registry import MedicalOntologyRegistry
from src.ontology.sync import sync_ontology_to_project

logger = logging.getLogger(__name__)


@dataclass
class VertexIntegrationResult:
    datalake: Optional[PipelineResult] = None
    training: Dict = field(default_factory=dict)
    online: List[Dict] = field(default_factory=list)
    batch: Dict = field(default_factory=dict)
    bigquery: Dict = field(default_factory=dict)
    ontology: Dict = field(default_factory=dict)
    hemodynamics: Dict = field(default_factory=dict)
    clinical_intelligence: Dict = field(default_factory=dict)
    production: Dict = field(default_factory=dict)
    exports: Dict = field(default_factory=dict)


class VertexIntegrationOrchestrator:
    """
    Orquestrador unificado: Datalake → Features → Vertex AI.

    Fluxo completo:
      1. Pipeline datalake (Bronze → Silver → Gold)
      2. Treinamento (local + Vertex CustomTraining)
      3. Inferência online (stream vitals → Endpoint)
      4. Inferência batch (coorte → JSONL → Batch Prediction)
    """

    def __init__(
        self,
        lakehouse_config: Optional[LakehouseConfig] = None,
        vertex_config: Optional[VertexConfig] = None,
    ):
        self.lakehouse_config = lakehouse_config or LakehouseConfig()
        self.vertex_config = vertex_config or VertexConfig()
        self.vertex_config.ensure_directories()

        self.datalake = DatalakeOrchestrator(self.lakehouse_config)
        self.feature_builder = DatalakeFeatureBuilder(self.datalake.query_engine)
        self.exporter = VertexDataExporter(self.vertex_config)
        self.local_model = LocalAnomalyModel(self.vertex_config.local_model_dir)

        self.training_pipeline = VertexTrainingPipeline(
            self.vertex_config, self.feature_builder, self.exporter, self.local_model,
        )
        self.online_pipeline = VertexOnlinePipeline(
            self.vertex_config, self.feature_builder, self.local_model,
        )
        self.batch_pipeline = VertexBatchPipeline(
            self.vertex_config, self.feature_builder, self.exporter, self.local_model,
        )
        self.bigquery_bridge = BigQueryBridge(
            self.datalake.store, self.vertex_config.project_id,
        )

    def run_full_integration(
        self,
        simulation_config: Optional[SimulationConfig] = None,
        start_time: Optional[datetime] = None,
        online_max_records: int = 15,
    ) -> VertexIntegrationResult:
        result = VertexIntegrationResult()

        logger.info("=== FASE 1: Pipeline Datalake ===")
        result.datalake = self.datalake.run_full_pipeline(
            simulation_config=simulation_config,
            start_time=start_time,
        )

        partition_dates = result.datalake.partition_dates
        sample_patient = result.datalake.patients[0] if result.datalake.patients else None

        logger.info("=== FASE 2: Treinamento ===")
        result.training = self.training_pipeline.run_training(partition_dates=partition_dates)

        if sample_patient and partition_dates:
            logger.info("=== FASE 3: Inferência Online ===")
            result.online = self.online_pipeline.stream_patient_vitals(
                patient_id=sample_patient,
                partition_date=partition_dates[0],
                max_records=online_max_records,
                delay_seconds=0.05,
            )

        logger.info("=== FASE 4: Inferência Batch ===")
        result.batch = self.batch_pipeline.run_batch_prediction(
            min_risk_score=0.2,
            partition_dates=partition_dates,
        )

        logger.info("=== FASE 5: Sync BigQuery + FHIR ===")
        result.bigquery = self.bigquery_bridge.sync_all(
            partition_dates=partition_dates,
            patient_profiles=result.datalake.patient_profiles,
        )

        logger.info("=== FASE 6: Ontologia Médica ===")
        result.ontology = self._integrate_ontology()

        logger.info("=== FASE 7: Hemodinâmica (grad/div/curl) ===")
        result.hemodynamics = self._run_hemodynamics_analysis()

        logger.info("=== FASE 8: Inteligência Clínica Preditiva ===")
        result.clinical_intelligence = self._run_clinical_prediction(result)

        logger.info("=== FASE 9: Framework de Produção (F17) ===")
        result.production = self._run_production_framework(result)

        result.exports = {
            "training_csv": result.training.get("csv_path"),
            "batch_jsonl": result.batch.get("jsonl_path"),
            "batch_predictions": result.batch.get("local_predictions_path"),
            "model_path": str(self.vertex_config.local_model_dir / "anomaly_detector.pkl"),
            "fhir_bundle": (result.datalake.fhir_export or {}).get("bundle_path"),
            "fhir_ndjson": (result.datalake.fhir_export or {}).get("ndjson_path"),
            "ontology": result.ontology.get("canonical_path"),
            "ontology_codesystem": result.ontology.get("codesystem_path"),
            "hemodynamics": result.hemodynamics.get("output_dir"),
            "clinical_intelligence": result.clinical_intelligence.get("output_dir"),
            "production": result.production,
            "clinical_validation": result.production.get("validation", {}).get("report_path"),
            "conformal_calibration": result.production.get("conformal", {}).get("path"),
        }

        return result

    def _run_production_framework(self, result: VertexIntegrationResult) -> Dict:
        from src.integrations.production.orchestrator import ProductionOrchestrator

        prod = ProductionOrchestrator(
            lakehouse_config=self.lakehouse_config,
            vertex_config=self.vertex_config,
        )
        patient_ids = result.datalake.patients if result.datalake else []
        prod_result = prod.run_production_pipeline(
            patient_ids=patient_ids,
            run_ingestion=True,
            run_clinical_sync=True,
            run_conformal=True,
            run_validation=True,
            run_vertex_deploy=False,
            use_simulated_datalake_if_empty=False,
        )
        return prod_result.to_dict()

    def _run_clinical_prediction(self, result: VertexIntegrationResult) -> Dict:
        from src.clinical_intelligence.pipeline import ClinicalIntelligencePipeline
        from src.clinical_intelligence.storage import ClinicalIntelligenceStorage

        if not result.datalake or not result.datalake.patient_profiles:
            return {"status": "SKIPPED", "reason": "no_patient_profiles"}

        pipeline = ClinicalIntelligencePipeline()
        storage = ClinicalIntelligenceStorage()

        hemo_scores = {}
        for s in result.hemodynamics.get("summaries", []):
            if s.get("irregularities", 0) > 0:
                hemo_scores[s.get("patient_id", "")] = min(
                    1.0, s["irregularities"] / 6.0,
                )

        ci_results = pipeline.analyze_from_profiles(
            query_engine=self.datalake.query_engine,
            patient_profiles=result.datalake.patient_profiles,
            partition_dates=result.datalake.partition_dates,
            hemodynamic_scores=hemo_scores,
        )

        paths = [storage.save_result(r) for r in ci_results]
        summary_path = storage.save_batch_summary(ci_results) if ci_results else ""

        return {
            "status": "INTEGRATED",
            "patients_analyzed": len(ci_results),
            "active_predictions": sum(1 for r in ci_results if r.predictions),
            "output_dir": str(storage.output_dir),
            "artifact_paths": paths + ([summary_path] if summary_path else []),
            "top_predictions": [
                {
                    "patient_id": r.patient_id,
                    "fusion_score": r.fusion_score,
                    "event": r.predictions[0].event_type if r.predictions else None,
                    "probability": r.predictions[0].probability if r.predictions else 0,
                    "lead_time_hours": r.predictions[0].lead_time_hours if r.predictions else 0,
                }
                for r in ci_results
            ],
        }

    def _run_hemodynamics_analysis(self) -> Dict:
        from src.hemodynamics.alerts import HemodynamicsAlertGenerator
        from src.hemodynamics.analyzer import VascularFlowAnalyzer
        from src.hemodynamics.simulator import VascularFlowSimulator
        from src.hemodynamics.storage import HemodynamicsStorage

        simulator = VascularFlowSimulator(nx=40, ny=24, nz=24, spacing=0.5)
        analyzer = VascularFlowAnalyzer()
        alert_gen = HemodynamicsAlertGenerator()
        storage = HemodynamicsStorage()

        scenarios = list(VascularFlowSimulator.SCENARIOS)
        summaries = []
        artifact_paths = []

        for scenario in scenarios:
            pressure, velocity = simulator.simulate(scenario)
            analysis = analyzer.analyze(
                pressure=pressure,
                velocity=velocity,
                patient_id=f"PAT-HEMO-{scenario[:4].upper()}",
                scenario=scenario,
            )
            summary = alert_gen.summary(analysis)
            flags = alert_gen.generate_fhir_flags(analysis)
            paths = storage.save_analysis(analysis, summary)
            fhir_path = storage.save_fhir_flags(flags, scenario)
            summaries.append(summary)
            artifact_paths.extend([paths["analysis"], paths["summary"], fhir_path])

        return {
            "status": "INTEGRATED",
            "scenarios": scenarios,
            "summaries": summaries,
            "total_irregularities": sum(s["irregularities"] for s in summaries),
            "output_dir": str(storage.output_dir),
            "artifact_paths": artifact_paths,
        }

    def _integrate_ontology(self) -> Dict:
        sync = sync_ontology_to_project()
        registry = MedicalOntologyRegistry()
        if not registry.load():
            return {"status": "NOT_AVAILABLE", "sync": sync}

        bridge = OntologyFhirBridge(registry)
        codesystem = bridge.build_codesystem()

        import json
        from pathlib import Path
        cs_path = Path("data/ontology/fhir_codesystem.json")
        cs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cs_path, "w", encoding="utf-8") as f:
            json.dump(codesystem, f, indent=2, ensure_ascii=False)

        return {
            "status": "INTEGRATED",
            "sync": sync,
            "canonical_path": str(registry.ontology_path),
            "codesystem_path": str(cs_path),
            "statistics": registry.statistics,
            "top_keywords": registry.get_top_keywords(10),
            "domains_available": list(registry.domain_scores("telemedicina cardiovascular").keys()),
        }