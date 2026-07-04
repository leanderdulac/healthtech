import logging
import os

from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

FHIR_RESOURCE_SCHEMA = [
    bigquery.SchemaField(
        "resource_type", "STRING", mode="REQUIRED",
        description="Tipo FHIR R4: Patient, Observation, Device, Flag",
    ),
    bigquery.SchemaField(
        "resource_id", "STRING", mode="REQUIRED",
        description="ID do recurso FHIR",
    ),
    bigquery.SchemaField(
        "patient_id", "STRING", mode="NULLABLE",
        description="Referencia Patient/ para recursos vinculados",
    ),
    bigquery.SchemaField(
        "effective_datetime", "TIMESTAMP", mode="NULLABLE",
        description="Data efetiva (Observation) ou periodo",
    ),
    bigquery.SchemaField(
        "fhir_version", "STRING", mode="REQUIRED",
        description="Versao FHIR (R4)",
    ),
    bigquery.SchemaField(
        "last_updated", "TIMESTAMP", mode="REQUIRED",
    ),
    bigquery.SchemaField(
        "resource_json", "JSON", mode="REQUIRED",
        description="Recurso FHIR completo em JSON (padrao HL7)",
    ),
]


def provision_bigquery_datalake(project_id: str, location: str = "US"):
    """
    Cria infraestrutura do Data Lakehouse no BigQuery com armazenamento FHIR nativo.

    Tabelas:
      1. fhir_resources — recursos FHIR R4 (Patient, Device, Observation, Flag)
      2. fhir_observations — view-friendly para sinais vitais (derivada do JSON)
      3. wearable_biometrics — compatibilidade retroativa (legado)
    """
    client = bigquery.Client(project=project_id, location=location)
    dataset_id = f"{project_id}.healthtech_datalake"

    logger.info("Provisionando Datalake FHIR no projeto: %s", project_id)

    dataset = bigquery.Dataset(dataset_id)
    dataset.location = location
    dataset.description = (
        "Datalake FHIR R4 / HL7 para dados de saude e telemetria de wearables"
    )

    try:
        dataset = client.create_dataset(dataset, exists_ok=True)
        logger.info("Dataset '%s' garantido.", dataset.dataset_id)
    except GoogleAPIError as e:
        logger.error("Erro ao criar dataset: %s", e)
        return

    # Tabela principal FHIR (armazenamento canonico HL7)
    table_fhir_id = f"{dataset_id}.fhir_resources"
    table_fhir = bigquery.Table(table_fhir_id, schema=FHIR_RESOURCE_SCHEMA)
    table_fhir.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="last_updated",
    )
    table_fhir.clustering_fields = ["resource_type", "patient_id"]

    # Tabela legada de biometria (compatibilidade com pipelines existentes)
    schema_biometrics = [
        bigquery.SchemaField("patient_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("heart_rate_bpm", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("loinc_code", "STRING", mode="NULLABLE", description="8867-4"),
        bigquery.SchemaField("sensors_used", "STRING", mode="REPEATED"),
        bigquery.SchemaField("is_anomaly", "BOOLEAN", mode="NULLABLE"),
        bigquery.SchemaField("fhir_observation_id", "STRING", mode="NULLABLE"),
    ]
    table_biometrics_id = f"{dataset_id}.wearable_biometrics"
    table_biometrics = bigquery.Table(table_biometrics_id, schema=schema_biometrics)
    table_biometrics.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="timestamp",
    )
    table_biometrics.clustering_fields = ["patient_id"]

    try:
        client.create_table(table_fhir, exists_ok=True)
        logger.info("Tabela 'fhir_resources' criada (FHIR R4 / HL7).")

        client.create_table(table_biometrics, exists_ok=True)
        logger.info("Tabela 'wearable_biometrics' criada (compatibilidade).")

    except GoogleAPIError as e:
        logger.error("Erro na criacao das tabelas: %s", e)


if __name__ == "__main__":
    GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "project-placeholder")
    provision_bigquery_datalake(project_id=GCP_PROJECT_ID)