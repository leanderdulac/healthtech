import logging
from google.cloud import aiplatform

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def deploy_modelo_endpoint(project_id: str, location: str, model_id: str):
    """
    Esta função pega um Modelo já treinado no Model Registry 
    e hospeda ele em um Endpoint de API persistente (Tempo Real).
    """
    aiplatform.init(project=project_id, location=location)
    
    try:
        logger.info(f"Buscando modelo '{model_id}' no Model Registry...")
        model = aiplatform.Model(model_name=model_id)
        
        logger.info("Criando Endpoint e alocando recursos computacionais (Pode levar de 5 a 15 minutos)...")
        # Criação do endpoint e roteamento de tráfego
        endpoint = model.deploy(
            machine_type="n1-standard-2", # VM que ficará ligada 24/7 respondendo as APIs
            min_replica_count=1,
            max_replica_count=3,          # Auto-scaling ativado para picos de leituras cardíacas
            traffic_split={"0": 100},     # 100% do tráfego para essa versão do modelo
            sync=False                    # Operação Assíncrona
        )
        
        logger.info(f"Processo de Deploy iniciado. Endpoint Resource Name: {endpoint.resource_name}")
        return endpoint
        
    except Exception as e:
        logger.error(f"Falha ao provisionar Endpoint de Deploy: {e}")

if __name__ == "__main__":
    GCP_PROJECT_ID = "project-d28ce7a4-0717-428d-ae4"
    # Você precisaria substituir isso pelo ID real gerado após o training.py finalizar
    MODELO_TREINADO_ID = "1234567890" 
    deploy_modelo_endpoint(GCP_PROJECT_ID, "us-central1", MODELO_TREINADO_ID)
