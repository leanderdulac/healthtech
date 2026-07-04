import logging
from typing import Dict, Optional

import pandas as pd

from src.datalake.config import LakehouseConfig
from src.datalake.schemas.base import DataLayer
from src.datalake.extraction.extractors.anomaly_windows import AnomalyWindowExtractor
from src.datalake.extraction.extractors.patient_timeline import PatientTimelineExtractor
from src.datalake.extraction.extractors.population_cohort import PopulationCohortExtractor
from src.datalake.extraction.extractors.vitals_stream import VitalsStreamExtractor
from src.datalake.extraction.filters import QueryFilters
from src.datalake.storage.interface import LakehouseStore

logger = logging.getLogger(__name__)


class DatalakeQueryEngine:
    """
    Fachada unificada de extração do lakehouse de telemetria.
    Orquestra extractors especializados e expõe API de consulta.
    """

    def __init__(self, store: LakehouseStore, config: Optional[LakehouseConfig] = None):
        self.store = store
        self.config = config or LakehouseConfig()
        self._extractors = {
            "timeline": PatientTimelineExtractor(store),
            "vitals": VitalsStreamExtractor(store),
            "anomalies": AnomalyWindowExtractor(store),
            "cohort": PopulationCohortExtractor(store),
        }

    def extract(self, query_type: str, filters: QueryFilters) -> pd.DataFrame:
        if query_type not in self._extractors:
            raise ValueError(
                f"Query type '{query_type}' inválido. "
                f"Disponíveis: {list(self._extractors.keys())}"
            )
        logger.info("Extraindo '%s' com filtros: patient=%s", query_type, filters.patient_id)
        return self._extractors[query_type].extract(filters)

    def extract_patient_24h(self, patient_id: str, partition_date: str) -> Dict[str, pd.DataFrame]:
        """Pacote completo de extração 24h para um paciente."""
        base_filters = QueryFilters(
            patient_id=patient_id,
            partition_dates=[partition_date],
        )
        return {
            "timeline": self.extract("timeline", base_filters),
            "vitals_stream": self.extract("vitals", base_filters),
            "anomaly_episodes": self.extract("anomalies", base_filters),
            "daily_summary": self.store.read_layer(
                layer=DataLayer.GOLD,
                table="daily_summary",
                patient_id=patient_id,
                partition_dates=[partition_date],
            ),
            "alerts": self.store.read_layer(
                layer=DataLayer.GOLD,
                table="patient_alerts",
                patient_id=patient_id,
            ),
        }

    def extract_high_risk_cohort(self, min_risk_score: float = 0.5) -> pd.DataFrame:
        return self.extract("cohort", QueryFilters(
            min_risk_score=min_risk_score,
            clinical_risk_levels=["elevated", "critical"],
        ))

    def get_lakehouse_stats(self) -> Dict[str, object]:
        stats = {}
        gold_tables = ["hourly_vitals", "daily_summary", "patient_alerts"]

        for layer in DataLayer:
            if layer == DataLayer.GOLD:
                frames = [
                    self.store.read_layer(layer=layer, table=t) for t in gold_tables
                ]
                df = pd.concat(frames, ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame()
                partitions = sorted({
                    p for t in gold_tables for p in self.store.list_partitions(layer, t)
                })
            else:
                partitions = self.store.list_partitions(layer)
                df = self.store.read_layer(layer=layer)

            stats[layer.value] = {
                "partitions": partitions,
                "total_records": len(df),
                "patients": df["patient_id"].nunique() if not df.empty and "patient_id" in df.columns else 0,
            }

        lineage = self.store.get_lineage()
        stats["lineage_events"] = len(lineage)
        return stats