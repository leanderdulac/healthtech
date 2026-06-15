import logging
from google.cloud import aiplatform

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def orquestrar_custom_training(project_id: str, location: str, gcs_staging_bucket: str):
    """
    Submete um CustomTrainingJob no Vertex AI.
    Em um cenário real, este script informaria o Vertex para ler dados diretamente 
    do BigQuery, treinar um modelo Scikit-Learn em uma VM na nuvem, e salvar o modelo final.
    """
    aiplatform.init(project=project_id, location=location, staging_bucket=gcs_staging_bucket)
    
    logger.info("Configurando ambiente de treinamento na Nuvem...")
    
    # Este é um container pre-construído do Google com Scikit-Learn
    container_uri = "us-docker.pkg.dev/vertex-ai/training/scikit-learn-cpu.0-23:latest"
    
    # Criamos o Job de treinamento apontando para o script Python local que seria executado NA NUVEM
    # Obs: `train_script.py` seria o arquivo contendo a lógica real de fit (Isolation Forest, etc)
    job = aiplatform.CustomTrainingJob(
        display_name="healthtech_anomaly_training_job",
        script_path="src/ml_pipeline/batch_inference.py", # Reutilizando a lógica base
        container_uri=container_uri,
        requirements=["pandas==2.0.3", "google-cloud-bigquery"],
    )
    
    logger.info("Submetendo o CustomTrainingJob para a fila do Vertex AI...")
    
    try:
        # A execução disso levanta uma VM, injeta o script, treina e desliga a VM.
        # sync=False não prende a tela do desenvolvedor enquanto treina.
        model = job.run(
            replica_count=1,
            machine_type="n1-standard-4",
            sync=False
        )
        logger.info(f"Treinamento iniciado! Acompanhe no console do Vertex AI.")
        return job
        
    except Exception as e:
        logger.error(f"Falha ao iniciar treinamento (verifique as permissões de acesso ao GCS): {e}")

if __name__ == "__main__":
    GCP_PROJECT_ID = "project-d28ce7a4-0717-428d-ae4"
    # O GCS bucket é necessário pelo Vertex para guardar os scripts temporários e logs de treino
    STAGING_BUCKET = f"gs://{GCP_PROJECT_ID}-vertex-staging"
    orquestrar_custom_training(GCP_PROJECT_ID, "us-central1", STAGING_BUCKET)
