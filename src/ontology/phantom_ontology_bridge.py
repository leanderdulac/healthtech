"""
phantom_ontology_bridge.py — Rede Diagnóstica Bayesiana e Relatórios Enriquecidos.

Este módulo implementa a ponte entre sinais fantasma (phantom signals)
estimados a partir de dados de wearables e a ontologia clínica, utilizando
inferência bayesiana para gerar hipóteses diagnósticas probabilísticas.

A rede bayesiana combina:
    - Probabilidades a priori de condições clínicas
    - Verossimilhança gaussiana baseada em limiares de risco
    - Evidências adicionais de métricas HRV e scores de anomalia
    - Códigos clínicos padronizados (ICD-10, SNOMED-CT, MeSH)

Autor: HealthTech Platform
Licença: MIT
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.stats import norm

from .clinical_ontology_mapper import CLINICAL_ONTOLOGY, ClinicalOntologyMapper

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Rede Diagnóstica Bayesiana
# ──────────────────────────────────────────────────────────────────────────────


class BayesianDiagnosticNetwork:
    """Rede bayesiana para inferência diagnóstica a partir de sinais fantasma.

    Implementa o teorema de Bayes para computar probabilidades posteriores
    de condições clínicas dadas observações de sinais fisiológicos estimados
    (phantom signals), métricas de variabilidade cardíaca (HRV) e scores
    de anomalia provenientes de modelos de detecção não-supervisionada.

    A verossimilhança P(dados|condição) é modelada como uma distribuição
    gaussiana centrada nos limites dos limiares de risco, de forma que
    valores fora da faixa normal aumentam a probabilidade da condição.

    Atributos:
        ontology (dict): Base de conhecimento clínico.
        priors (dict[str, float]): Probabilidades a priori por categoria.
        _sigma_scale (float): Fator de escala para desvio-padrão gaussiano.

    Exemplo de uso:
        >>> net = BayesianDiagnosticNetwork()
        >>> phantom = {'systolic_bp': 165.0, 'diastolic_bp': 95.0, 'spo2': 97.0}
        >>> hipoteses = net.generate_diagnostic_hypotheses(phantom, top_k=3)
        >>> for h in hipoteses:
        ...     print(f"{h['category']}: {h['posterior_probability']:.4f}")
    """

    # Probabilidades a priori padrão (~5% cada, refletindo prevalência
    # populacional geral sem informação clínica específica)
    DEFAULT_PRIORS: dict[str, float] = {
        "cardiovascular": 0.06,
        "respiratory": 0.05,
        "metabolic": 0.06,
        "neurological_autonomic": 0.04,
        "telemedicine_digital_health": 0.02,
    }

    def __init__(
        self,
        ontology: dict[str, dict[str, Any]] | None = None,
        priors: dict[str, float] | None = None,
        sigma_scale: float = 0.15,
    ) -> None:
        """Inicializa a rede diagnóstica bayesiana.

        Args:
            ontology: Base de conhecimento clínico. Se None, utiliza
                CLINICAL_ONTOLOGY.
            priors: Probabilidades a priori por categoria. Se None,
                utiliza DEFAULT_PRIORS.
            sigma_scale: Fator de escala para o desvio-padrão da
                distribuição gaussiana de verossimilhança. Controla
                quão rapidamente a likelihood decai fora da faixa normal.
                Valores menores = decaimento mais abrupto.
        """
        self.ontology = ontology if ontology is not None else CLINICAL_ONTOLOGY
        self.priors = priors if priors is not None else dict(self.DEFAULT_PRIORS)
        self._sigma_scale = sigma_scale

        # Garante que todas as categorias da ontologia têm prior definido
        for category in self.ontology:
            if category not in self.priors:
                self.priors[category] = 0.05
                logger.warning(
                    "Prior não definido para '%s'; usando valor padrão 0.05.",
                    category,
                )

        logger.info(
            "BayesianDiagnosticNetwork inicializada com %d categorias, "
            "sigma_scale=%.3f",
            len(self.ontology),
            self._sigma_scale,
        )

    # ── Verossimilhança ──────────────────────────────────────────────────

    def _compute_likelihood(
        self, phantom_data: dict[str, float], category: str
    ) -> float:
        """Computa P(observações | condição) para uma categoria clínica.

        Para cada sinal fantasma relevante à categoria, calcula a
        verossimilhança gaussiana baseada na distância do valor observado
        aos limites da faixa normal. Valores dentro da faixa normal
        recebem verossimilhança base; valores fora recebem verossimilhança
        proporcional ao desvio.

        A verossimilhança conjunta é o produto das verossimilhanças
        individuais (assumindo independência condicional).

        Args:
            phantom_data: Dicionário {nome_sinal: valor_estimado}.
            category: Nome da categoria clínica.

        Returns:
            Verossimilhança conjunta P(dados|condição) como float.
            Retorna 1.0 (verossimilhança neutra) se a categoria não
            tiver sinais fantasma definidos ou nenhum sinal relevante
            estiver presente nos dados.
        """
        cat_data = self.ontology.get(category, {})
        thresholds = cat_data.get("risk_thresholds", {})
        phantom_signals = cat_data.get("phantom_signals", [])

        if not thresholds or not phantom_signals:
            return 1.0  # Sem sinais → verossimilhança neutra

        likelihood = 1.0
        signals_evaluated = 0

        for signal_name in phantom_signals:
            if signal_name not in phantom_data:
                continue

            if signal_name not in thresholds:
                continue

            value = phantom_data[signal_name]
            low, high = thresholds[signal_name]
            range_width = high - low

            if range_width <= 0:
                logger.warning(
                    "Limiar inválido para sinal '%s' na categoria '%s': "
                    "low=%s, high=%s",
                    signal_name,
                    category,
                    low,
                    high,
                )
                continue

            sigma = range_width * self._sigma_scale

            # Modelo de verossimilhança:
            # - Dentro da faixa normal → alta verossimilhança para "saudável",
            #   baixa para "condição presente"
            # - Fora da faixa → inversamente: alta verossimilhança para condição
            if low <= value <= high:
                # Valor normal: verossimilhança baixa de estar doente
                # Distância ao centro da faixa normal
                center = (low + high) / 2.0
                dist_to_boundary = min(abs(value - low), abs(value - high))
                # Mais longe da borda = menor verossimilhança de doença
                signal_likelihood = 1.0 - norm.cdf(dist_to_boundary, loc=0, scale=sigma)
                signal_likelihood = max(signal_likelihood, 0.05)  # Floor
            else:
                # Valor anormal: verossimilhança alta de condição
                if value < low:
                    deviation = low - value
                else:
                    deviation = value - high
                # Quanto maior o desvio, maior a verossimilhança
                signal_likelihood = norm.cdf(deviation, loc=0, scale=sigma)
                signal_likelihood = max(signal_likelihood, 0.1)  # Floor

            likelihood *= signal_likelihood
            signals_evaluated += 1

            logger.debug(
                "  Sinal '%s': valor=%.2f, faixa=(%s, %s), "
                "likelihood=%.6f",
                signal_name,
                value,
                low,
                high,
                signal_likelihood,
            )

        if signals_evaluated == 0:
            return 1.0

        return float(likelihood)

    # ── Posterior bayesiano ───────────────────────────────────────────────

    def compute_posterior(
        self,
        phantom_data: dict[str, float],
        hrv_metrics: dict[str, float] | None = None,
        anomaly_score: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Computa a distribuição posterior P(condição | dados) para todas as condições.

        Aplica o teorema de Bayes:
            P(condição | dados) ∝ P(dados | condição) × P(condição)

        Incorpora evidências adicionais de métricas HRV (ex: SDNN, RMSSD,
        LF/HF ratio) e scores de anomalia de modelos não-supervisionados
        como multiplicadores da verossimilhança.

        Args:
            phantom_data: Valores estimados dos sinais fantasma.
            hrv_metrics: Métricas de variabilidade cardíaca opcionais.
                Chaves esperadas: 'sdnn', 'rmssd', 'lf_hf_ratio', etc.
            anomaly_score: Scores de anomalia opcionais por categoria
                ou gerais. Chave 'global' para score geral.

        Returns:
            Lista de dicionários ordenada por probabilidade posterior
            decrescente, contendo:
                - category (str)
                - prior (float)
                - likelihood (float)
                - posterior (float)
                - severity (str)
        """
        if not phantom_data:
            logger.warning("phantom_data vazio — retornando priors como posteriors.")
            return self._priors_as_posteriors()

        unnormalized: dict[str, float] = {}

        for category in self.ontology:
            prior = self.priors.get(category, 0.05)
            likelihood = self._compute_likelihood(phantom_data, category)

            # ── Incorpora HRV como evidência adicional ──
            hrv_factor = self._hrv_evidence_factor(hrv_metrics, category)

            # ── Incorpora anomaly score ──
            anomaly_factor = self._anomaly_evidence_factor(
                anomaly_score, category
            )

            joint = prior * likelihood * hrv_factor * anomaly_factor
            unnormalized[category] = joint

            logger.debug(
                "  %s: prior=%.4f, lik=%.6f, hrv_f=%.4f, anom_f=%.4f → joint=%.8f",
                category,
                prior,
                likelihood,
                hrv_factor,
                anomaly_factor,
                joint,
            )

        # Normalização
        total = sum(unnormalized.values())
        if total <= 0:
            logger.error("Soma das probabilidades conjuntas é zero ou negativa.")
            return self._priors_as_posteriors()

        results: list[dict[str, Any]] = []
        for category, joint in unnormalized.items():
            posterior = joint / total
            results.append(
                {
                    "category": category,
                    "prior": round(self.priors.get(category, 0.05), 6),
                    "likelihood": round(
                        self._compute_likelihood(phantom_data, category), 6
                    ),
                    "posterior": round(posterior, 6),
                    "severity": self._severity_from_posterior(posterior),
                }
            )

        results.sort(key=lambda x: x["posterior"], reverse=True)

        logger.info(
            "Posterior computado — Top categoria: '%s' (%.4f, %s)",
            results[0]["category"],
            results[0]["posterior"],
            results[0]["severity"],
        )
        return results

    def generate_diagnostic_hypotheses(
        self,
        phantom_data: dict[str, float],
        hrv_metrics: dict[str, float] | None = None,
        anomaly_score: dict[str, float] | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Gera as top-k hipóteses diagnósticas com evidências de suporte.

        Combina a inferência bayesiana posterior com metadados clínicos
        da ontologia para produzir hipóteses acionáveis com:
            - Códigos clínicos padronizados (ICD-10, SNOMED)
            - Nível de confiança qualitativo
            - Evidências de suporte (quais sinais contribuíram)
            - Ações recomendadas baseadas na severidade

        Args:
            phantom_data: Valores estimados dos sinais fantasma.
            hrv_metrics: Métricas HRV opcionais.
            anomaly_score: Scores de anomalia opcionais.
            top_k: Número de hipóteses a retornar (padrão: 3).

        Returns:
            Lista das top-k hipóteses diagnósticas, cada uma contendo:
                - category (str)
                - posterior_probability (float)
                - confidence_level (str): 'high', 'medium', ou 'low'
                - relevant_icd10_codes (list[str])
                - relevant_snomed_codes (list[str])
                - supporting_evidence (list[dict])
                - recommended_actions (list[str])
                - severity (str)
        """
        posteriors = self.compute_posterior(
            phantom_data, hrv_metrics, anomaly_score
        )

        top_results = posteriors[:top_k]
        hypotheses: list[dict[str, Any]] = []

        for result in top_results:
            category = result["category"]
            posterior = result["posterior"]
            cat_data = self.ontology.get(category, {})

            # ── Evidências de suporte ──
            supporting_evidence = self._gather_supporting_evidence(
                phantom_data, category
            )

            # ── Nível de confiança ──
            confidence_level = self._confidence_from_posterior(posterior)

            # ── Ações recomendadas ──
            recommended_actions = self._generate_recommended_actions(
                category, result["severity"], posterior
            )

            hypothesis = {
                "category": category,
                "posterior_probability": posterior,
                "confidence_level": confidence_level,
                "severity": result["severity"],
                "relevant_icd10_codes": list(cat_data.get("icd10", [])),
                "relevant_snomed_codes": list(cat_data.get("snomed", [])),
                "supporting_evidence": supporting_evidence,
                "recommended_actions": recommended_actions,
            }
            hypotheses.append(hypothesis)

        logger.info(
            "Geradas %d hipóteses diagnósticas (top_k=%d)", len(hypotheses), top_k
        )
        return hypotheses

    # ── Métodos de severidade e confiança ────────────────────────────────

    def _severity_from_posterior(self, posterior: float) -> str:
        """Mapeia probabilidade posterior para nível de severidade.

        Limiares:
            - > 0.7  → 'critical'
            - > 0.4  → 'elevated'
            - > 0.2  → 'moderate'
            - ≤ 0.2  → 'low'

        Args:
            posterior: Probabilidade posterior da condição.

        Returns:
            String indicando nível de severidade.
        """
        if posterior > 0.7:
            return "critical"
        elif posterior > 0.4:
            return "elevated"
        elif posterior > 0.2:
            return "moderate"
        else:
            return "low"

    @staticmethod
    def _confidence_from_posterior(posterior: float) -> str:
        """Mapeia probabilidade posterior para nível de confiança qualitativo.

        Args:
            posterior: Probabilidade posterior.

        Returns:
            'high' se posterior > 0.6, 'medium' se > 0.3, senão 'low'.
        """
        if posterior > 0.6:
            return "high"
        elif posterior > 0.3:
            return "medium"
        else:
            return "low"

    # ── Métodos auxiliares ────────────────────────────────────────────────

    def _hrv_evidence_factor(
        self,
        hrv_metrics: dict[str, float] | None,
        category: str,
    ) -> float:
        """Computa fator de evidência baseado em métricas HRV.

        Métricas HRV influenciam primariamente categorias cardiovascular
        e neurológica/autonômica. LF/HF ratio elevado sugere desequilíbrio
        autonômico; SDNN/RMSSD baixos sugerem risco cardiovascular.

        Args:
            hrv_metrics: Dicionário com métricas HRV.
            category: Categoria clínica sendo avaliada.

        Returns:
            Fator multiplicativo >= 0.5. Valores > 1.0 amplificam a
            verossimilhança; < 1.0 atenuam.
        """
        if not hrv_metrics:
            return 1.0

        factor = 1.0

        if category == "cardiovascular":
            # SDNN baixo (< 50ms) = risco cardiovascular aumentado
            sdnn = hrv_metrics.get("sdnn")
            if sdnn is not None:
                if sdnn < 50:
                    factor *= 1.0 + (50 - sdnn) / 50.0
                elif sdnn > 100:
                    factor *= 0.7  # HRV alta = protetor

            # RMSSD baixo indica tônus vagal reduzido
            rmssd = hrv_metrics.get("rmssd")
            if rmssd is not None and rmssd < 20:
                factor *= 1.3

        elif category == "neurological_autonomic":
            # LF/HF ratio alto indica dominância simpática
            lf_hf = hrv_metrics.get("lf_hf_ratio")
            if lf_hf is not None:
                if lf_hf > 2.5:
                    factor *= 1.0 + (lf_hf - 2.5) * 0.3
                elif lf_hf < 0.5:
                    factor *= 1.2  # Dominância parassimpática extrema

            # RMSSD como indicador vagal
            rmssd = hrv_metrics.get("rmssd")
            if rmssd is not None and rmssd < 15:
                factor *= 1.4

        elif category == "respiratory":
            # Respiratory sinus arrhythmia reduzida (via RMSSD)
            rmssd = hrv_metrics.get("rmssd")
            if rmssd is not None and rmssd < 10:
                factor *= 1.2

        return max(factor, 0.5)

    def _anomaly_evidence_factor(
        self,
        anomaly_score: dict[str, float] | None,
        category: str,
    ) -> float:
        """Computa fator de evidência a partir de scores de anomalia.

        Scores de anomalia elevados (geralmente 0–1, onde 1 = alta anomalia)
        amplificam a verossimilhança da condição correspondente.

        Args:
            anomaly_score: Dicionário com scores de anomalia.
                Chave 'global' para score geral; chaves por categoria
                para scores específicos.
            category: Categoria clínica sendo avaliada.

        Returns:
            Fator multiplicativo >= 0.5.
        """
        if not anomaly_score:
            return 1.0

        factor = 1.0

        # Score específico da categoria
        cat_score = anomaly_score.get(category)
        if cat_score is not None:
            # Score alto amplifica (ex: score 0.8 → fator ~1.6)
            factor *= 1.0 + cat_score * 0.75

        # Score global como evidência secundária
        global_score = anomaly_score.get("global")
        if global_score is not None:
            factor *= 1.0 + global_score * 0.25

        return max(factor, 0.5)

    def _gather_supporting_evidence(
        self, phantom_data: dict[str, float], category: str
    ) -> list[dict[str, Any]]:
        """Identifica quais sinais fantasma contribuíram para a hipótese.

        Args:
            phantom_data: Valores dos sinais fantasma.
            category: Categoria clínica.

        Returns:
            Lista de dicionários descrevendo cada sinal que contribuiu,
            com valor observado, faixa normal, e desvio.
        """
        cat_data = self.ontology.get(category, {})
        thresholds = cat_data.get("risk_thresholds", {})
        phantom_signals = cat_data.get("phantom_signals", [])
        evidence: list[dict[str, Any]] = []

        for signal_name in phantom_signals:
            if signal_name not in phantom_data:
                continue

            value = phantom_data[signal_name]
            entry: dict[str, Any] = {
                "signal": signal_name,
                "observed_value": round(value, 4),
            }

            if signal_name in thresholds:
                low, high = thresholds[signal_name]
                entry["normal_range"] = {"low": low, "high": high}
                entry["within_normal"] = low <= value <= high

                if value < low:
                    entry["deviation"] = round(value - low, 4)
                    entry["direction"] = "below_normal"
                elif value > high:
                    entry["deviation"] = round(value - high, 4)
                    entry["direction"] = "above_normal"
                else:
                    entry["deviation"] = 0.0
                    entry["direction"] = "within_normal"

            evidence.append(entry)

        return evidence

    def _generate_recommended_actions(
        self, category: str, severity: str, posterior: float
    ) -> list[str]:
        """Gera ações recomendadas baseadas na categoria e severidade.

        Args:
            category: Categoria clínica.
            severity: Nível de severidade ('critical', 'elevated', etc.).
            posterior: Probabilidade posterior.

        Returns:
            Lista de strings com ações recomendadas.
        """
        actions: list[str] = []

        # Ações baseadas na severidade
        severity_actions = {
            "critical": [
                "Encaminhamento urgente para avaliação especializada",
                "Monitoramento contínuo recomendado",
                "Considerar intervenção imediata",
            ],
            "elevated": [
                "Agendar consulta com especialista",
                "Aumentar frequência de monitoramento",
                "Revisar medicação atual",
            ],
            "moderate": [
                "Acompanhamento ambulatorial recomendado",
                "Monitoramento periódico",
            ],
            "low": [
                "Manter monitoramento de rotina",
            ],
        }
        actions.extend(severity_actions.get(severity, []))

        # Ações específicas por categoria
        category_specific: dict[str, list[str]] = {
            "cardiovascular": [
                "Verificar ECG de 12 derivações",
                "Avaliar perfil lipídico",
            ],
            "respiratory": [
                "Verificar espirometria",
                "Avaliar oximetria contínua",
            ],
            "metabolic": [
                "Solicitar hemoglobina glicada (HbA1c)",
                "Avaliar perfil metabólico completo",
            ],
            "neurological_autonomic": [
                "Avaliar qualidade do sono (polissonografia)",
                "Considerar avaliação neurológica",
            ],
            "telemedicine_digital_health": [
                "Verificar calibração dos dispositivos",
                "Avaliar conectividade e qualidade dos dados",
            ],
        }

        if severity in ("critical", "elevated") and category in category_specific:
            actions.extend(category_specific[category])

        return actions

    def _priors_as_posteriors(self) -> list[dict[str, Any]]:
        """Retorna priors formatados como posteriors (fallback para dados vazios).

        Returns:
            Lista de posteriors iguais aos priors normalizados.
        """
        total = sum(self.priors.values())
        if total <= 0:
            total = 1.0

        results = [
            {
                "category": cat,
                "prior": round(p, 6),
                "likelihood": 1.0,
                "posterior": round(p / total, 6),
                "severity": self._severity_from_posterior(p / total),
            }
            for cat, p in self.priors.items()
        ]
        results.sort(key=lambda x: x["posterior"], reverse=True)
        return results


# ──────────────────────────────────────────────────────────────────────────────
# Relatório Enriquecido com Ontologia
# ──────────────────────────────────────────────────────────────────────────────


class OntologyEnrichedReport:
    """Gerador de relatórios clínicos enriquecidos com ontologia.

    Compõe o mapeador de ontologia clínica e a rede diagnóstica bayesiana
    para produzir relatórios abrangentes que integram:
        - Estimativas de sinais fantasma
        - Hipóteses diagnósticas probabilísticas
        - Contexto de tópicos da literatura (LDA)
        - Códigos clínicos padronizados

    Atributos:
        ontology_mapper (ClinicalOntologyMapper): Mapeador de ontologia.
        bayesian_network (BayesianDiagnosticNetwork): Rede bayesiana.

    Exemplo de uso:
        >>> mapper = ClinicalOntologyMapper()
        >>> network = BayesianDiagnosticNetwork()
        >>> report_gen = OntologyEnrichedReport(mapper, network)
        >>> relatorio = report_gen.generate_patient_report(
        ...     patient_id='P001',
        ...     phantom_data={'systolic_bp': 155.0, 'spo2': 96.0}
        ... )
    """

    def __init__(
        self,
        ontology_mapper: ClinicalOntologyMapper,
        bayesian_network: BayesianDiagnosticNetwork,
    ) -> None:
        """Inicializa o gerador de relatórios.

        Args:
            ontology_mapper: Instância do mapeador de ontologia clínica.
            bayesian_network: Instância da rede diagnóstica bayesiana.
        """
        self.ontology_mapper = ontology_mapper
        self.bayesian_network = bayesian_network
        logger.info("OntologyEnrichedReport inicializado.")

    def generate_patient_report(
        self,
        patient_id: str,
        phantom_data: dict[str, float],
        hrv_metrics: dict[str, float] | None = None,
        anomaly_score: dict[str, float] | None = None,
        topic_context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Gera relatório abrangente do paciente combinando múltiplas fontes.

        O relatório integra:
            1. Dados de sinais fantasma e suas interpretações
            2. Hipóteses diagnósticas bayesianas com probabilidades
            3. Contexto de tópicos da literatura (se disponível)
            4. Códigos clínicos padronizados consolidados
            5. Resumo executivo e recomendações

        Args:
            patient_id: Identificador único do paciente (anonimizado).
            phantom_data: Valores estimados dos sinais fantasma.
            hrv_metrics: Métricas HRV opcionais.
            anomaly_score: Scores de anomalia opcionais.
            topic_context: Contexto de tópicos LDA opcionais (resultado
                de ClinicalOntologyMapper.map_all_topics).

        Returns:
            Dicionário estruturado adequado para serialização JSON,
            contendo todas as seções do relatório.
        """
        logger.info("Gerando relatório para paciente '%s'...", patient_id)

        # ── 1. Hipóteses diagnósticas ──
        hypotheses = self.bayesian_network.generate_diagnostic_hypotheses(
            phantom_data,
            hrv_metrics=hrv_metrics,
            anomaly_score=anomaly_score,
            top_k=3,
        )

        # ── 2. Posterior completo ──
        full_posterior = self.bayesian_network.compute_posterior(
            phantom_data,
            hrv_metrics=hrv_metrics,
            anomaly_score=anomaly_score,
        )

        # ── 3. Consolidação de códigos clínicos ──
        all_icd10: list[str] = []
        all_snomed: list[str] = []
        all_mesh: list[str] = []
        for hyp in hypotheses:
            all_icd10.extend(hyp.get("relevant_icd10_codes", []))
            all_snomed.extend(hyp.get("relevant_snomed_codes", []))
        # Adicionar MeSH das categorias das hipóteses
        for hyp in hypotheses:
            cat = hyp.get("category", "")
            cat_data = self.bayesian_network.ontology.get(cat, {})
            all_mesh.extend(cat_data.get("mesh", []))

        # ── 4. Interpretação de sinais fantasma ──
        phantom_interpretation = self._interpret_phantom_data(phantom_data)

        # ── 5. Contexto de literatura ──
        literature_context = self._process_topic_context(topic_context)

        # ── 6. Resumo executivo ──
        executive_summary = self._generate_executive_summary(
            patient_id, hypotheses, phantom_interpretation
        )

        # ── 7. Metadados ──
        report = {
            "report_metadata": {
                "patient_id": patient_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "report_version": "1.0.0",
                "model_version": "bayesian_v1",
            },
            "executive_summary": executive_summary,
            "phantom_signals": {
                "raw_values": phantom_data,
                "interpretation": phantom_interpretation,
            },
            "diagnostic_hypotheses": hypotheses,
            "full_posterior_distribution": full_posterior,
            "clinical_codes": {
                "icd10": sorted(set(all_icd10)),
                "snomed": sorted(set(all_snomed)),
                "mesh": sorted(set(all_mesh)),
            },
            "hrv_context": self._hrv_summary(hrv_metrics),
            "anomaly_context": self._anomaly_summary(anomaly_score),
            "literature_context": literature_context,
        }

        logger.info(
            "Relatório gerado para paciente '%s' — %d hipóteses, "
            "%d códigos ICD-10 únicos.",
            patient_id,
            len(hypotheses),
            len(report["clinical_codes"]["icd10"]),
        )
        return report

    # ── Métodos auxiliares do relatório ───────────────────────────────────

    def _interpret_phantom_data(
        self, phantom_data: dict[str, float]
    ) -> list[dict[str, Any]]:
        """Interpreta cada sinal fantasma em relação aos limiares de risco.

        Args:
            phantom_data: Valores dos sinais fantasma.

        Returns:
            Lista de interpretações por sinal.
        """
        interpretations: list[dict[str, Any]] = []

        for signal_name, value in phantom_data.items():
            entry: dict[str, Any] = {
                "signal": signal_name,
                "value": round(value, 4),
                "status": "unknown",
                "related_categories": [],
            }

            # Buscar em todas as categorias
            for cat_name, cat_data in self.bayesian_network.ontology.items():
                thresholds = cat_data.get("risk_thresholds", {})
                if signal_name in thresholds:
                    low, high = thresholds[signal_name]
                    entry["related_categories"].append(cat_name)
                    entry["normal_range"] = {"low": low, "high": high}

                    if value < low:
                        entry["status"] = "below_normal"
                        entry["alert"] = (
                            f"Valor {value:.1f} abaixo do limiar inferior ({low})"
                        )
                    elif value > high:
                        entry["status"] = "above_normal"
                        entry["alert"] = (
                            f"Valor {value:.1f} acima do limiar superior ({high})"
                        )
                    else:
                        entry["status"] = "within_normal"

            interpretations.append(entry)

        return interpretations

    def _process_topic_context(
        self, topic_context: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        """Processa contexto de tópicos LDA para inclusão no relatório.

        Args:
            topic_context: Resultado de map_all_topics ou None.

        Returns:
            Lista processada de tópicos relevantes com enriquecimento
            ontológico, ou lista vazia se não disponível.
        """
        if not topic_context:
            return []

        processed: list[dict[str, Any]] = []
        for topic in topic_context:
            category = topic.get("best_category", "unknown")
            score = topic.get("combined_score", 0.0)

            # Só inclui tópicos com relevância mínima
            if score < 0.05:
                continue

            enriched: dict[str, Any] = {
                "topic_index": topic.get("topic_index"),
                "mapped_category": category,
                "relevance_score": score,
            }

            # Enriquecer com contexto ontológico
            try:
                context = self.ontology_mapper.get_ontology_context(category)
                enriched["ontology_context"] = {
                    "icd10": context.get("icd10", []),
                    "mesh": context.get("mesh", []),
                }
            except KeyError:
                enriched["ontology_context"] = {}

            processed.append(enriched)

        return processed

    @staticmethod
    def _hrv_summary(
        hrv_metrics: dict[str, float] | None,
    ) -> dict[str, Any]:
        """Gera resumo interpretativo das métricas HRV.

        Args:
            hrv_metrics: Métricas HRV ou None.

        Returns:
            Dicionário com resumo das métricas e interpretações.
        """
        if not hrv_metrics:
            return {"available": False, "summary": "Métricas HRV não disponíveis."}

        summary: dict[str, Any] = {
            "available": True,
            "metrics": hrv_metrics,
            "interpretations": [],
        }

        sdnn = hrv_metrics.get("sdnn")
        if sdnn is not None:
            if sdnn < 50:
                summary["interpretations"].append(
                    "SDNN reduzido — possível risco cardiovascular aumentado."
                )
            elif sdnn > 100:
                summary["interpretations"].append(
                    "SDNN dentro da faixa saudável — boa variabilidade cardíaca."
                )

        rmssd = hrv_metrics.get("rmssd")
        if rmssd is not None:
            if rmssd < 20:
                summary["interpretations"].append(
                    "RMSSD baixo — tônus vagal possivelmente reduzido."
                )

        lf_hf = hrv_metrics.get("lf_hf_ratio")
        if lf_hf is not None:
            if lf_hf > 2.5:
                summary["interpretations"].append(
                    "LF/HF ratio elevado — predominância simpática."
                )
            elif lf_hf < 0.5:
                summary["interpretations"].append(
                    "LF/HF ratio baixo — predominância parassimpática."
                )

        return summary

    @staticmethod
    def _anomaly_summary(
        anomaly_score: dict[str, float] | None,
    ) -> dict[str, Any]:
        """Gera resumo dos scores de anomalia.

        Args:
            anomaly_score: Scores de anomalia ou None.

        Returns:
            Dicionário com resumo e flag de alerta.
        """
        if not anomaly_score:
            return {"available": False, "summary": "Scores de anomalia não disponíveis."}

        high_anomalies = {
            k: v for k, v in anomaly_score.items() if v > 0.7
        }

        return {
            "available": True,
            "scores": anomaly_score,
            "high_anomaly_categories": list(high_anomalies.keys()),
            "alert": len(high_anomalies) > 0,
        }

    @staticmethod
    def _generate_executive_summary(
        patient_id: str,
        hypotheses: list[dict[str, Any]],
        phantom_interpretation: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Gera resumo executivo do relatório.

        Args:
            patient_id: ID do paciente.
            hypotheses: Hipóteses diagnósticas.
            phantom_interpretation: Interpretação dos sinais fantasma.

        Returns:
            Dicionário com resumo executivo estruturado.
        """
        # Sinais anormais
        abnormal_signals = [
            interp
            for interp in phantom_interpretation
            if interp.get("status") in ("above_normal", "below_normal")
        ]

        # Hipótese principal
        primary = hypotheses[0] if hypotheses else {}
        primary_severity = primary.get("severity", "unknown")

        # Nível de alerta geral
        if primary_severity == "critical":
            alert_level = "ALTO"
            alert_message = (
                "Sinais de alerta críticos detectados. "
                "Recomenda-se avaliação médica imediata."
            )
        elif primary_severity == "elevated":
            alert_level = "MODERADO"
            alert_message = (
                "Indicadores elevados detectados. "
                "Recomenda-se acompanhamento próximo."
            )
        else:
            alert_level = "BAIXO"
            alert_message = "Indicadores dentro dos padrões esperados."

        return {
            "patient_id": patient_id,
            "alert_level": alert_level,
            "alert_message": alert_message,
            "primary_hypothesis": primary.get("category", "N/A"),
            "primary_probability": primary.get("posterior_probability", 0.0),
            "abnormal_signal_count": len(abnormal_signals),
            "total_signals_evaluated": len(phantom_interpretation),
            "confidence": primary.get("confidence_level", "low"),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Demonstração
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    print("=" * 72)
    print("  DEMONSTRAÇÃO — Rede Diagnóstica Bayesiana e Relatório Enriquecido")
    print("=" * 72)

    # ── Dados sintéticos de sinais fantasma ──
    phantom_data_critical = {
        "systolic_bp": 165.0,     # Acima do normal (90–140)
        "diastolic_bp": 95.0,     # Acima do normal (60–90)
        "spo2": 92.0,             # Abaixo do normal (95–100)
        "glucose": 210.0,         # Acima do normal (70–140)
        "vagal_tone": 15.0,       # Abaixo do normal (20–80)
    }

    phantom_data_normal = {
        "systolic_bp": 120.0,
        "diastolic_bp": 75.0,
        "spo2": 98.0,
        "glucose": 95.0,
        "vagal_tone": 55.0,
    }

    hrv_metrics_abnormal = {
        "sdnn": 35.0,             # Baixo (< 50ms)
        "rmssd": 12.0,            # Baixo (< 20ms)
        "lf_hf_ratio": 3.2,      # Elevado (> 2.5)
    }

    anomaly_score_high = {
        "global": 0.75,
        "cardiovascular": 0.85,
        "respiratory": 0.60,
    }

    # ── 1. Rede Bayesiana ──
    print("\n─── Rede Diagnóstica Bayesiana ───")
    network = BayesianDiagnosticNetwork()

    print("\n>> Cenário CRÍTICO (valores anormais + HRV alterado + anomalias):")
    hypotheses = network.generate_diagnostic_hypotheses(
        phantom_data_critical,
        hrv_metrics=hrv_metrics_abnormal,
        anomaly_score=anomaly_score_high,
        top_k=3,
    )
    for h in hypotheses:
        print(
            f"  {h['category']:30s} → P={h['posterior_probability']:.4f} "
            f"[{h['confidence_level']:6s}] severity={h['severity']}"
        )
        print(f"    ICD-10: {h['relevant_icd10_codes']}")
        if h["supporting_evidence"]:
            for ev in h["supporting_evidence"]:
                print(
                    f"    ↳ {ev['signal']}: {ev['observed_value']:.1f} "
                    f"({'⚠ ' + ev.get('direction', '') if not ev.get('within_normal', True) else '✓ normal'})"
                )

    print("\n>> Cenário NORMAL (valores dentro da faixa):")
    hypotheses_normal = network.generate_diagnostic_hypotheses(
        phantom_data_normal, top_k=3
    )
    for h in hypotheses_normal:
        print(
            f"  {h['category']:30s} → P={h['posterior_probability']:.4f} "
            f"[{h['confidence_level']:6s}] severity={h['severity']}"
        )

    # ── 2. Relatório Enriquecido ──
    print("\n─── Relatório Enriquecido com Ontologia ───")
    mapper = ClinicalOntologyMapper()
    report_gen = OntologyEnrichedReport(mapper, network)

    # Simula contexto de tópicos LDA
    topic_context = [
        {
            "topic_index": 0,
            "best_category": "cardiovascular",
            "combined_score": 0.72,
        },
        {
            "topic_index": 1,
            "best_category": "metabolic",
            "combined_score": 0.65,
        },
    ]

    report = report_gen.generate_patient_report(
        patient_id="PATIENT_2025_001",
        phantom_data=phantom_data_critical,
        hrv_metrics=hrv_metrics_abnormal,
        anomaly_score=anomaly_score_high,
        topic_context=topic_context,
    )

    # Exibe resumo executivo
    print("\n>> Resumo Executivo:")
    exec_summary = report["executive_summary"]
    print(f"  Paciente: {exec_summary['patient_id']}")
    print(f"  Alerta: {exec_summary['alert_level']} — {exec_summary['alert_message']}")
    print(f"  Hipótese principal: {exec_summary['primary_hypothesis']}")
    print(f"  Probabilidade: {exec_summary['primary_probability']:.4f}")
    print(f"  Sinais anormais: {exec_summary['abnormal_signal_count']}/{exec_summary['total_signals_evaluated']}")

    # Exibe códigos clínicos consolidados
    print("\n>> Códigos Clínicos Consolidados:")
    codes = report["clinical_codes"]
    print(f"  ICD-10: {codes['icd10']}")
    print(f"  SNOMED: {codes['snomed']}")
    print(f"  MeSH:   {codes['mesh']}")

    # Exibe JSON parcial
    print("\n>> Relatório completo (JSON):")
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str)[:3000])
    print("  ... (truncado)")

    print("\n✓ Demonstração concluída.")
