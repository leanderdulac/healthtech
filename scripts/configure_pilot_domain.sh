#!/usr/bin/env bash
# Lê DOMAIN de um arquivo (padrão: Desktop) e prepara mapeamento Cloud Run + imprime DNS.
set -euo pipefail

CONFIG="${1:-$HOME/Desktop/NEXT2U_DOMINIO_PARA_CONFIGURAR.md}"
PROJECT="${PROJETO_GCP:-healthtech-gcp-2026}"
REGION="${REGIAO:-us-central1}"
SERVICE="${SERVICO_CLOUD_RUN:-next2u-web-staging}"

if [[ ! -f "$CONFIG" ]]; then
  echo "Arquivo não encontrado: $CONFIG" >&2
  exit 1
fi

# Extrai DOMAIN= e WWW= do bloco de config (ignora vazios / placeholders)
DOMAIN=$(grep -E '^DOMAIN=' "$CONFIG" | head -1 | cut -d= -f2- | tr -d '[:space:]')
WWW=$(grep -E '^WWW=' "$CONFIG" | head -1 | cut -d= -f2- | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
PROJECT=$(grep -E '^PROJETO_GCP=' "$CONFIG" | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)
REGION=$(grep -E '^REGIAO=' "$CONFIG" | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)
SERVICE=$(grep -E '^SERVICO_CLOUD_RUN=' "$CONFIG" | head -1 | cut -d= -f2- | tr -d '[:space:]' || true)
PROJECT=${PROJECT:-healthtech-gcp-2026}
REGION=${REGION:-us-central1}
SERVICE=${SERVICE:-next2u-web-staging}

if [[ -z "$DOMAIN" ]]; then
  echo "DOMAIN= ainda vazio em $CONFIG" >&2
  echo "Preencha o domínio comprado e rode de novo." >&2
  exit 2
fi

# Sanidade básica
if [[ "$DOMAIN" == http* || "$DOMAIN" == */* || "$DOMAIN" == *:* ]]; then
  echo "DOMAIN inválido (não use https://, porta ou path): $DOMAIN" >&2
  exit 3
fi

echo "Projeto=$PROJECT Região=$REGION Serviço=$SERVICE"
echo "Domínio apex=$DOMAIN  WWW=${WWW:-sim}"
gcloud config set project "$PROJECT" >/dev/null

echo ""
echo "==> Abra a verificação do domínio na conta Google (browser):"
echo "    gcloud domains verify $DOMAIN"
echo "    (ou https://search.google.com/search-console — propriedade do domínio)"
echo ""
read -r -p "Depois que o domínio estiver verificado nesta conta GCP, Enter para continuar (Ctrl+C cancela)... "

map_one() {
  local d="$1"
  echo "=== mapeando $d → $SERVICE ==="
  if gcloud beta run domain-mappings describe --domain="$d" --region="$REGION" --platform=managed >/dev/null 2>&1; then
    echo "já existe"
  else
    gcloud beta run domain-mappings create \
      --service="$SERVICE" \
      --domain="$d" \
      --region="$REGION" \
      --platform=managed
  fi
  echo "--- registros DNS para $d ---"
  gcloud beta run domain-mappings describe --domain="$d" --region="$REGION" --platform=managed \
    --format='table(status.resourceRecords.type,status.resourceRecords.name,status.resourceRecords.rrdata)'
  echo "--- condições ---"
  gcloud beta run domain-mappings describe --domain="$d" --region="$REGION" --platform=managed \
    --format='table(status.conditions.type,status.conditions.status,status.conditions.message)'
}

map_one "$DOMAIN"
if [[ "${WWW:-sim}" == "sim" || "${WWW}" == "yes" || "${WWW}" == "s" ]]; then
  map_one "www.$DOMAIN"
fi

OUT="$HOME/Desktop/NEXT2U_DNS_${DOMAIN//./_}_$(date +%Y-%m-%d).txt"
{
  echo "Next2U DNS — $DOMAIN — gerado $(date '+%Y-%m-%d %H:%M %Z')"
  echo "Serviço: $SERVICE | Projeto: $PROJECT | Região: $REGION"
  echo ""
  gcloud beta run domain-mappings describe --domain="$DOMAIN" --region="$REGION" --platform=managed \
    --format='yaml(status.resourceRecords,status.conditions)'
  if [[ "${WWW:-sim}" == "sim" || "${WWW}" == "yes" || "${WWW}" == "s" ]]; then
    echo ""
    echo "### www.$DOMAIN"
    gcloud beta run domain-mappings describe --domain="www.$DOMAIN" --region="$REGION" --platform=managed \
      --format='yaml(status.resourceRecords,status.conditions)'
  fi
} > "$OUT"
echo ""
echo "Registros salvos em: $OUT"
echo "Cole no painel DNS; quando propagar, atualizamos Auth0 APP_BASE_URL + callbacks."
