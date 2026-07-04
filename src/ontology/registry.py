"""
Registro central da ontologia médica do Healthtech.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DEFAULT_ONTOLOGY_PATH = Path("data/ontology/medical_ontology.json")
SCRAPER_ONTOLOGY_PATH = Path("data/scraping/usp_teses/ontology.json")

DOMAIN_KEYWORDS = {
    "cardiovascular": {
        "cardio", "cardíaco", "cardiaco", "arritmia", "frequência cardíaca",
        "heart rate", "ecg", "eletrocardiografia", "hipertensão", "infarto",
        "coronária", "valvular", "insuficiência cardíaca",
    },
    "respiratory": {
        "respiratório", "respiratorio", "spo2", "oxigenação", "pulmonar",
        "pneumologia", "ventilação", "asma", "dpoc",
    },
    "monitoring": {
        "telemedicina", "wearable", "monitoramento", "sensor", "iot",
        "dispositivo", "biométrico", "biometrico", "sinais vitais",
        "telemetria", "remoto",
    },
    "neurology": {
        "neurologia", "neurológico", "eeg", "epilepsia", "avc", "demência",
        "parkinson", "neuropatia",
    },
    "oncology": {
        "oncologia", "câncer", "cancer", "tumor", "neoplasia", "quimioterapia",
    },
    "mental_health": {
        "psiquiatria", "saúde mental", "depressão", "ansiedade", "psicologia",
    },
    "imaging": {
        "imagem", "tomografia", "ressonância", "radiologia", "ultrassom",
        "segmentação", "visualização 3d",
    },
}


class MedicalOntologyRegistry:
    """Carrega e consulta a ontologia médica derivada de teses USP."""

    def __init__(self, ontology_path: Optional[Path] = None):
        self.ontology_path = Path(ontology_path) if ontology_path else self._resolve_path()
        self._data: Dict = {}
        self._keywords: Dict[str, int] = {}
        self._areas: Dict[str, int] = {}
        self._cooccurrence: Dict[str, Set[str]] = {}
        self._loaded = False

    @staticmethod
    def _resolve_path() -> Path:
        if DEFAULT_ONTOLOGY_PATH.exists():
            return DEFAULT_ONTOLOGY_PATH
        return SCRAPER_ONTOLOGY_PATH

    def load(self) -> bool:
        if not self.ontology_path.exists():
            logger.warning("Ontologia não encontrada: %s", self.ontology_path)
            return False

        with open(self.ontology_path, encoding="utf-8") as f:
            self._data = json.load(f)

        ont = self._data.get("ontology", {})
        self._keywords = {
            item["keyword"]: item["count"]
            for item in ont.get("top_keywords", [])
        }
        self._areas = {
            item["area"]: item["count"]
            for item in ont.get("top_areas", [])
        }
        self._build_cooccurrence()
        self._loaded = True
        logger.info(
            "Ontologia carregada: %d keywords, %d áreas",
            len(self._keywords), len(self._areas),
        )
        return True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def statistics(self) -> Dict:
        return self._data.get("ontology", {}).get("statistics", {})

    def _build_cooccurrence(self) -> None:
        self._cooccurrence = {}
        for edge in self._data.get("graph", {}).get("edges", []):
            if edge.get("relation") != "cooccursWith":
                continue
            src = edge["source"].replace("keyword:", "")
            tgt = edge["target"].replace("keyword:", "")
            self._cooccurrence.setdefault(src, set()).add(tgt)
            self._cooccurrence.setdefault(tgt, set()).add(src)

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().strip())

    def match_keywords(self, text: str, top_k: int = 10) -> List[Tuple[str, float]]:
        if not self._loaded:
            return []
        normalized = self._normalize(text)
        matches = []
        for keyword, count in self._keywords.items():
            if keyword in normalized:
                score = count / max(self._keywords.values())
                matches.append((keyword, round(score, 4)))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:top_k]

    def domain_scores(self, text: str) -> Dict[str, float]:
        normalized = self._normalize(text)
        scores: Dict[str, float] = {}
        for domain, terms in DOMAIN_KEYWORDS.items():
            hits = sum(1 for t in terms if t in normalized)
            ont_hits = sum(
                1 for kw in self._keywords
                if kw in normalized and any(t in kw for t in terms)
            )
            total = hits + ont_hits
            if total > 0:
                scores[domain] = round(min(1.0, total / 5), 3)
        return scores

    def related_terms(self, term: str, max_depth: int = 1) -> List[str]:
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower().strip()).strip("-")
        related = set()
        frontier = {slug}
        for _ in range(max_depth):
            next_frontier = set()
            for s in frontier:
                for r in self._cooccurrence.get(s, []):
                    if r not in related:
                        related.add(r)
                        next_frontier.add(r)
            frontier = next_frontier
        return sorted(related)[:20]

    def get_top_keywords(self, n: int = 50) -> List[Dict]:
        return [
            {"keyword": k, "count": c}
            for k, c in sorted(self._keywords.items(), key=lambda x: x[1], reverse=True)[:n]
        ]

    def get_top_areas(self, n: int = 20) -> List[Dict]:
        return [
            {"area": a, "count": c}
            for a, c in sorted(self._areas.items(), key=lambda x: x[1], reverse=True)[:n]
        ]

    def to_dict(self) -> Dict:
        return self._data