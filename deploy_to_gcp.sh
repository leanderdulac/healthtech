#!/bin/bash
# deploy_to_gcp.sh — Deploy automatizado no GCP / Cloud Run (com hardening)
set -euo pipefail

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
GCP_PROJECT_ID=${GCP_PROJECT_ID:-""}
GCP_REGION=${GCP_REGION:-"us-central1"}
SERVICE_NAME=${SERVICE_NAME:-"healthtech-responsive"}
ALLOW_UNAUTHENTICATED=${ALLOW_UNAUTHENTICATED:-"false"}
API_KEY=${API_KEY:-""}
SECRET_SALT=${SECRET_SALT:-""}
CORS_ORIGINS=${CORS_ORIGINS:-""}

if [[ -z "$GCP_PROJECT_ID" || "$GCP_PROJECT_ID" == "project-placeholder" ]]; then
  echo "ERRO: defina GCP_PROJECT_ID com o ID real do projeto."
  exit 1
fi

if [[ -z "$API_KEY" ]]; then
  echo "ERRO: defina API_KEY (ex.: export API_KEY=\$(openssl rand -hex 32))."
  exit 1
fi

if [[ -z "$SECRET_SALT" || "$SECRET_SALT" == "default-salt" || "$SECRET_SALT" == "altere-este-salt-em-producao" ]]; then
  echo "ERRO: defina SECRET_SALT forte (ex.: export SECRET_SALT=\$(openssl rand -hex 32))."
  exit 1
fi

STAGING_BUCKET="gs://${GCP_PROJECT_ID}-vertex-staging"

echo "========================================================================"
echo " INICIANDO DEPLOY NA NUVEM (GCP & VERTEX AI) "
echo "========================================================================"
echo "Projeto GCP ID: $GCP_PROJECT_ID"
echo "Região:         $GCP_REGION"
echo "Bucket GCS:     $STAGING_BUCKET"
echo "Serviço Cloud Run: $SERVICE_NAME"
echo "Auth público:   $ALLOW_UNAUTHENTICATED"
echo "========================================================================"

echo "Habilitando APIs do GCP..."
gcloud services enable \
    run.googleapis.com \
    build.googleapis.com \
    aiplatform.googleapis.com \
    bigquery.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com --project="$GCP_PROJECT_ID"

echo "Garantindo Bucket GCS para Staging e Modelos..."
if ! gsutil ls -b "$STAGING_BUCKET" >/dev/null 2>&1; then
    gsutil mb -l "$GCP_REGION" "$STAGING_BUCKET"
    echo "Bucket $STAGING_BUCKET criado com sucesso."
else
    echo "Bucket $STAGING_BUCKET já existe."
fi

echo "Provisionando infraestrutura do BigQuery Data Lake..."
export GCP_PROJECT_ID="$GCP_PROJECT_ID"
python src/data_warehouse/bigquery_setup.py

echo "Ingerindo base de conhecimento USP inicial para o GCS (se CSV existir)..."
export GCS_STAGING_BUCKET="$STAGING_BUCKET"
if [[ -f teses_usp_saude.csv ]]; then
  python src/data_warehouse/datalake_manager.py
else
  echo "Aviso: teses_usp_saude.csv não encontrado — pulando ingestão inicial."
fi

echo "Indexando corpus no ChromaDB (opcional)..."
python -c "
from src.ml_pipeline.slm_search_engine import SLMSearchEngine
from src.data_warehouse.datalake_manager import DataLakeManager
dl = DataLakeManager(lake_path='$STAGING_BUCKET')
slm = SLMSearchEngine()
try:
    slm.index_datalake(dl)
except Exception as e:
    print('Indexação pulada/falhou (não bloqueante):', e)
" || true

AUTH_FLAG="--no-allow-unauthenticated"
if [[ "$ALLOW_UNAUTHENTICATED" == "true" ]]; then
  echo "AVISO: deploy público (--allow-unauthenticated). Prefira Identity / API key."
  AUTH_FLAG="--allow-unauthenticated"
fi

ENV_VARS="GCP_PROJECT_ID=${GCP_PROJECT_ID},GCS_STAGING_BUCKET=${STAGING_BUCKET},GCP_LOCATION=${GCP_REGION},ENVIRONMENT=production,AUTH_DISABLED=false,API_KEY=${API_KEY},SECRET_SALT=${SECRET_SALT}"
if [[ -n "$CORS_ORIGINS" ]]; then
  ENV_VARS="${ENV_VARS},CORS_ORIGINS=${CORS_ORIGINS}"
fi

echo "Compilando imagem Docker e enviando para o Google Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$GCP_REGION" \
    --platform managed \
    $AUTH_FLAG \
    --set-env-vars "$ENV_VARS" \
    --port 8080 \
    --project="$GCP_PROJECT_ID"

echo "========================================================================"
echo " DEPLOY CONCLUÍDO "
echo "========================================================================"
gcloud run services describe "$SERVICE_NAME" \
  --platform managed \
  --region "$GCP_REGION" \
  --format 'value(status.url)' \
  --project="$GCP_PROJECT_ID"
echo "Lembrete: envie header X-API-Key nas requisições REST."
echo "========================================================================"
