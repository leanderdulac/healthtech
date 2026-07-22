# Estágio de build para dependências
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt* ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Estágio final de execução
FROM python:3.11-slim AS runner

WORKDIR /app

# Usuário não-root
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV ENVIRONMENT=production
ENV AUTH_DISABLED=false

COPY --chown=appuser:appuser src/ /app/src/
COPY --chown=appuser:appuser dashboard/ /app/dashboard/
COPY --chown=appuser:appuser data/ /app/data/
COPY --chown=appuser:appuser requirements.txt /app/

# CSV de literatura é opcional (scraper gera em runtime)
RUN mkdir -p /app/data/chroma_db /app/data/lake && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')" || exit 1

# Uvicorn explícito (mais estável que python -m script em containers)
CMD ["python", "-m", "uvicorn", "src.api_server:app", "--host", "0.0.0.0", "--port", "8080"]
