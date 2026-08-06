#!/bin/bash
# deploy_to_gcp.sh — Deploy automatizado no GCP / Cloud Run (com hardening)
# Suporta APP_MODE=full (monólito) ou APP_MODE=secure (API enxuta)
set -euo pipefail

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
DEFAULT_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"$DEFAULT_PROJECT"}
GCP_PROJECT_ID=${GCP_PROJECT_ID:-"healthtech-gcp-2026"}
GCP_REGION=${GCP_REGION:-"us-central1"}
# full | secure
APP_MODE=${APP_MODE:-"full"}
if [[ "$APP_MODE" != "full" && "$APP_MODE" != "secure" ]]; then
  echo "ERRO: APP_MODE deve ser 'full' ou 'secure' (recebido: $APP_MODE)"
  exit 1
fi

if [[ "$APP_MODE" == "secure" ]]; then
  SERVICE_NAME=${SERVICE_NAME:-"healthtech-secure-api"}
  MEMORY=${MEMORY:-"1Gi"}
  CPU=${CPU:-"1"}
  SOURCE_DIR=${SOURCE_DIR:-"./saude_responsiva_secure"}
else
  SERVICE_NAME=${SERVICE_NAME:-"healthtech-responsive"}
  MEMORY=${MEMORY:-"4Gi"}
  CPU=${CPU:-"1"}
  SOURCE_DIR=${SOURCE_DIR:-"."}
fi

ALLOW_UNAUTHENTICATED=${ALLOW_UNAUTHENTICATED:-"true"}
API_KEY=${API_KEY:-"ht_admin_live_key_2026_safe_token_32c"}
INGEST_API_KEY=${INGEST_API_KEY:-"ht_ingest_live_key_2026_safe_token_32c"}
READ_API_KEY=${READ_API_KEY:-"ht_read_live_key_2026_safe_token_32c"}
SECRET_SALT=${SECRET_SALT:-$(openssl rand -hex 32 2>/dev/null || echo "healthtech_strong_salt_$(date +%s)")}
CORS_ORIGINS=${CORS_ORIGINS:-"https://healthtech-responsive-5794833455.us-central1.run.app,http://localhost:8000"}

if [[ -z "$GCP_PROJECT_ID" || "$GCP_PROJECT_ID" == "project-placeholder" ]]; then
  echo "ERRO: defina GCP_PROJECT_ID com o ID real do projeto."
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
echo "APP_MODE:       $APP_MODE"
echo "Source:         $SOURCE_DIR"
echo "Memória/CPU:    $MEMORY / $CPU"
echo "Auth público:   $ALLOW_UNAUTHENTICATED"
echo "========================================================================"

echo "Habilitando APIs do GCP..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    aiplatform.googleapis.com \
    bigquery.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com --project="$GCP_PROJECT_ID"

if [[ "$APP_MODE" == "full" ]]; then
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
dl = DataLakeManager(lake_path='data/lake')
slm = SLMSearchEngine()
try:
    slm.index_datalake(dl)
except Exception as e:
    print('Indexação pulada/falhou (não bloqueante):', e)
" || true
else
  echo "Modo secure: pulando BigQuery/GCS/Chroma pré-deploy (API enxuta)."
fi

AUTH_FLAG="--allow-unauthenticated"
AUTH_DISABLED_VAL="false"

ENV_VARS="^@^GCP_PROJECT_ID=${GCP_PROJECT_ID}@GCS_STAGING_BUCKET=${STAGING_BUCKET}@GCP_LOCATION=${GCP_REGION}@ENVIRONMENT=production@APP_MODE=${APP_MODE}@AUTH_DISABLED=${AUTH_DISABLED_VAL}@API_KEY=${API_KEY}@ADMIN_API_KEY=${API_KEY}@INGEST_API_KEY=${INGEST_API_KEY}@READ_API_KEY=${READ_API_KEY}@SECRET_SALT=${SECRET_SALT}@CORS_ORIGINS=${CORS_ORIGINS}"

echo "Compilando imagem Docker e enviando para o Google Cloud Run..."
if [[ "$APP_MODE" == "secure" ]]; then
  # Imagem enxuta a partir de saude_responsiva_secure/Dockerfile
  gcloud run deploy "$SERVICE_NAME" \
      --quiet \
      --source "$SOURCE_DIR" \
      --region "$GCP_REGION" \
      --platform managed \
      $AUTH_FLAG \
      --set-env-vars "$ENV_VARS" \
      --port 8080 \
      --memory "$MEMORY" \
      --cpu "$CPU" \
      --project="$GCP_PROJECT_ID"
else
  # Monólito full a partir do Dockerfile raiz (APP_MODE=full)
  gcloud run deploy "$SERVICE_NAME" \
      --quiet \
      --source "$SOURCE_DIR" \
      --region "$GCP_REGION" \
      --platform managed \
      $AUTH_FLAG \
      --set-env-vars "$ENV_VARS" \
      --port 8080 \
      --memory "$MEMORY" \
      --cpu "$CPU" \
      --project="$GCP_PROJECT_ID"
fi

echo "========================================================================"
echo " DEPLOY CONCLUÍDO "
echo "========================================================================"
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --platform managed \
  --region "$GCP_REGION" \
  --format 'value(status.url)' \
  --project="$GCP_PROJECT_ID")
echo "URL: $SERVICE_URL"
echo "Modo: $APP_MODE"
echo "Health: curl -s ${SERVICE_URL}/api/health"
echo "Lembrete: envie header X-API-Key nas requisições REST."
echo ""
echo "Exemplos:"
echo "  APP_MODE=full   ./deploy_to_gcp.sh   # monólito + dashboard"
echo "  APP_MODE=secure ./deploy_to_gcp.sh   # API secure enxuta"
echo "========================================================================"
