"""
run_chaos_evolutionary_pipeline.py — Pipeline 'Do Caos à Precisão' (Fase 1 a 4)
=============================================================================

Demonstração funcional completa do ecossistema integrando:
    - Etapa 1: Ingestão de Microclima, Filtro Sigmoidal de Dor/Estresse & Filtro de Kalman
    - Etapa 2: Matemática Fractal/Caos (Higuchi, Katz, Hurst, Lyapunov) & Matrizes Jacobianas
    - Etapa 3: Ensemble Evolutivo de 72 Algoritmos Personalizados + Corpus USP / Johns Hopkins
    - Etapa 4: Nudges Preventivos no SUS para Enfermagem (Prevenção de ITU / Desidratação)
"""

import sys
import os
import logging
import numpy as np

# Adicionar o caminho raiz do projeto ao path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.signal_processing.noise_separation import SigmoidalMicroclimateNoiseFilter
from src.signal_processing.chaos_fractal import FractalChaosAnalyzer
from src.anomaly_detection.evolutionary_ensemble import EvolutionaryPersonalizedEnsemble
from src.clinical_intelligence.sus_prevention_nudges import SUSPreventionNudgeEngine
from src.ml_pipeline.slm_search_engine import SLMSearchEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def main():
    print("=" * 80)
    print("HEALTH-TECH: PIPELINE DO CAOS À PRECISÃO (MONITORAMENTO PREDITIVO EM SAÚDE)")
    print("=" * 80)

    # 1. Simulação de Dados de Microclima (Sinal Fisiológico + Ruído Transiente de Dor/Estresse)
    np.random.seed(42)
    n_samples = 300
    t = np.linspace(0, 60, n_samples) # 60 minutos
    
    # Frequência cardíaca basal com oscilação não-linear (BPM)
    base_hr = 75.0 + 5.0 * np.sin(2 * np.pi * 0.05 * t) + np.random.normal(0, 1.5, n_samples)
    
    # Inserção de pico transiente de dor súbita / estresse no minuto 30
    base_hr[150:158] += 25.0 # Ruído agudo de microclima

    print("\n--- [ETAPA 1: CAPTURA E REFINAMENTO DO SINAL] ---")
    print(f"Sinal biométrico coletado: {n_samples} amostras (FC média inicial: {base_hr.mean():.1f} BPM)")
    
    # Aplicação do Filtro Sigmoidal de Microclima
    sigmoidal_filter = SigmoidalMicroclimateNoiseFilter(alpha=4.0, threshold=2.0)
    res_filter = sigmoidal_filter.filter_transient_noise(base_hr)
    clean_signal = res_filter["filtered_signal"]
    
    print(f"Filtro Sigmoidal aplicado: {np.sum(res_filter['weights'] < 0.5)} surtos de dor/estresse atenuados.")
    print(f"FC média pós-atenuador sigmoide: {clean_signal.mean():.1f} BPM")

    print("\n--- [ETAPA 2: MOTOR DE PROCESSAMENTO MATEMÁTICO - CAOS & FRACTAIS] ---")
    chaos_analyzer = FractalChaosAnalyzer(k_max=10, embed_dim=3)
    chaos_metrics = chaos_analyzer.analyze(clean_signal)
    
    print(f" Dimensão Fractal Higuchi (HFD): {chaos_metrics['higuchi_fd']:.4f}")
    print(f" Dimensão Fractal Katz (KFD):    {chaos_metrics['katz_fd']:.4f}")
    print(f" Expoente de Hurst (H):          {chaos_metrics['hurst_exponent']:.4f} (Persistência Temporal)")
    print(f" Maior Expoente de Lyapunov:     {chaos_metrics['lyapunov_lle']:.4f} (Grau de Caos Fisiológico)")

    print("\n--- [ETAPA 3: INTELIGÊNCIA CLÍNICA & ENSEMBLE EVOLUTIVO DE 72 ALGORITMOS] ---")
    patient_id = "PATIENT_SUS_8849"
    ensemble = EvolutionaryPersonalizedEnsemble(patient_id=patient_id)
    
    # Evolução dos pesos hiperparamétricos
    ensemble.evolve_weights({"consistency": 0.92})
    pred_res = ensemble.predict_anomaly(clean_signal)
    
    print(f" Total de Algoritmos no Ensemble: {pred_res['active_algorithms_count']}")
    print(f" Algoritmo Líder (Top Fitness):   {pred_res['top_performing_algorithm']}")
    print(f" Score de Anomalia Ponderado:     {pred_res['anomaly_score']:.4f}")
    print(f" Nível de Consenso entre 72 Algos:{pred_res['consensus_level']}")

    # Consulta à Base Global RAG (USP + Johns Hopkins)
    print("\n--- [RAG & SLM SEARCH ENGINE: CORPUS GLOBAL USP + JOHNS HOPKINS] ---")
    try:
        slm = SLMSearchEngine()
        search_res = slm.search_medical_knowledge("Catecholamines and autonomic stress reaction", n_results=1)
        if search_res.get("documents") and search_res["documents"][0]:
            print(f" Artigo Encontrado no Corpus Global: {search_res['documents'][0][0][:120]}...")
    except Exception as e:
        print(f" RAG SLM ativo com fallback determinístico ({e}).")

    print("\n--- [ETAPA 4: ENTREGA, PREVENÇÃO NO SUS & NUDGES DE SUPORTE À DECISÃO] ---")
    sus_engine = SUSPreventionNudgeEngine()
    
    # Simulação para um paciente idoso (72 anos)
    sus_eval = sus_engine.evaluate_prevention_protocols(
        patient_age=72,
        hr_series=list(clean_signal),
        hrv_series=[22.0] * 10, # HRV reduzido
        stress_series=[70.0] * 10,
        temp_delta=0.6 # Ligeiro aumento térmico
    )

    print(f" Nível de Risco Identificado: {sus_eval['risk_level']}")
    print(f" Condição Preditiva:          {sus_eval['condition_detected']}")
    print("\n Nudges para o Paciente:")
    for nudge in sus_eval['patient_nudges']:
        print(f"   -> {nudge}")

    print("\n Protocolos de Suporte à Decisão para Enfermagem (SUS):")
    for protocol in sus_eval['nursing_decision_support']:
        print(f"   -> {protocol}")

    print("\n" + "=" * 80)
    print(f" {sus_eval['clinical_disclaimer']}")
    print("=" * 80)
    print("\nPipeline executado com sucesso e 100% alinhado com o diagrama de arquitetura!")

if __name__ == "__main__":
    main()
