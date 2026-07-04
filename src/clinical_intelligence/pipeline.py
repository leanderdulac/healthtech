"""
Pipeline de inteligência clínica preditiva multimodal.

Fluxo:
  Silver vitals → Denoising → Ghost signals → Fuzzy → Fusion → Prognóstico
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from src.clinical_intelligence.evidence_fusion import EvidenceFusionEngine
from src.clinical_intelligence.fuzzy_engine import FuzzyClinicalEngine
from src.clinical_intelligence.ghost_signals import GhostSignalDetector
from src.clinical_intelligence.models import (
    ClinicalIntelligenceResult,
    PatientBaseline,
)
from src.clinical_intelligence.prognostic_engine import PrognosticEngine
from src.clinical_intelligence.signal_processing import WearableSignalProcessor

logger = logging.getLogger(__name__)


class ClinicalIntelligencePipeline:
    """
    Motor preditivo completo para telemetria wearable + dados clínicos.

    Integra com datalake Silver/Gold, ontologia, hemodinâmica e FHIR.
    """

    def __init__(self):
        self.signal_processor = WearableSignalProcessor()
        self.ghost_detector = GhostSignalDetector()
        self.fuzzy_engine = FuzzyClinicalEngine()
        self.prognostic = PrognosticEngine()
        self.fusion = EvidenceFusionEngine()

    def analyze_patient(
        self,
        vitals_df: pd.DataFrame,
        baseline: PatientBaseline,
        scenario: str = "live",
        hemodynamic_score: float = 0.0,
        ontology_domains: Optional[Dict[str, float]] = None,
    ) -> ClinicalIntelligenceResult:
        signals = self._build_signals(vitals_df)
        persistence = self.prognostic.compute_persistence(signals, baseline)

        ghosts = self.ghost_detector.detect(
            signals, baseline, hemodynamic_score, ontology_domains,
        )

        fuzzy = self.fuzzy_engine.assess(
            hr_deviation=self.prognostic.hr_deviation(signals, baseline),
            spo2_risk=self.prognostic.spo2_risk(signals, baseline),
            hrv_suppression=self.prognostic.hrv_suppression(signals, baseline),
            ghost_signals=ghosts,
            noise_level=self.prognostic.noise_level(signals),
            artifact_ratio=self.prognostic.artifact_ratio(signals),
            persistence=persistence,
            trajectory_slope=self.prognostic.trajectory_slope(signals),
            baseline=baseline,
        )
        fuzzy.persistence_score = persistence

        wearable_score = self.prognostic.wearable_risk_score(signals, baseline)
        fusion_score, predictions = self.fusion.fuse(
            patient_id=baseline.patient_id,
            wearable_score=wearable_score,
            ghost_signals=ghosts,
            fuzzy=fuzzy,
            baseline=baseline,
            hemodynamic_score=hemodynamic_score,
        )

        if ontology_domains is None:
            ontology_domains = self._ontology_from_ghosts(ghosts)

        return ClinicalIntelligenceResult(
            patient_id=baseline.patient_id,
            scenario=scenario,
            denoised_signals=signals,
            ghost_signals=ghosts,
            fuzzy=fuzzy,
            predictions=predictions,
            fusion_score=fusion_score,
            ontology_domains=ontology_domains,
        )

    def analyze_from_profiles(
        self,
        query_engine,
        patient_profiles: List,
        partition_dates: Optional[List[str]] = None,
        hemodynamic_scores: Optional[Dict[str, float]] = None,
    ) -> List[ClinicalIntelligenceResult]:
        from src.datalake.extraction.filters import QueryFilters

        results = []
        for profile in patient_profiles:
            vitals = query_engine.extract("vitals", QueryFilters(
                patient_id=profile.patient_id,
                partition_dates=partition_dates,
            ))
            if vitals.empty:
                continue

            baseline = self._profile_to_baseline(profile)
            hemo = (hemodynamic_scores or {}).get(profile.patient_id, 0.0)
            ont = self._load_ontology_domains()

            result = self.analyze_patient(
                vitals, baseline,
                scenario="datalake",
                hemodynamic_score=hemo,
                ontology_domains=ont,
            )
            results.append(result)

        return results

    def _build_signals(self, vitals_df: pd.DataFrame) -> Dict:
        signals = {}
        vitals_df = vitals_df.sort_values("window_start")

        metric_map = {
            "heart_rate": "heart_rate",
            "spo2": "spo2",
            "hrv": "hrv",
            "stress_index": "stress",
        }

        for col, metric in metric_map.items():
            if col not in vitals_df.columns:
                continue
            values = vitals_df[col].dropna().tolist()
            if not values:
                continue
            timestamps = vitals_df.loc[vitals_df[col].notna(), "window_start"].astype(str).tolist()
            quality = None
            if "quality_score" in vitals_df.columns:
                quality = vitals_df.loc[vitals_df[col].notna(), "quality_score"].tolist()

            signals[metric] = self.signal_processor.process(
                metric=metric,
                values=values,
                timestamps=timestamps,
                quality_scores=quality,
            )

        return signals

    @staticmethod
    def _profile_to_baseline(profile) -> PatientBaseline:
        conditions = []
        if getattr(profile, "risk_factor", 0) > 0.5:
            conditions.append("elevated_cardiovascular_risk")
        if profile.age > 60:
            conditions.append("age_related_risk")

        return PatientBaseline(
            patient_id=profile.patient_id,
            resting_hr=float(profile.resting_hr),
            baseline_spo2=float(profile.baseline_spo2),
            baseline_hrv=float(profile.baseline_hrv),
            age=profile.age,
            risk_factor=float(getattr(profile, "risk_factor", 0)),
            activity_level=getattr(profile, "activity_level", "moderate"),
            clinical_conditions=conditions,
        )

    @staticmethod
    def _load_ontology_domains() -> Dict[str, float]:
        try:
            from src.ontology.registry import MedicalOntologyRegistry
            registry = MedicalOntologyRegistry()
            if registry.load():
                return registry.domain_scores("telemedicina cardiovascular wearable")
        except Exception:
            pass
        return {}

    @staticmethod
    def _ontology_from_ghosts(ghosts) -> Dict[str, float]:
        domains = {"cardiovascular": 0.0, "respiratory": 0.0, "monitoring": 0.0}
        for g in ghosts:
            if "hypoxemia" in g.name or "respiratory" in g.clinical_relevance.lower():
                domains["respiratory"] = min(1.0, domains["respiratory"] + g.value * 0.3)
            if "cardiac" in g.clinical_relevance.lower() or "autonomic" in g.name:
                domains["cardiovascular"] = min(1.0, domains["cardiovascular"] + g.value * 0.3)
            domains["monitoring"] = min(1.0, domains["monitoring"] + g.confidence * 0.1)
        return domains