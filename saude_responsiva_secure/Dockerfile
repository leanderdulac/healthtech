# Saúde Responsiva Secure API — imagem enxuta non-root
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim AS runner

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV ENVIRONMENT=production
ENV AUTH_DISABLED=false
ENV APP_MODE=secure
ENV PYTHONPATH=/app

COPY --chown=appuser:appuser app/ /app/app/
COPY --chown=appuser:appuser migrations/ /app/migrations/
COPY --chown=appuser:appuser requirements.txt /app/
# Subset gerado por scripts/sync_secure_vendor.py (não o monorepo inteiro):
#   clinical_intelligence — matriz de alertas no ingest
#   ops — timestamps, patients_routes, operational_patients, live_devices, device_registry
# Fonte local: _vendor_src/ (evita sombrear monorepo `src/` no PYTHONPATH do host)
COPY --chown=appuser:appuser _vendor_src/ /app/src/
# Catálogo Next2U (estrelas/nomes). Sem este JSON as 158 regras caem para 1★/leve.
COPY --chown=appuser:appuser data/ /app/data/

USER appuser

# Falha o build se o vendor não incluir o src.ops usado em ingest + /patients.
RUN python -c "from src.ops.timestamps import stamp_ingest; from src.ops.patients_routes import router; assert stamp_ingest and router.routes"

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
