"""
clinical_ontology_mapper.py — Mapeamento de Tópicos LDA para Ontologias Clínicas.

Este módulo implementa o mapeamento semântico entre tópicos extraídos via
Latent Dirichlet Allocation (LDA) e categorias clínicas padronizadas,
utilizando múltiplas métricas de similaridade (Jaccard, Wu-Palmer simplificada)
para associar vocabulário biomédico a códigos ICD-10, SNOMED-CT e MeSH.

A base de conhecimento clínico (CLINICAL_ONTOLOGY) é inspirada na cobertura
temática da base de teses da USP e foi projetada para suportar domínios
de saúde digital e telemedicina, além das categorias clínicas tradicionais.

Autor: HealthTech Platform
Licença: MIT
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Base de Conhecimento Clínico Estruturada
# ──────────────────────────────────────────────────────────────────────────────

CLINICAL_ONTOLOGY: dict[str, dict[str, Any]] = {
    "cardiovascular": {
        "icd10": ["I10", "I11", "I25", "I48", "I50"],
        "snomed": ["38341003", "49436004", "84114007"],
        "mesh": ["D006333", "D006973", "D002318"],
        "seed_terms": [
            "hipertensão",
            "cardíaco",
            "arritmia",
            "infarto",
            "insuficiência cardíaca",
            "pressão arterial",
            "eletrocardiograma",
            "fibrilação",
            "taquicardia",
            "bradicardia",
        ],
        "phantom_signals": ["systolic_bp", "diastolic_bp"],
        "risk_thresholds": {
            "systolic_bp": (90, 140),
            "diastolic_bp": (60, 90),
        },
    },
    "respiratory": {
        "icd10": ["J44", "J45", "J96"],
        "snomed": ["195967001", "233604007"],
        "mesh": ["D012120", "D001249"],
        "seed_terms": [
            "respiratório",
            "pulmonar",
            "asma",
            "oxigenação",
            "dispneia",
            "ventilação",
            "apneia",
            "saturação",
            "brônquio",
            "pneumonia",
        ],
        "phantom_signals": ["spo2"],
        "risk_thresholds": {"spo2": (95, 100)},
    },
    "metabolic": {
        "icd10": ["E11", "E13", "E78"],
        "snomed": ["73211009", "44054006"],
        "mesh": ["D003920", "D008659"],
        "seed_terms": [
            "diabetes",
            "glicose",
            "metabólico",
            "insulina",
            "glicemia",
            "hemoglobina glicada",
            "resistência insulínica",
            "obesidade",
            "colesterol",
            "triglicérides",
        ],
        "phantom_signals": ["glucose"],
        "risk_thresholds": {"glucose": (70, 140)},
    },
    "neurological_autonomic": {
        "icd10": ["G90", "G47", "G43"],
        "snomed": ["72167002"],
        "mesh": ["D001342", "D012893"],
        "seed_terms": [
            "neurológico",
            "autônomo",
            "vagal",
            "simpático",
            "parassimpático",
            "sono",
            "insônia",
            "estresse",
            "ansiedade",
            "variabilidade",
        ],
        "phantom_signals": ["vagal_tone"],
        "risk_thresholds": {"vagal_tone": (20, 80)},
    },
    "telemedicine_digital_health": {
        "icd10": [],
        "snomed": [],
        "mesh": ["D017216", "D000086382"],
        "seed_terms": [
            "telemedicina",
            "monitoramento remoto",
            "wearable",
            "dispositivo vestível",
            "saúde digital",
            "aplicativo",
            "teleconsulta",
            "telemonitoramento",
            "iot",
            "sensor",
        ],
        "phantom_signals": [],
        "risk_thresholds": {},
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Mapeador de Ontologia Clínica
# ──────────────────────────────────────────────────────────────────────────────


class ClinicalOntologyMapper:
    """Mapeador de tópicos LDA para ontologias clínicas padronizadas.

    Esta classe implementa múltiplas métricas de similaridade semântica
    para associar distribuições de palavras provenientes de modelos LDA
    a categorias clínicas definidas na ontologia estruturada.

    Atributos:
        ontology (dict): Dicionário contendo a base de conhecimento clínico.
        _category_seed_sets (dict): Cache de conjuntos de termos-semente
            por categoria para otimizar cálculos de similaridade.
        _category_ngrams (dict): Cache de n-gramas gerados a partir dos
            termos-semente para correspondência parcial.

    Exemplo de uso:
        >>> mapper = ClinicalOntologyMapper()
        >>> resultado = mapper.map_topic_to_ontology(['cardíaco', 'pressão', 'arritmia'])
        >>> print(resultado['best_category'])
        'cardiovascular'
    """

    def __init__(self, ontology: dict[str, dict[str, Any]] | None = None) -> None:
        """Inicializa o mapeador com a ontologia clínica.

        Args:
            ontology: Dicionário de ontologia clínica. Se None, utiliza
                a constante CLINICAL_ONTOLOGY definida neste módulo.
        """
        self.ontology = ontology if ontology is not None else CLINICAL_ONTOLOGY

        # Pré-computa conjuntos de termos-semente para cada categoria
        self._category_seed_sets: dict[str, set[str]] = {}
        self._category_ngrams: dict[str, set[str]] = {}

        for category, data in self.ontology.items():
            seeds = data.get("seed_terms", [])
            # Conjunto de termos completos (lowercase)
            self._category_seed_sets[category] = {
                term.lower() for term in seeds
            }
            # Conjunto de n-gramas (tokens individuais de termos compostos)
            ngrams: set[str] = set()
            for term in seeds:
                tokens = term.lower().split()
                ngrams.update(tokens)
            self._category_ngrams[category] = ngrams

        logger.info(
            "ClinicalOntologyMapper inicializado com %d categorias: %s",
            len(self.ontology),
            list(self.ontology.keys()),
        )

    # ── API pública ──────────────────────────────────────────────────────

    def get_seed_topics(self) -> dict[int, list[str]]:
        """Retorna termos-semente indexados por número de tópico para Guided LDA.

        Cada categoria da ontologia é mapeada para um índice inteiro
        sequencial, começando em 0, com seus respectivos termos-semente.

        Returns:
            Dicionário {índice_tópico: lista_de_termos_semente}.
        """
        seed_topics: dict[int, list[str]] = {}
        for idx, (category, data) in enumerate(self.ontology.items()):
            seed_topics[idx] = list(data.get("seed_terms", []))
            logger.debug(
                "Tópico %d ← categoria '%s' (%d termos-semente)",
                idx,
                category,
                len(seed_topics[idx]),
            )
        return seed_topics

    def map_topic_to_ontology(self, topic_words: list[str]) -> dict[str, Any]:
        """Mapeia palavras de um tópico LDA para a melhor categoria ontológica.

        Computa similaridade Jaccard e Wu-Palmer simplificada contra cada
        categoria da ontologia e retorna a melhor correspondência.

        Args:
            topic_words: Lista de palavras-chave do tópico LDA
                (tipicamente as top-N palavras com maior peso).

        Returns:
            Dicionário contendo:
                - best_category (str): Nome da melhor categoria.
                - jaccard_score (float): Similaridade Jaccard.
                - wu_palmer_score (float): Similaridade Wu-Palmer simplificada.
                - combined_score (float): Média ponderada das similaridades.
                - icd10_codes (list[str]): Códigos ICD-10 da categoria.
                - snomed_codes (list[str]): Códigos SNOMED-CT da categoria.
                - mesh_codes (list[str]): Códigos MeSH da categoria.
                - all_scores (dict): Scores de todas as categorias.

        Raises:
            ValueError: Se topic_words estiver vazia.
        """
        if not topic_words:
            raise ValueError("topic_words não pode ser uma lista vazia.")

        topic_set = {w.lower() for w in topic_words}
        best_category = ""
        best_combined = -1.0
        all_scores: dict[str, dict[str, float]] = {}

        for category in self.ontology:
            seed_set = self._category_seed_sets[category]

            jaccard = self.compute_jaccard_similarity(topic_set, seed_set)
            wu_palmer = self.compute_wu_palmer_similarity(
                topic_words, list(seed_set)
            )

            # Combinação ponderada: Wu-Palmer recebe peso maior por capturar
            # correspondências parciais em termos compostos
            combined = 0.4 * jaccard + 0.6 * wu_palmer
            all_scores[category] = {
                "jaccard": round(jaccard, 6),
                "wu_palmer": round(wu_palmer, 6),
                "combined": round(combined, 6),
            }

            if combined > best_combined:
                best_combined = combined
                best_category = category

        cat_data = self.ontology.get(best_category, {})

        result = {
            "best_category": best_category,
            "jaccard_score": all_scores.get(best_category, {}).get("jaccard", 0.0),
            "wu_palmer_score": all_scores.get(best_category, {}).get("wu_palmer", 0.0),
            "combined_score": round(best_combined, 6),
            "icd10_codes": list(cat_data.get("icd10", [])),
            "snomed_codes": list(cat_data.get("snomed", [])),
            "mesh_codes": list(cat_data.get("mesh", [])),
            "all_scores": all_scores,
        }

        logger.info(
            "Tópico mapeado → '%s' (combined=%.4f, jaccard=%.4f, wu_palmer=%.4f)",
            best_category,
            best_combined,
            result["jaccard_score"],
            result["wu_palmer_score"],
        )
        return result

    def compute_jaccard_similarity(
        self, set_a: set[str] | list[str], set_b: set[str] | list[str]
    ) -> float:
        """Calcula a similaridade de Jaccard entre dois conjuntos.

        J(A, B) = |A ∩ B| / |A ∪ B|

        Args:
            set_a: Primeiro conjunto de termos.
            set_b: Segundo conjunto de termos.

        Returns:
            Valor float entre 0.0 e 1.0 representando a similaridade.
            Retorna 0.0 se ambos os conjuntos forem vazios.
        """
        a = set(s.lower() for s in set_a) if not isinstance(set_a, set) else set_a
        b = set(s.lower() for s in set_b) if not isinstance(set_b, set) else set_b

        if not a and not b:
            return 0.0

        intersection = len(a & b)
        union = len(a | b)

        return intersection / union if union > 0 else 0.0

    def compute_wu_palmer_similarity(
        self, topic_words: list[str], category_seeds: list[str]
    ) -> float:
        """Calcula similaridade Wu-Palmer simplificada usando sobreposição de n-gramas.

        Esta versão simplificada implementa correspondência parcial considerando
        tokens individuais de termos compostos. Por exemplo, a palavra 'cardíaco'
        obtém correspondência parcial com o termo-semente 'insuficiência cardíaca'.

        O score é uma combinação ponderada de:
            - Correspondência exata (peso 1.0)
            - Correspondência parcial por token (peso 0.5)
            - Correspondência por n-grama de caracteres (peso 0.25)

        Args:
            topic_words: Palavras do tópico LDA.
            category_seeds: Termos-semente da categoria ontológica.

        Returns:
            Score de similaridade Wu-Palmer simplificada entre 0.0 e 1.0.
        """
        if not topic_words or not category_seeds:
            return 0.0

        topic_lower = [w.lower() for w in topic_words]
        seed_lower = [s.lower() for s in category_seeds]

        # Conjuntos de termos completos
        topic_set = set(topic_lower)
        seed_set = set(seed_lower)

        # Tokens individuais extraídos de termos compostos nos seeds
        seed_tokens: set[str] = set()
        for seed in seed_lower:
            seed_tokens.update(seed.split())

        topic_tokens: set[str] = set()
        for word in topic_lower:
            topic_tokens.update(word.split())

        # ── Camada 1: correspondência exata ──
        exact_matches = len(topic_set & seed_set)

        # ── Camada 2: correspondência parcial por token ──
        partial_matches = 0
        already_exact = topic_set & seed_set
        remaining_topic_tokens = topic_tokens - already_exact
        for token in remaining_topic_tokens:
            if token in seed_tokens:
                partial_matches += 1

        # ── Camada 3: correspondência por n-gramas de caracteres (trigramas) ──
        ngram_score = self._compute_char_ngram_overlap(
            topic_tokens - already_exact - (remaining_topic_tokens & seed_tokens),
            seed_tokens,
            n=3,
        )

        # ── Combinação ponderada ──
        max_possible = max(len(topic_lower), 1)
        weighted_score = (
            1.0 * exact_matches
            + 0.5 * partial_matches
            + 0.25 * ngram_score
        ) / max_possible

        # Clamp entre 0 e 1
        return float(np.clip(weighted_score, 0.0, 1.0))

    def map_all_topics(
        self, lda_topic_words: list[list[str]]
    ) -> list[dict[str, Any]]:
        """Mapeia todos os tópicos LDA para categorias ontológicas.

        Args:
            lda_topic_words: Lista de listas, onde cada sublista contém
                as palavras-chave de um tópico LDA.

        Returns:
            Lista de dicionários com os resultados do mapeamento
            para cada tópico, indexados na mesma ordem de entrada.
        """
        results: list[dict[str, Any]] = []
        for idx, words in enumerate(lda_topic_words):
            logger.info("Mapeando tópico %d (%d palavras)...", idx, len(words))
            try:
                mapping = self.map_topic_to_ontology(words)
                mapping["topic_index"] = idx
                results.append(mapping)
            except ValueError as exc:
                logger.warning(
                    "Tópico %d ignorado — erro de validação: %s", idx, exc
                )
                results.append(
                    {
                        "topic_index": idx,
                        "best_category": "unknown",
                        "combined_score": 0.0,
                        "error": str(exc),
                    }
                )
        return results

    def get_ontology_context(self, category: str) -> dict[str, Any]:
        """Retorna informações completas da ontologia para uma categoria.

        Args:
            category: Nome da categoria clínica (ex: 'cardiovascular').

        Returns:
            Dicionário com todos os campos da ontologia para a categoria,
            ou dicionário vazio se a categoria não existir.

        Raises:
            KeyError: Se a categoria não existir na ontologia.
        """
        if category not in self.ontology:
            raise KeyError(
                f"Categoria '{category}' não encontrada na ontologia. "
                f"Categorias disponíveis: {list(self.ontology.keys())}"
            )

        context = dict(self.ontology[category])
        context["category_name"] = category
        logger.debug("Contexto ontológico retornado para '%s'", category)
        return context

    # ── Métodos internos ─────────────────────────────────────────────────

    @staticmethod
    def _compute_char_ngram_overlap(
        tokens_a: set[str], tokens_b: set[str], n: int = 3
    ) -> float:
        """Computa sobreposição de n-gramas de caracteres entre conjuntos de tokens.

        Args:
            tokens_a: Primeiro conjunto de tokens.
            tokens_b: Segundo conjunto de tokens.
            n: Tamanho do n-grama de caracteres.

        Returns:
            Número estimado de correspondências por n-grama (float).
        """
        if not tokens_a or not tokens_b:
            return 0.0

        def _char_ngrams(word: str, size: int) -> set[str]:
            """Gera n-gramas de caracteres para uma palavra."""
            if len(word) < size:
                return {word}
            return {word[i : i + size] for i in range(len(word) - size + 1)}

        ngrams_b: set[str] = set()
        for token in tokens_b:
            ngrams_b.update(_char_ngrams(token, n))

        if not ngrams_b:
            return 0.0

        overlap_count = 0.0
        for token in tokens_a:
            token_ngrams = _char_ngrams(token, n)
            if token_ngrams:
                ratio = len(token_ngrams & ngrams_b) / len(token_ngrams)
                if ratio > 0.5:  # Limiar de correspondência significativa
                    overlap_count += ratio

        return overlap_count


# ──────────────────────────────────────────────────────────────────────────────
# Demonstração
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    print("=" * 72)
    print("  DEMONSTRAÇÃO — ClinicalOntologyMapper")
    print("=" * 72)

    mapper = ClinicalOntologyMapper()

    # ── 1. Termos-semente para Guided LDA ──
    print("\n─── Termos-semente para Guided LDA ───")
    seed_topics = mapper.get_seed_topics()
    for topic_id, terms in seed_topics.items():
        print(f"  Tópico {topic_id}: {terms[:5]}...")

    # ── 2. Mapeamento de tópicos sintéticos ──
    print("\n─── Mapeamento de tópicos sintéticos ───")
    synthetic_topics = [
        ["cardíaco", "pressão", "arritmia", "eletrocardiograma", "frequência"],
        ["diabetes", "glicose", "insulina", "hemoglobina", "obesidade"],
        ["respiratório", "pulmonar", "oxigenação", "saturação", "ventilação"],
        ["telemedicina", "wearable", "sensor", "monitoramento", "digital"],
        ["sono", "vagal", "ansiedade", "estresse", "neurológico"],
    ]

    resultados = mapper.map_all_topics(synthetic_topics)
    for res in resultados:
        print(
            f"  Tópico {res.get('topic_index', '?')}: "
            f"→ {res.get('best_category', 'N/A')} "
            f"(score={res.get('combined_score', 0):.4f})"
        )
        if "icd10_codes" in res:
            print(f"    ICD-10: {res['icd10_codes']}")
            print(f"    SNOMED: {res['snomed_codes']}")
            print(f"    MeSH:   {res['mesh_codes']}")

    # ── 3. Contexto ontológico ──
    print("\n─── Contexto ontológico: cardiovascular ───")
    ctx = mapper.get_ontology_context("cardiovascular")
    for key, value in ctx.items():
        print(f"  {key}: {value}")

    # ── 4. Similaridades detalhadas ──
    print("\n─── Similaridades detalhadas ───")
    topic_test = ["cardíaco", "insuficiência", "pressão"]
    for cat_name in mapper.ontology:
        seeds = list(mapper._category_seed_sets[cat_name])
        j = mapper.compute_jaccard_similarity(set(topic_test), set(seeds))
        wp = mapper.compute_wu_palmer_similarity(topic_test, seeds)
        print(f"  {cat_name}: Jaccard={j:.4f}, Wu-Palmer={wp:.4f}")

    print("\n✓ Demonstração concluída.")
