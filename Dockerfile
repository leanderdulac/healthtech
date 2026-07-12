# Estágio de build para dependências
FROM python:3.11-slim as builder

WORKDIR /app

# Instalar pacotes de sistema necessários para compilar bibliotecas científicas (scipy, numpy, pywt etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Instalar dependências em um diretório isolado
RUN pip install --no-cache-dir --user -r requirements.txt

# Estágio final de execução
FROM python:3.11-slim as runner

WORKDIR /app

# Copiar bibliotecas compiladas do estágio builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copiar os diretórios da aplicação
COPY src/ /app/src/
COPY dashboard/ /app/dashboard/
COPY data/ /app/data/
# Copiar literatura padrão
COPY teses_usp_saude.csv /app/

# Configurar variáveis de ambiente padrão
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "src/api_server.py"]
