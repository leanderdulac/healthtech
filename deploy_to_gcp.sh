#!/bin/bash
# deploy_to_gcp.sh — Script para deploy automatizado do projeto no GCP e Vertex AI

set -e

# ==============================================================================
# CONFIGURAÇÕES DO USUÁRIO
# Substitua pelos dados do seu ambiente GCP
# ==============================================================================
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"project-placeholder"}
GCP_REGION=${GCP_REGION:-"us-central1"}
STAGING_BUCKET="gs://${GCP_PROJECT_ID}-vertex-staging"
SERVICE_NAME="healthtech-responsive"

echo "========================================================================"
echo " INICIANDO DEPLOY NA NUVEM (GCP & VERTEX AI) "
echo "========================================================================"
echo "Projeto GCP ID: $GCP_PROJECT_ID"
echo "Região:         $GCP_REGION"
echo "Bucket GCS:     $STAGING_BUCKET"
echo "Serviço Cloud Run: $SERVICE_NAME"
echo "========================================================================"

# 1. Autenticar no GCP (caso não esteja logado)
# gcloud auth login

# 2. Habilitar APIs necessárias no projeto
echo "Habilitando APIs do GCP..."
gcloud services enable \
    run.googleapis.com \
    build.googleapis.com \
    aiplatform.googleapis.com \
    bigquery.googleapis.com \
    storage.googleapis.com --project="$GCP_PROJECT_ID"

# 3. Criar Bucket do GCS se não existir
echo "Garantindo Bucket GCS para Staging e Modelos..."
if ! gsutil ls -b "$STAGING_BUCKET" >/dev/null 2>&1; then
    gsutil mb -l "$GCP_REGION" "$STAGING_BUCKET"
    echo "Bucket $STAGING_BUCKET criado com sucesso."
else
    echo "Bucket $STAGING_BUCKET já existe."
fi

# 4. Provisionar Tabelas no BigQuery
echo "Provisionando infraestrutura do BigQuery Data Lake..."
export GCP_PROJECT_ID="$GCP_PROJECT_ID"
python src/data_warehouse/bigquery_setup.py

# 5. Ingestão de Dados Iniciais no Data Lake GCS
echo "Ingerindo base de conhecimento USP inicial para o GCS..."
export GCS_STAGING_BUCKET="$STAGING_BUCKET"
python src/data_warehouse/datalake_manager.py

# 6. Reindexar ChromaDB e enviar backup inicial para o GCS
echo "Indexando corpus no banco de vetores ChromaDB e sincronizando..."
python -c "from src.ml_pipeline.slm_search_engine import SLMSearchEngine; from src.data_warehouse.datalake_manager import DataLakeManager; dl = DataLakeManager(lake_path='$STAGING_BUCKET'); slm = SLMSearchEngine(); slm.index_datalake(dl)"

# 7. Submeter Imagem do Contêiner para o Cloud Build e Deploy no Cloud Run
echo "Compilando imagem Docker e enviando para o Google Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$GCP_REGION" \
    --platform managed \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT_ID="$GCP_PROJECT_ID",GCS_STAGING_BUCKET="$STAGING_BUCKET",GCP_LOCATION="$GCP_REGION" \
    --port 8080 \
    --project="$GCP_PROJECT_ID"

echo "========================================================================"
echo " DEPLOY CONCLUÍDO COM SUCESSO! "
echo "========================================================================"
echo "Sua plataforma Saúde Responsiva já está ativa na nuvem!"
echo "Acesse a interface gráfica em:"
gcloud run services describe "$SERVICE_NAME" --platform managed --region "$GCP_REGION" --format 'value(status.url)' --project="$GCP_PROJECT_ID"
echo "========================================================================"
