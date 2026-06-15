# HealthTech GCP Pipeline - Documentação Completa

## 🏥 Visão Geral do Sistema

Sistema completo de dados e Machine Learning para HealthTech no Google Cloud Platform, seguindo as melhores práticas do setor de saúde (HIPAA, FHIR) e arquitetura moderna de dados.

---

## 📐 Arquitetura do Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    HEALTHTECH GCP PIPELINE                       │
└─────────────────────────────────────────────────────────────────┘

1. INGESTÃO E RECONCILIAÇÃO (Streaming/Eventos)
   ├── DataGenerator: Gera dados de sensores biométricos
   ├── DataReconciliation: Agrega em janelas de tempo
   └── Validação de qualidade dos dados
   
2. SEGURANÇA E PRIVACIDADE (FHIR + HIPAA)
   ├── FHIRAnonymizer: Remove PHI (Protected Health Information)
   ├── Hash SHA-256 determinístico
   └── Generalização de dados sensíveis
   
3. ML - INFERÊNCIA ONLINE (Vertex AI Endpoint)
   ├── VertexAIOnlineInference: Detecção de arritmia em tempo real
   ├── API REST para streaming de dados
   └── Baixa latência (< 100ms)
   
4. ML - INFERÊNCIA BATCH (Vertex AI Batch Prediction)
   ├── VertexAIBatchPrediction: Análise populacional
   ├── Processamento de arquivos .jsonl do GCS
   └── Consolidação no BigQuery
```

---

## 🗂️ Estrutura de Diretórios

```
healthcare_gcp_pipeline/
├── main_pipeline.py          # Pipeline principal
├── src/
│   ├── ingestion/            # Módulos de ingestão
│   ├── security/             # Anonimização e segurança
│   ├── ml_inference/         # Inferência online e batch
│   └── utils/                # Utilitários
├── data/
│   ├── raw/                  # Dados brutos
│   ├── processed/            # Dados processados
│   └── lakehouse/            # Data Lake/Lakehouse
└── tests/                    # Testes unitários
```

---

## 🔧 Componentes Principais

### 1. GCPConfig (Configuração Centralizada)

```python
@dataclass
class GCPConfig:
    project_id: str
    region: str
    bucket_name: str
    dataset_id: str
    endpoint_id: str
    model_name: str
    
    @classmethod
    def from_env(cls) -> 'GCPConfig'
```

**Variáveis de Ambiente:**
- `GCP_PROJECT_ID`: ID do projeto GCP
- `GCP_REGION`: Região dos serviços (ex: us-central1)
- `GCS_BUCKET`: Nome do bucket no GCS
- `BQ_DATASET`: Dataset do BigQuery
- `VERTEX_ENDPOINT_ID`: ID do endpoint Vertex AI
- `VERTEX_MODEL_NAME`: Nome do modelo de ML

---

### 2. DataGenerator (Geração de Dados)

Gera dados simulados de sensores biométricos:
- Heart rate (BPM)
- Blood pressure (sistólica/diastólica)
- Oxygen saturation (%)
- Temperature (Celsius)
- Sensor quality score

**Exemplo de uso:**
```python
generator = DataGenerator(seed=42)
readings = generator.generate_patient_vitals(
    patient_id="PATIENT_12345",
    num_readings=10
)
```

---

### 3. DataReconciliation (Reconciliação em Janelas)

Reconcilia múltiplas leituras em janelas de tempo:
- Filtra dados por qualidade (quality_score > 0.7)
- Agrega métricas (média, contagem)
- Identifica sensores únicos
- Define flag de qualidade da janela

**Retorna:**
```python
{
    'window_start': '2024-01-15T10:00:00',
    'window_end': '2024-01-15T10:01:00',
    'num_readings': 6,
    'avg_heart_rate': 85.17,
    'avg_oxygen_saturation': 97.5,
    'sensors_count': 3,
    'quality_flag': 'HIGH'
}
```

---

### 4. FHIRAnonymizer (Anonimização)

Segue padrões **FHIR** e **HIPAA** para proteção de dados:

**Campos PHI anonimizados:**
- `patient_id` → `patient_id_anon` (hash SHA-256)
- `name` → `name_anon`
- `email` → `email_anon`
- `phone` → `phone_anon`
- `address` → `address_anon`
- `ssn` → `ssn_anon`
- `birth_date` → `birth_year` (generalização)

**Características:**
- ✅ Hash determinístico (mesmo input = mesmo output)
- ✅ Salt configurável para segurança
- ✅ Prefixo "ANON-" para identificação
- ✅ Cópia dos dados (não modifica original)

---

### 5. VertexAIOnlineInference (Inferência Online)

Detecta arritmias em tempo real via Vertex AI Endpoint:

**Modo Produção:**
- Conecta ao Vertex AI Endpoint real
- Envia sinais vitais como instâncias
- Retorna predição com confiança

**Modo Simulação:**
- Lógica baseada em regras (HR > 100 ou < 50)
- Ideal para desenvolvimento e testes
- Sem necessidade de credenciais GCP

**Exemplo de resposta:**
```python
{
    'prediction': 0,
    'class_label': 'NORMAL',
    'probability': 0.15,
    'confidence': 0.92,
    'model_version': 'simulated-v1.0',
    'inference_type': 'online_simulation'
}
```

---

### 6. VertexAIBatchPrediction (Inferência em Lote)

Processa grandes volumes para análise populacional:

**Funcionalidades:**
1. **submit_batch_job()**: Submete job no Vertex AI
   - Lê arquivos .jsonl do GCS
   - Processa em lote
   - Salva resultados no GCS

2. **consolidate_to_bigquery()**: Consolida resultados
   - Carrega dados do GCS para BigQuery
   - Formato NEWLINE_DELIMITED_JSON
   - Append em tabela existente

**Fluxo:**
```
GCS (input.jsonl) → Vertex AI Batch → GCS (output/) → BigQuery
```

---

## 🚀 Execução do Pipeline

### Modo Simulação (Desenvolvimento)

```bash
python main_pipeline.py
```

**Saída esperada:**
```
🔧 MODO SIMULAÇÃO ATIVADO - Sem credenciais GCP reais
📥 Etapa 1: Ingestão de dados biométricos
   ✅ 6 leituras geradas
🔄 Etapa 2: Reconciliação de dados
   ✅ Dados reconciliados: success
🔒 Etapa 3: Anonimização de dados sensíveis
   ✅ Paciente anonimizado: ANON-81161ac7433cfa13
🤖 Etapa 4: Inferência online para detecção de arritmia
   ✅ Predição: NORMAL (confiança: 0.92)
📦 Etapa 5: Predição em lote para análise populacional
   ✅ Job batch: COMPLETED_SIMULATED
📊 Etapa 6: Consolidação no BigQuery
   ✅ BigQuery: CONSOLIDATED_SIMULATED
🎉 Pipeline concluído com sucesso!
```

### Modo Produção

```bash
export GCP_PROJECT_ID="my-healthtech-project"
export GCP_REGION="us-central1"
export GCS_BUCKET="my-production-bucket"
export BQ_DATASET="patient_analytics"
export VERTEX_ENDPOINT_ID="123456789"
export VERTEX_MODEL_NAME="arrhythmia-detector"

python main_pipeline.py
```

---

## 🔒 Conformidade e Segurança

### HIPAA Compliance
- ✅ Remoção de 18 identificadores diretos
- ✅ Anonimização rastreável (hash com salt)
- ✅ Generalização de datas (apenas ano)
- ✅ Logs sem dados sensíveis

### FHIR Standard
- ✅ Estrutura compatível com FHIR Resources
- ✅ Campos padronizados para interoperabilidade
- ✅ Metadados de qualidade incluídos

---

## 📊 Monitoramento e Logging

**Logs estruturados incluem:**
- Timestamp ISO 8601
- Nível de severidade (INFO, WARNING, ERROR)
- Nome do componente
- Mensagem descritiva com emojis para fácil identificação

**Exemplo:**
```
2024-01-15 10:30:45,123 - __main__ - INFO - 🔒 Etapa 3: Anonimização de dados sensíveis
```

---

## 🧪 Próximos Passos Sugeridos

### 1. Testes Unitários
```python
# tests/test_anonymization.py
def test_anonymize_patient_removes_phi():
    anonymizer = FHIRAnonymizer()
    # ... testes
```

### 2. CI/CD Pipeline
- GitHub Actions para validação automática
- Deploy automático em staging/production
- Testes de integração com GCP emulado (LocalStack)

### 3. Containerização
```dockerfile
FROM python:3.10-slim
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . /app
CMD ["python", "main_pipeline.py"]
```

### 4. Orquestração com Cloud Composer (Airflow)
```python
# DAG para agendamento diário
with DAG('healthtech-pipeline', schedule_interval='@daily') as dag:
    ingestion_task = PythonOperator(task_id='ingest', ...)
    reconciliation_task = PythonOperator(task_id='reconcile', ...)
    # ...
```

### 5. Monitoramento com Cloud Monitoring
- Métricas customizadas de latência
- Alertas para falhas no pipeline
- Dashboards no Looker Studio

---

## 📚 Referências

- [Google Cloud Healthcare API](https://cloud.google.com/healthcare-api)
- [FHIR Standard](https://www.hl7.org/fhir/)
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html)
- [Vertex AI Documentation](https://cloud.google.com/vertex-ai/docs)
- [BigQuery Best Practices](https://cloud.google.com/bigquery/docs/best-practices-performance-overview)

---

## 👨‍💻 Autor

Engenheiro de Dados e ML especializado em GCP e HealthTech.

**Boas práticas aplicadas:**
- ✅ Type hints (PEP 484)
- ✅ Docstrings (PEP 257 / Google-style)
- ✅ Tratamento robusto de exceções
- ✅ Configuração via variáveis de ambiente
- ✅ Logging estruturado
- ✅ Código modular e testável
- ✅ Separação de responsabilidades
- ✅ Modo simulação para desenvolvimento
