"""
Enriquecimento de features ML com scores da ontologia médica.
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from src.ontology.registry import DOMAIN_KEYWORDS, MedicalOntologyRegistry

logger = logging.getLogger(__name__)

DOMAIN_COLUMNS = [f"ont_{domain}" for domain in DOMAIN_KEYWORDS]
METRIC_DOMAIN_MAP = {
    "heart_rate": "cardiovascular",
    "tachycardia": "cardiovascular",
    "bradycardia": "cardiovascular",
    "spo2": "respiratory",
    "hypoxemia": "respiratory",
    "hrv": "cardiovascular",
    "stress_index": "mental_health",
    "high_stress": "mental_health",
}


class OntologyFeatureEnricher:
    """Adiciona features derivadas da ontologia ao dataset de treino."""

    def __init__(self, registry: Optional[MedicalOntologyRegistry] = None):
        self.registry = registry or MedicalOntologyRegistry()
        if not self.registry.is_loaded:
            self.registry.load()

    @property
    def is_available(self) -> bool:
        return self.registry.is_loaded

    def enrich_batch_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.is_available or df.empty:
            return df

        enriched = df.copy()
        for domain in DOMAIN_KEYWORDS:
            enriched[f"ont_{domain}"] = 0.0

        for idx, row in enriched.iterrows():
            context_parts = [
                str(row.get("clinical_risk_level", "")),
                str(row.get("patient_id", "")),
            ]
            for col in ("anomaly_episodes", "total_alerts", "avg_resting_hr", "avg_spo2"):
                val = row.get(col)
                if val and float(val) > 0:
                    context_parts.append(col)

            context = " ".join(context_parts)
            scores = self.registry.domain_scores(context)

            if row.get("anomaly_episodes", 0) > 0:
                scores["monitoring"] = max(scores.get("monitoring", 0), 0.5)
            if row.get("avg_resting_hr", 0) > 100:
                scores["cardiovascular"] = max(scores.get("cardiovascular", 0), 0.7)
            if row.get("avg_spo2", 100) < 94:
                scores["respiratory"] = max(scores.get("respiratory", 0), 0.7)

            for domain, score in scores.items():
                enriched.at[idx, f"ont_{domain}"] = score

        logger.info("Features enriquecidas com %d domínios ontológicos", len(DOMAIN_KEYWORDS))
        return enriched

    def enrich_alerts(self, alerts_df: pd.DataFrame) -> pd.DataFrame:
        if not self.is_available or alerts_df.empty:
            return alerts_df

        enriched = alerts_df.copy()
        matched_keywords = []
        ontology_domains = []

        for _, row in enriched.iterrows():
            text = f"{row.get('alert_type', '')} {row.get('metric_type', '')}"
            keywords = self.registry.match_keywords(text, top_k=5)
            domains = self.registry.domain_scores(text)

            metric = str(row.get("metric_type", ""))
            mapped_domain = METRIC_DOMAIN_MAP.get(metric)
            if mapped_domain:
                domains[mapped_domain] = max(domains.get(mapped_domain, 0), 0.8)

            matched_keywords.append([k for k, _ in keywords])
            ontology_domains.append(domains)

        enriched["ontology_keywords"] = matched_keywords
        enriched["ontology_domains"] = ontology_domains
        return enriched

    def get_feature_columns(self) -> List[str]:
        return list(DOMAIN_COLUMNS)