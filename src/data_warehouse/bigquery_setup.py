import logging
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def provision_bigquery_datalake(project_id: str, location: str = "US"):
    """
    Cria a infraestrutura do Data Lakehouse no Google BigQuery.
    Provisiona um Dataset central e duas tabelas com schemas estritos:
    1. fhirs_patients (Perfis anonimizados)
    2. wearable_biometrics (Dados de séries temporais)
    """
    client = bigquery.Client(project=project_id, location=location)
    dataset_id = f"{project_id}.healthtech_datalake"

    logger.info(f"Provisionando Datalake no projeto: {project_id}")

    # 1. Criar Dataset
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = location
    dataset.description = "Datalake central para dados estruturados de saúde (FHIR) e IoT"
    
    try:
        dataset = client.create_dataset(dataset, exists_ok=True)
        logger.info(f"Dataset '{dataset.dataset_id}' garantido com sucesso.")
    except GoogleAPIError as e:
        logger.error(f"Erro ao criar dataset: {e}")
        return

    # 2. Schema da Tabela de Pacientes (Padrão FHIR simplificado)
    schema_patients = [
        bigquery.SchemaField("patient_id", "STRING", mode="REQUIRED", description="ID Anonimizado (UUID)"),
        bigquery.SchemaField("gender", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("birth_year", "DATE", mode="NULLABLE", description="Apenas ano de nascimento retido"),
        bigquery.SchemaField("location_city", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("location_country", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED")
    ]
    
    table_patients_id = f"{dataset_id}.fhir_patients"
    table_patients = bigquery.Table(table_patients_id, schema=schema_patients)
    
    # 3. Schema da Tabela de Biometria IoT (Wearables)
    schema_biometrics = [
        bigquery.SchemaField("patient_id", "STRING", mode="REQUIRED", description="FK para fhir_patients"),
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("heart_rate_bpm", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("sensors_used", "STRING", mode="REPEATED", description="Sensores envolvidos na leitura"),
        bigquery.SchemaField("is_anomaly", "BOOLEAN", mode="NULLABLE", description="Flag populada via inferência Batch/Online")
    ]
    
    table_biometrics_id = f"{dataset_id}.wearable_biometrics"
    # Otimização: Particionando por data de ingestão para consultas baratas de longo prazo
    table_biometrics = bigquery.Table(table_biometrics_id, schema=schema_biometrics)
    table_biometrics.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="timestamp" 
    )

    # Executar a criação das tabelas
    try:
        client.create_table(table_patients, exists_ok=True)
        logger.info(f"Tabela 'fhir_patients' criada com schema FHIR.")
        
        client.create_table(table_biometrics, exists_ok=True)
        logger.info(f"Tabela particionada 'wearable_biometrics' criada.")
        
    except GoogleAPIError as e:
        logger.error(f"Erro na criação das tabelas: {e}")

if __name__ == "__main__":
    # Substitua pelo seu ID
    GCP_PROJECT_ID = "project-d28ce7a4-0717-428d-ae4" 
    provision_bigquery_datalake(project_id=GCP_PROJECT_ID)
