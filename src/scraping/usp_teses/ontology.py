"""
Construtor de ontologia a partir de teses/dissertações de medicina.

Gera estrutura para treino de modelos NLP e integração com FHIR/SNOMED.
"""

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List

from src.scraping.usp_teses.models import ThesisRecord

STOPWORDS_PT = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "em", "para", "com", "por",
    "um", "uma", "os", "as", "na", "no", "nas", "nos", "ao", "aos", "à", "às",
    "se", "que", "ou", "como", "mais", "entre", "sobre", "após", "antes", "sem",
    "sua", "seu", "suas", "seus", "este", "esta", "estes", "estas", "foi", "ser",
    "são", "é", "ao", "pelo", "pela", "pelos", "pelas",
}


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-záàâãéêíóôõúçüA-ZÁÀÂÃÉÊÍÓÔÕÚÇÜ0-9\-]{3,}", text.lower())
    return [t for t in tokens if t not in STOPWORDS_PT]


class OntologyBuilder:
    """Constrói ontologia de domínio médico a partir do corpus coletado."""

    def __init__(self, namespace: str = "http://healthtech.local/ontology"):
        self.namespace = namespace

    def build(self, records: List[ThesisRecord]) -> Dict:
        keyword_counts: Counter = Counter()
        area_counts: Counter = Counter()
        tipo_counts: Counter = Counter()
        unidade_counts: Counter = Counter()
        term_cooccurrence: Dict[str, Counter] = defaultdict(Counter)
        token_counts: Counter = Counter()

        nodes = []
        edges = []

        for record in records:
            if not record.is_medicine_related:
                continue

            area_counts[record.area] += 1
            tipo_counts[record.tipo_documento] += 1
            unidade_counts[record.unidade] += 1

            record_keywords = list(record.palavras_chave_pt) + list(record.palavras_chave_en)
            for kw in record_keywords:
                kw_norm = kw.strip().lower()
                if kw_norm:
                    keyword_counts[kw_norm] += 1

            record_terms = set(record_keywords)
            for t1 in record_terms:
                for t2 in record_terms:
                    if t1 != t2:
                        term_cooccurrence[t1.lower()][t2.lower()] += 1

            for token in _tokenize(record.resumo_pt):
                token_counts[token] += 1

            thesis_node_id = f"thesis:{record.id}"
            nodes.append({
                "id": thesis_node_id,
                "type": "Thesis",
                "label": record.titulo[:120],
                "properties": {
                    "ano": record.ano_defesa,
                    "tipo": record.tipo_documento,
                    "doi": record.doi,
                },
            })

            if record.area:
                area_id = f"area:{self._slug(record.area)}"
                edges.append({
                    "source": thesis_node_id,
                    "target": area_id,
                    "relation": "belongsToArea",
                })

            for kw in record_keywords:
                kw_id = f"keyword:{self._slug(kw)}"
                edges.append({
                    "source": thesis_node_id,
                    "target": kw_id,
                    "relation": "hasKeyword",
                })

        for area, count in area_counts.most_common():
            nodes.append({
                "id": f"area:{self._slug(area)}",
                "type": "ConcentrationArea",
                "label": area,
                "count": count,
            })

        for kw, count in keyword_counts.most_common(200):
            nodes.append({
                "id": f"keyword:{self._slug(kw)}",
                "type": "Keyword",
                "label": kw,
                "count": count,
            })

        for tipo, count in tipo_counts.most_common():
            nodes.append({
                "id": f"tipo:{self._slug(tipo)}",
                "type": "DocumentType",
                "label": tipo,
                "count": count,
            })

        top_tokens = [
            {"term": term, "count": count}
            for term, count in token_counts.most_common(100)
        ]

        cooccurrence_edges = []
        for t1, counter in term_cooccurrence.items():
            for t2, count in counter.most_common(3):
                if t1 < t2:
                    cooccurrence_edges.append({
                        "source": f"keyword:{self._slug(t1)}",
                        "target": f"keyword:{self._slug(t2)}",
                        "relation": "cooccursWith",
                        "weight": count,
                    })

        return {
            "ontology": {
                "namespace": self.namespace,
                "version": "1.0",
                "domain": "medicine",
                "source": "teses.usp.br",
                "generated_at": datetime.utcnow().isoformat(),
                "statistics": {
                    "total_theses": len([r for r in records if r.is_medicine_related]),
                    "unique_areas": len(area_counts),
                    "unique_keywords": len(keyword_counts),
                    "unique_units": len(unidade_counts),
                },
                "top_areas": [
                    {"area": a, "count": c} for a, c in area_counts.most_common(30)
                ],
                "top_keywords": [
                    {"keyword": k, "count": c} for k, c in keyword_counts.most_common(50)
                ],
                "top_tokens": top_tokens,
                "document_types": [
                    {"tipo": t, "count": c} for t, c in tipo_counts.most_common()
                ],
            },
            "graph": {
                "nodes": nodes,
                "edges": edges + cooccurrence_edges[:500],
            },
        }

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
        return slug.strip("-")[:80] or "unknown"