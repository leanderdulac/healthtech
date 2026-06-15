import time
import logging
from src.utils.data_generator import generate_sensor_data, generate_patient_fhir_mock
from src.ingestion.data_reconciliation import reconciliar_dados_biometricos
from src.security.anonymization import anonimizar_paciente_fhir
from src.ml_pipeline.online_inference import VertexOnlineDetector
from src.ml_pipeline.batch_inference import orquestrar_batch_vertex_ai

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Variáveis do Google Cloud Platform (GCP)
GCP_PROJECT_ID = "project-d28ce7a4-0717-428d-ae4"
GCP_LOCATION = "us-central1"
# ID do Endpoint Online onde o modelo de detecção de arritmia estaria rodando (exemplo)
VERTEX_ENDPOINT_ID = "1234567890123456789" 
# Nome do modelo no Model Registry para Batch Prediction
VERTEX_MODEL_NAME = "modelo-saude-populacional-v2"
GCS_INPUT_DATA = "gs://seu-bucket-datalake/pacientes_fhir/dados_historicos.jsonl"
GCS_OUTPUT_DATA = "gs://seu-bucket-datalake/vertex_predictions/batch_risco/"

def run_simulation():
    print("="*60)
    print(" INICIANDO INTEGRAÇÃO VERTEX AI (ESQUELETO DE PRODUÇÃO) ")
    print("="*60)

    # 1. Coleta e Unificação
    print("\n[1] GERANDO E UNIFICANDO DADOS (Ingestão)...")
    df_raw = generate_sensor_data(num_records=10)
    df_clean = reconciliar_dados_biometricos(df_raw, janela_tempo_segundos=3)
    print(f"Dados reconciliados: {len(df_clean)} batimentos consolidados para streaming.")

    # 2. Segurança
    print("\n[2] ANONIMIZAÇÃO (Privacidade FHIR)...")
    paciente_mock = generate_patient_fhir_mock()
    paciente_anonimo = anonimizar_paciente_fhir(paciente_mock)
    print("ID Seguro (Lakehouse):", paciente_anonimo['identifier'][0]['value'])

    # 3. Inferência Online (Vertex AI Endpoint)
    print("\n[3] INFERÊNCIA ONLINE (Chamando API Vertex AI Endpoint)...")
    # Inicializa o Detector com as credenciais do GCP
    detector_online = VertexOnlineDetector(
        project=GCP_PROJECT_ID, 
        location=GCP_LOCATION, 
        endpoint_id=VERTEX_ENDPOINT_ID
    )
    
    # Simula o streaming enviando batimento a batimento para a nuvem
    for index, row in df_clean.iterrows():
        bpm = row['heart_rate_reconciliado']
        resultado = detector_online.processar_nova_leitura(bpm)
        print(f"  -> BPM: {bpm} | Score: {resultado['score']} | Status: {resultado['status']} [{resultado['modo']}]")
        time.sleep(0.2)

    # 4. Inferência Batch (Vertex AI Batch Prediction)
    print("\n[4] INFERÊNCIA EM LOTE (Submetendo Job no Vertex AI)...")
    resultado_batch = orquestrar_batch_vertex_ai(
        project=GCP_PROJECT_ID,
        location=GCP_LOCATION,
        model_name=VERTEX_MODEL_NAME,
        gcs_input_uri=GCS_INPUT_DATA,
        gcs_output_uri=GCS_OUTPUT_DATA
    )
    
    print("\n=> Status do Job Batch:")
    print(f"Status: {resultado_batch['status']}")
    if 'job_url' in resultado_batch:
        print(f"URL de Acompanhamento (GCP Console): {resultado_batch['job_url']}")
    else:
        print(f"Aviso: {resultado_batch.get('mensagem')}")
        print(f"Resultados seriam exportados para: {resultado_batch.get('gcs_output')}")

    print("\n" + "="*60)
    print(" FLUXO DE INTEGRAÇÃO COM A NUVEM CONCLUÍDO ")
    print("="*60)

if __name__ == "__main__":
    run_simulation()
