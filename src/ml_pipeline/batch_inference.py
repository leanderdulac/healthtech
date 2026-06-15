import logging
from google.cloud import aiplatform

logger = logging.getLogger(__name__)

def orquestrar_batch_vertex_ai(project: str, location: str, model_name: str, gcs_input_uri: str, gcs_output_uri: str, machine_type: str = "n1-standard-4") -> dict:
    """
    Orquestra um Job de Inferência em Lote no Vertex AI.
    Ao invés de processar os dados na máquina, delega o processamento pesado 
    para o cluster distribuído do GCP, lendo os dados do BigQuery ou GCS.
    """
    logger.info(f"Preparando Batch Prediction Job no Vertex AI para o modelo {model_name}...")
    
    try:
        aiplatform.init(project=project, location=location)
        
        # Referência ao modelo previamente treinado e registrado no Vertex AI Registry
        model = aiplatform.Model(model_name=model_name)
        
        # Dispara o job assíncrono na nuvem
        # Normalmente isso seria agendado (ex: via Cloud Composer / Airflow)
        batch_predict_job = model.batch_predict(
            job_display_name="deteccao_risco_saude_populacional",
            gcs_source=gcs_input_uri,
            gcs_destination_prefix=gcs_output_uri,
            instances_format="jsonl",
            predictions_format="jsonl",
            machine_type=machine_type, # Maquina parruda na nuvem configurável
            starting_replica_count=1,
            max_replica_count=5, # Auto-scaling ativado
            sync=False # Retorna imediatamente sem bloquear o fluxo principal
        )
        
        logger.info(f"Job Submetido com sucesso! ID: {batch_predict_job.resource_name}")
        
        return {
            "status": "JOB_SUBMITTED",
            "job_id": batch_predict_job.resource_name,
            "job_url": f"https://console.cloud.google.com/vertex-ai/locations/{location}/batches/{batch_predict_job.name}?project={project}"
        }
        
    except Exception as e:
        logger.warning(f"Não foi possível orquestrar o Batch no GCP ({e}).")
        return {
            "status": "SIMULATION_MODE",
            "mensagem": "Nuvem não configurada. Simulando requisição enviada ao Vertex Batch.",
            "gcs_output": f"{gcs_output_uri}/simulacao_resultados/"
        }
