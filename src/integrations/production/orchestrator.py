"""
Orquestrador de produção — F17: ingestão real, clínico FHIR, Vertex TCN,
conformal prediction e validação clínica.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.clinical_intelligence.conformal.calibrator import ConformalCalibrator
from src.clinical_intelligence.validation.validator import ClinicalValidator
from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.ingestion.real.orchestrator import RealIngestionOrchestrator
from src.integrations.clinical.clinical_bridge import ClinicalDataBridge
from src.integrations.clinical.config import ClinicalIntegrationConfig
from src.integrations.vertex.config import VertexConfig
from src.integrations.vertex.deploy.endpoint_manager import VertexTCNEndpointManager

logger = logging.getLogger(__name__)


@dataclass
class ProductionResult:
    ingestion: Dict = field(default_factory=dict)
    clinical_sync: Dict = field(default_factory=dict)
    conformal: Dict = field(default_factory=dict)
    validation: Dict = field(default_factory=dict)
    vertex_deploy: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "ingestion": self.ingestion,
            "clinical_sync": self.clinical_sync,
            "conformal": self.conformal,
            "validation": self.validation,
            "vertex_deploy": self.vertex_deploy,
        }


class ProductionOrchestrator:
    """
    Pipeline de produção unificado (Fase 9 / F17).

    1. Ingestão real (Apple Health / Google Fit / BLE)
    2. Sync clínico FHIR → PatientBaseline
    3. Calibração conformal nos TCNs
    4. Validação clínica com ground truth
    5. Deploy Vertex AI (opcional)
    """

    def __init__(
        self,
        lakehouse_config: Optional[LakehouseConfig] = None,
        vertex_config: Optional[VertexConfig] = None,
        clinical_config: Optional[ClinicalIntegrationConfig] = None,
        ingestion_sources: Optional[List[str]] = None,
    ):
        self.lakehouse_config = lakehouse_config or LakehouseConfig()
        self.vertex_config = vertex_config or VertexConfig()
        self.clinical_config = clinical_config or ClinicalIntegrationConfig()
        self.vertex_config.ensure_directories()

        self.real_ingestion = RealIngestionOrchestrator(
            self.lakehouse_config,
            sources=ingestion_sources,
        )
        self.datalake = DatalakeOrchestrator(self.lakehouse_config)
        self.clinical_bridge = ClinicalDataBridge(self.clinical_config)
        self.conformal = ConformalCalibrator(self.vertex_config.local_model_dir)
        self.validator = ClinicalValidator(
            model_dir=self.vertex_config.local_model_dir,
            clinical_bridge=self.clinical_bridge,
        )
        self.vertex_deploy = VertexTCNEndpointManager(self.vertex_config)

    def run_production_pipeline(
        self,
        patient_id: Optional[str] = None,
        patient_ids: Optional[List[str]] = None,
        run_ingestion: bool = True,
        run_clinical_sync: bool = True,
        run_conformal: bool = True,
        run_validation: bool = True,
        run_vertex_deploy: bool = False,
        use_simulated_datalake_if_empty: bool = True,
    ) -> ProductionResult:
        result = ProductionResult()

        if run_ingestion:
            logger.info("=== F17.1: Ingestão Real ===")
            result.ingestion = self.real_ingestion.run_full_pipeline(patient_id=patient_id)

        patient_profiles = []
        partition_dates = []

        if result.ingestion.get("pipeline"):
            partition_dates = result.ingestion["pipeline"].get("partition_dates", [])
            from src.ingestion.real.profile_factory import profiles_from_ids
            patient_profiles = profiles_from_ids(
                result.ingestion["pipeline"].get("patients", [])
            )

        if not patient_profiles and use_simulated_datalake_if_empty:
            logger.info("Ingestão vazia — usando datalake simulado para conformal/validação")
            sim_result = self.datalake.run_full_pipeline()
            patient_profiles = sim_result.patient_profiles
            partition_dates = sim_result.partition_dates

        pids = patient_ids or [p.patient_id for p in patient_profiles]

        if run_clinical_sync and pids:
            logger.info("=== F17.2: Sync Clínico FHIR ===")
            baselines = self.clinical_bridge.sync_cohort(pids)
            result.clinical_sync = {
                "status": "completed",
                "patients_synced": len(baselines),
                "fhir_live": self.clinical_bridge.client.is_live,
                "baselines": {k: v.to_dict() for k, v in baselines.items()},
            }

        if run_conformal and patient_profiles:
            logger.info("=== F17.3: Conformal Prediction ===")
            result.conformal = self.conformal.calibrate_from_datalake(
                query_engine=self.datalake.query_engine,
                patient_profiles=patient_profiles,
                partition_dates=partition_dates,
            )

        if run_validation and patient_profiles:
            logger.info("=== F17.4: Validação Clínica ===")
            result.validation = self.validator.validate_with_fhir_ground_truth(
                query_engine=self.datalake.query_engine,
                patient_profiles=patient_profiles,
                partition_dates=partition_dates,
            )

        if run_vertex_deploy:
            logger.info("=== F17.5: Deploy Vertex TCN ===")
            validation = self.vertex_deploy.validate_artifacts()
            if validation["valid"]:
                result.vertex_deploy = self.vertex_deploy.deploy_to_vertex()
            else:
                result.vertex_deploy = {
                    "status": "skipped",
                    "reason": "missing_artifacts",
                    "missing": validation["missing"],
                    "local_smoke": self.vertex_deploy.smoke_test_local()
                    if not validation["valid"] else None,
                }

        return result