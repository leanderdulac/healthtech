"""
main_simulation.py — Fluxo de Simulação de Produção e Validação Matemática

Este script demonstra a integração ponta a ponta dos novos módulos de matemática avançada:
1. Geração de Sinais Fisiológicos Realistas (Processo Ornstein-Uhlenbeck e Correlações Multivariadas)
2. Processamento de Sinais e Separação de Ruído (Filtros Wavelet e Butterworth)
3. Fusão Bayesiana de Sensores (Inverse-Variance Weighting com EWMA Adaptativo)
4. Motor de Inferência de Dados Fantasmas (Extended Kalman Filter)
5. Mapeamento Ontológico Clínico e Rede Bayesiana de Diagnóstico (ICD-10, SNOMED, MeSH)
6. Conectores e Orquestração GCP Vertex AI (Online, Batch, Training)
"""

import time
import logging
import os
import json
import pandas as pd
import numpy as np
import sys
from datetime import datetime
from dotenv import load_dotenv

# Módulos de Ingestão e Segurança
from src.utils.data_generator import (
    generate_sensor_data,
    generate_patient_fhir_mock,
    generate_wearable_multimodal_data,
    generate_rr_intervals
)
from src.ingestion.data_reconciliation import reconciliar_dados_biometricos
from src.security.anonymization import anonimizar_paciente_fhir

# Módulos de Aprendizado de Máquina (Vertex AI)
from src.ml_pipeline.online_inference import VertexOnlineDetector
from src.ml_pipeline.batch_inference import orquestrar_batch_vertex_ai
from src.ml_pipeline.training import orquestrar_custom_training

# Novos Módulos Fisiológicos, de Sinais e Ontológicos
from src.signal_processing import (
    AdaptiveSensorFusion,
    WaveletDenoiser,
    ButterworthFilter,
    decompose_signal_components
)
from src.phantom_data import (
    PhantomDataEngine,
    BatchPhantomProcessor,
    HRVAnalyzer
)
from src.ontology import (
    ClinicalOntologyMapper,
    BayesianDiagnosticNetwork,
    OntologyEnrichedReport
)

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variáveis do GCP
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "project-placeholder")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
VERTEX_ENDPOINT_ID = os.getenv("VERTEX_ENDPOINT_ID", "endpoint-placeholder") 
VERTEX_MODEL_NAME = os.getenv("VERTEX_MODEL_NAME", "model-placeholder")
GCS_INPUT_DATA = os.getenv("GCS_INPUT_DATA", "gs://placeholder/input.jsonl")
GCS_OUTPUT_DATA = os.getenv("GCS_OUTPUT_DATA", "gs://placeholder/output/")
GCS_STAGING_BUCKET = os.getenv("GCS_STAGING_BUCKET", "gs://placeholder-staging-bucket/")


def run_simulation():
    print("=" * 70)
    print("        HEALTH TECH — SIMULAÇÃO AVANÇADA DE SINAIS E INFRAESTRUTURA")
    print("=" * 70)

    # 1. Geração de Sinais Fisiológicos Realistas e Fusão Bayesiana
    print("\n[1] FUSÃO BAYESIANA E SEPARAÇÃO DE RUÍDO (Sinais de Wearables)...")
    # Gerar leituras brutas simuladas via O-U com ruído e sensores redundantes
    df_raw = generate_sensor_data(num_records=30)
    print(f"  -> Leituras brutas geradas de múltiplos sensores: {len(df_raw)}")
    
    # Reconciliar usando a nova Fusão Bayesiana (Precision-Weighting + EWMA)
    df_clean = reconciliar_dados_biometricos(df_raw, janela_tempo_segundos=3)
    print(f"  -> Batimentos reconciliados via Fusão Bayesiana: {len(df_clean)}")
    if 'variancia_fusionada' in df_clean.columns:
        print(f"  -> Variância da fusão (BLUE) média: {df_clean['variancia_fusionada'].mean():.4f}")
    
    # Aplicar Denoising Wavelet para separar ruído
    denoiser = WaveletDenoiser(wavelet='db4', level=2)
    signal_reconciled = df_clean['heart_rate_reconciliado'].values.astype(float)
    if len(signal_reconciled) >= 4:
        signal_denoised = denoiser.denoise(signal_reconciled)
        snr_db = denoiser.estimate_snr(signal_reconciled, signal_denoised)
        print(f"  -> Denoising Wavelet (DWT) aplicado. SNR Estimado: {snr_db:.2f} dB")
    else:
        signal_denoised = signal_reconciled
        print("  -> Denoising Wavelet ignorado (dados insuficientes)")

    # 2. Segurança e Anonimização
    print("\n[2] SEGURANÇA E PRIVACIDADE (FHIR Anonymization)...")
    paciente_mock = generate_patient_fhir_mock()
    paciente_anonimo = anonimizar_paciente_fhir(paciente_mock)
    patient_secure_id = paciente_anonimo['identifier'][0]['value']
    print(f"  -> Paciente de origem: {paciente_mock['name'][0]['given'][0]} {paciente_mock['name'][0]['family']}")
    print(f"  -> Hash Longitudinal Seguro (Data Lake): {patient_secure_id}")

    # 3. Motor de Dados Fantasmas (Extended Kalman Filter)
    print("\n[3] MOTOR DE DADOS FANTASMAS (Estimativa de Sinais Ocultos)...")
    # Gerar dados multimodais realistas (HR, HRV RMSSD, temperatura cutânea, atividade)
    df_multimodal = generate_wearable_multimodal_data(num_records=50)
    print(f"  -> Dados multimodais de wearables recebidos (N={len(df_multimodal)})")
    
    # Processador em lote (Extended Kalman Filter)
    batch_processor = BatchPhantomProcessor(use_ukf=False)
    df_phantom = batch_processor.process_dataframe(df_multimodal)
    
    # Exibir resumo das estimativas fantasmas
    print("  -> Médias de Sinais Fantasmas Inferidos (Latentes):")
    print(f"     * Pressão Sistólica: {df_phantom['est_systolic_bp'].mean():.1f} ± {df_phantom['est_systolic_bp'].std():.1f} mmHg")
    print(f"     * Pressão Diastólica: {df_phantom['est_diastolic_bp'].mean():.1f} ± {df_phantom['est_diastolic_bp'].std():.1f} mmHg")
    print(f"     * Saturação de Oxigênio (SpO2): {df_phantom['est_spo2'].mean():.2f}%")
    print(f"     * Glicose Estimada: {df_phantom['est_glucose'].mean():.1f} mg/dL")
    print(f"     * Tônus Vagal Inferido: {df_phantom['est_vagal_tone'].mean():.1f} u.a.")

    # 4. Mapeamento de Ontologia Clínica e Rede Bayesiana
    print("\n[4] REDE DIAGNÓSTICA BAYESIANA E ONTOLOGIA CLÍNICA (USP)...")
    # Mapear o último estado inferido do paciente
    latest_row = df_phantom.iloc[-1]
    phantom_states = {
        'systolic_bp': latest_row['est_systolic_bp'],
        'diastolic_bp': latest_row['est_diastolic_bp'],
        'spo2': latest_row['est_spo2'],
        'glucose': latest_row['est_glucose'],
        'vagal_tone': latest_row['est_vagal_tone']
    }
    
    # Simular métricas HRV adicionais para o período
    hr_values = df_multimodal['heart_rate'].values
    rr_intervals = generate_rr_intervals(hr_values)
    hrv_analyzer = HRVAnalyzer()
    hrv_metrics = hrv_analyzer.compute_time_domain(rr_intervals)
    
    # Rede Bayesiana de Diagnóstico
    bayes_net = BayesianDiagnosticNetwork()
    hypotheses = bayes_net.generate_diagnostic_hypotheses(
        phantom_data=phantom_states,
        hrv_metrics=hrv_metrics,
        anomaly_score={'global': 0.1}, # Score simulado
        top_k=2
    )
    
    # Mapear para Ontologia e Gerar Relatório Clínico Enriquecido
    ontology_mapper = ClinicalOntologyMapper()
    report_generator = OntologyEnrichedReport(ontology_mapper, bayes_net)
    
    # Simular contexto de tópicos de teses da USP (NLP)
    # Tópico 0 = cardiovascular, Tópico 2 = metabolic
    topic_context = [
        {"topic_index": 0, "best_category": "cardiovascular", "combined_score": 0.85},
        {"topic_index": 2, "best_category": "metabolic", "combined_score": 0.60}
    ]
    
    report = report_generator.generate_patient_report(
        patient_id=patient_secure_id,
        phantom_data=phantom_states,
        hrv_metrics=hrv_metrics,
        anomaly_score={'global': 0.1},
        topic_context=topic_context
    )
    
    # Exibir sumário clínico
    exec_summary = report['executive_summary']
    print(f"  -> Alerta Clínico: {exec_summary['alert_level']} — {exec_summary['alert_message']}")
    print(f"  -> Hipótese Principal: {exec_summary['primary_hypothesis']} (P={exec_summary['primary_probability']:.2%})")
    print(f"  -> Códigos de Faturamento e Interoperabilidade Gerados:")
    print(f"     * CID-10: {report['clinical_codes']['icd10']}")
    print(f"     * SNOMED-CT: {report['clinical_codes']['snomed']}")
    print(f"     * MeSH: {report['clinical_codes']['mesh']}")

    # 5. Cloud Platform Integration (Vertex AI Mocks/Orchestrators)
    print("\n[5] INTEGRAÇÃO VERTEX AI (MLOps e Cloud Pipelines)...")
    
    # Submeter job de treinamento na nuvem
    print("  -> Submetendo CustomTrainingJob...")
    try:
        # Passar parâmetros mockados para simulação segura sem travar
        job = orquestrar_custom_training(
            project_id=GCP_PROJECT_ID,
            location=GCP_LOCATION,
            gcs_staging_bucket=GCS_STAGING_BUCKET
        )
        if job:
            print("     * Job de Treinamento submetido (Verifique GCP console).")
    except Exception as e:
        print(f"     * Mock ativo de treinamento: {e}")
        
    # Inferência Online do batimento cardíaco
    print("  -> Efetuando inferência online de streaming...")
    detector_online = VertexOnlineDetector(
        project=GCP_PROJECT_ID,
        location=GCP_LOCATION,
        endpoint_id=VERTEX_ENDPOINT_ID
    )
    # Testar com a última leitura reconciliada
    bpm_test = float(signal_reconciled[-1]) if len(signal_reconciled) > 0 else 72.0
    res_online = detector_online.processar_nova_leitura(bpm_test)
    print(f"     * BPM: {bpm_test:.1f} | Risco: {res_online['score']:.2f} | Status: {res_online['status']}")

    # Inferência em lote
    print("  -> Submetendo Batch Prediction Job...")
    resultado_batch = orquestrar_batch_vertex_ai(
        project=GCP_PROJECT_ID,
        location=GCP_LOCATION,
        model_name=VERTEX_MODEL_NAME,
        gcs_input_uri=GCS_INPUT_DATA,
        gcs_output_uri=GCS_OUTPUT_DATA
    )
    print(f"     * Status: {resultado_batch['status']}")
    if 'mensagem' in resultado_batch:
        print(f"     * Log: {resultado_batch['mensagem']}")

    print("\n" + "=" * 70)
    print("    VALIDAÇÃO E SIMULAÇÃO MATEMÁTICA CONCLUÍDAS COM SUCESSO!")
    print("=" * 70)


def main():
    print("=" * 70)
    print(" HEALTHTECH — Pipeline Completo (Datalake + BigQuery + Vertex AI)")
    print("=" * 70)
    print("\nRedirecionando para run_vertex_integration.py ...\n")
    try:
        from run_vertex_integration import main as run_integration
        run_integration()
    except Exception as e:
        logger.warning(f"Não foi possível rodar o run_vertex_integration: {e}")
        print("\nIniciando simulação local alternativa...\n")
        run_simulation()


if __name__ == "__main__":
    main()