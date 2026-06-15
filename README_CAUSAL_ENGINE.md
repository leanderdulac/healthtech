# HealthCausal Engine v2.0 - Documentação Técnica

## 🏥 Sistema Enterprise de IA Médica com Especialistas por Domínio e Inferência Causal

### Visão Geral

O **HealthCausal Engine** é um sistema avançado de monitoramento médico em tempo real que utiliza uma arquitetura multi-especialista combinada com um motor de inferência causal para prever eventos adversos em cascata. Diferente de sistemas tradicionais de alerta baseados em thresholds simples, este sistema:

1. **Segmenta por domínio clínico** - Um algoritmo especializado para cada tipo de dado médico
2. **Valida fisiologicamente** - Proxy anti-falso positivo que verifica coerência entre sinais vitais
3. **Prevê efeitos em cascata** - Motor causal que prediz como a elevação de um parâmetro afeta os demais

---

## 🏗️ Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                    STREAM DE DISPOSITIVOS IoT                    │
│            (Milhares de dispositivos médicos diversos)           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              1. CROSS-VALIDATION PROXY (Filtro)                 │
│   • Verifica coerência fisiológica entre sinais vitais          │
│   • Reduz confiança em leituras incoerentes                      │
│   • Ex: HR 220 + SpO2 99% = RUÍDO (improvável fisiologicamente) │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              2. ESPECIALISTAS POR DOMÍNIO (Parallel)            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │   Cardíaco   │ │ Hemodinâmico │ │  Metabólico  │            │
│  │  (Infarto)   │ │  (Pressão)   │ │  (Diabetes)  │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
│  ┌──────────────┐                                              │
│  │ Neurovascular│                                              │
│  │    (AVC)     │                                              │
│  └──────────────┘                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           3. CAUSAL INFERENCE ENGINE (The Merger)               │
│   • Grafo causal ponderado (BP → Stroke, HR → Cardiac)         │
│   • Propagação de risco em cascata                              │
│   • Predição do "próximo evento" provável                       │
│   • Recomendações clínicas acionáveis                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  CLINICAL EVENT ALERT                            │
│  • Severidade (INFO → LIFE_THREATENING)                         │
│  • Cadeia causal completa                                       │
│  • Fatores contribuintes                                        │
│  • Recomendação de tratamento                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Componentes Detalhados

### 1. Algoritmos Especialistas (One-per-Metric)

Cada especialista implementa lógica clínica validada para seu domínio específico:

#### **CardiacSpecialist** - Infarto e Arritmia
- **Inputs**: Heart Rate (histórico de 50 leituras)
- **Técnicas**:
  - Detecção de taquicardia (>140 bpm) e bradicardia (<40 bpm)
  - **HRV Analysis**: Baixa variabilidade (<10) indica estresse/ischemia
  - **Slope Detection**: Aumento súbito >30 bpm em janelas curtas
- **Outputs**: `ACUTE_MI_RISK`, `ARRHYTHMIA_DETECTED`
- **Score**: 0.0 - 1.0 (risco acumulado)

#### **HemodynamicSpecialist** - Pressão Arterial
- **Inputs**: BP Sistólica, BP Diastólica
- **Técnicas**:
  - Cálculo de **MAP** (Mean Arterial Pressure)
  - Detecção de crise hipertensiva (>180/120)
  - Identificação de **pressão de pulso estreita** (<25 mmHg) → tamponamento/shock
  - Hipotensão de choque (MAP <65)
- **Outputs**: `HEMODYNAMIC_INSTABILITY`, `SHOCK_RISK`

#### **MetabolicSpecialist** - Diabetes e Glicose
- **Inputs**: Glucose (mg/dL), histórico temporal
- **Técnicas**:
  - Hipoglicemia severa (<50 mg/dL)
  - Hiperglicemia/cetoacidose (>400 mg/dL)
  - **Rate of Change**: Queda rápida (>3 mg/dL/min) prevê hipoglicemia iminente
- **Outputs**: `METABOLIC_EMERGENCY`, `GLUCOSE_INSTABILITY`

#### **NeurovascularSpecialist** - AVC (Stroke)
- **Inputs Compostos**: BP, HR, Irregularidade Cardíaca, Histórico
- **Técnicas**:
  - Combinação HTN + Idade >60
  - **AFib Proxy**: HR irregular (desvio padrão / média)
  - Fator histórico (prior_stroke)
- **Outputs**: `HIGH_STROKE_PROBABILITY`, `STROKE_WATCH`

---

### 2. Cross-Validation Proxy (Anti-False Positive)

Este componente atua como um **filtro de ruído fisiológico**. Em vez de confiar cegamente em cada sensor, ele verifica se os sinais vitais são coerentes entre si:

**Regras de Validação**:
| Regra | Condição | Penalidade |
|-------|----------|------------|
| Taquicardia sem hipóxia | HR >150 + SpO2 >95 + RR <20 | -0.4 |
| Hipotensão sem compensação | BP <80 + HR <90 | -0.3 |
| Hipóxia severa sem taquicardia | SpO2 <80 + HR normal | -0.5 |

**Resultado**: 
- `confidence_score = 1.0 - penalty`
- Se `confidence < 0.6`: Alerta gerado com confiança reduzida ou suprimido

**Exemplo Prático**:
```python
# Cenário: Sensor de HR defeituoso lendo 220 bpm
vitals = {"heart_rate": 220, "spo2": 99, "resp_rate": 16}
# Resultado: Incoerência detectada! 
# HR 220 deveria causar SpO2 baixo e RR alto.
# Confiança reduzida para 0.6 → Alerta suprimido
```

---

### 3. Causal Inference Engine (The Merger)

O "cérebro" do sistema. Utiliza um **grafo causal direcionado ponderado** para simular a fisiologia humana e prever efeitos em cascata.

#### Matriz de Impacto Causal

```python
causal_graph = {
    'bp_sys': {
        'stroke_risk': 0.8,      # PA alta → 80% risco de AVC
        'cardiac_risk': 0.6,     # PA alta → 60% risco cardíaco
        'renal_risk': 0.5        # PA alta → 50% risco renal
    },
    'heart_rate': {
        'cardiac_risk': 0.9,     # TAQUITAQUICARDIA → 90% risco infarto
        'stroke_risk': 0.4,      # FC alta → 40% risco AVC
        'metabolic_demand': 0.7  # FC alta → 70% demanda metabólica
    },
    'glucose': {
        'neuro_risk': 0.7,       # Glicose extrema → 70% risco neurológico
        'cardiac_risk': 0.3,
        'infection_risk': 0.4
    },
    'spo2': {
        'cardiac_risk': 0.8,     # Hipóxia → 80% risco cardíaco
        'neuro_risk': 0.9,       # Hipóxia → 90% dano cerebral
        'organ_failure': 0.8
    }
}
```

#### Algoritmo de Propagação

1. **Identificar Gatilhos**: Scores de especialistas > 0.5
2. **Propagar no Grafo**: Para cada gatilho, calcular impacto nos nós vizinhos
   ```
   impact_value = specialist_score * causal_weight
   ```
3. **Acumular Risco**: Se múltiplos fatores afetam o mesmo alvo, usar o máximo
4. **Detectar Cascata Crítica**: Se `impact_value > 0.6` → adicionar ao caminho crítico
5. **Predizer Próximo Evento**: Nó com maior risco acumulado

**Exemplo de Saída**:
```json
{
  "status": "CRITICAL_CHAIN",
  "primary_trigger": "hemodynamic_risk",
  "predicted_next_event": "stroke_risk",
  "probability": 0.84,
  "causal_chain": [
    "bp_sys ↑ → stroke_risk CRITICAL (0.84)"
  ],
  "recommendation": "ADMINISTER ANTIHYPERTENSIVES IMMEDIATELY. PREPARE CT SCAN."
}
```

---

## 🔧 Como Usar

### Instalação de Dependências

```bash
pip install numpy pandas scipy
```

### Exemplo Básico

```python
from main_causal_engine import (
    HealthCausalOrchestrator, 
    PatientContext
)

# 1. Inicializar o motor
engine = HealthCausalOrchestrator()

# 2. Criar contexto do paciente
patient = PatientContext(
    patient_id="PT-123456",
    age=72,
    gender="M",
    history={"hypertension": True, "diabetes": False},
    baseline_metrics={"hr": 75, "bp": 130}
)

# 3. Simular fluxo de dados em tempo real
vitals_stream = {
    "heart_rate": 145,
    "bp_sys": 165,
    "bp_dia": 95,
    "spo2": 94,
    "resp_rate": 24,
    "glucose": 140
}

# 4. Processar e obter alerta (se houver)
event = engine.process_stream(patient, vitals_stream)

if event:
    print(f"ALERTA: {event.prediction}")
    print(f"Severidade: {event.severity.name}")
    print(f"Cadeia Causal: {event.causal_chain}")
    print(f"Fatores: {event.contributing_factors}")
```

### Integração com Streaming (Kafka/PubSub)

```python
# Pseudocódigo para integração GCP Pub/Sub
from google.cloud import pubsub_v1

def callback(message):
    vitals = json.loads(message.data.decode())
    patient = get_patient_context(vitals['patient_id'])
    
    event = engine.process_stream(patient, vitals)
    
    if event and event.severity >= AlertSeverity.HIGH:
        send_to_clinical_dashboard(event)
        trigger_pagerduty_alert(event)

subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_NAME)
streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
```

---

## 🧪 Cenários de Teste Incluídos

O script inclui 4 cenários de teste automatizados:

### Cenário 1: Infarto Agudo do Miocárdio
- **Dados**: HR 145, BP 165/95, HRV baixa
- **Esperado**: `ACUTE_CARDIAC_EVENT` (CRITICAL)
- **Cadeia**: HR ↑ → cardiac_risk CRITICAL

### Cenário 2: AVC Hemorrágico Iminente
- **Dados**: BP 210/130, HR irregular, idade 72
- **Esperado**: `HEMODYNAMIC_COLLAPSE` ou `IMMINENT_STROKE` (HIGH/CRITICAL)
- **Cadeia**: bp_sys ↑ → stroke_risk CRITICAL

### Cenário 3: Choque Séptico
- **Dados**: HR 130, BP 85/50, Temp 39.5°C, RR 32
- **Esperado**: Detecção de dissociação (taquicardia + hipotensão)

### Cenário 4: Ruído de Sensor (False Positive Test)
- **Dados**: HR 220 (improvável), SpO2 99% (incoerente)
- **Esperado**: Alerta suprimido ou confiança reduzida
- **Mensagem**: "Incoherence detected: Tachycardia without hypoxia"

---

## 📊 Estrutura de Dados

### PatientContext
```python
@dataclass
class PatientContext:
    patient_id: str
    age: int
    gender: str
    history: Dict[str, bool]  # {"diabetes": True, "hypertension": False}
    baseline_metrics: Dict[str, float]  # {"hr": 75, "bp": 130}
```

### ClinicalEvent
```python
@dataclass
class ClinicalEvent:
    timestamp: datetime
    patient_id: str
    source_module: str
    severity: AlertSeverity  # NORMAL, LOW, MEDIUM, HIGH, CRITICAL, LIFE_THREATENING
    prediction: str  # "ACUTE_CARDIAC_EVENT", "IMMINENT_STROKE", etc.
    confidence: float  # 0.0 - 1.0
    contributing_factors: Dict[str, float]  # {"tachycardia_extreme": 1.0, "low_hrv": 1.0}
    causal_chain: List[str]  # ["bp_sys ↑ → stroke_risk CRITICAL (0.84)"]
```

---

## 🚀 Próximos Passos (Roadmap)

### Fase 1: Aprimoramentos de ML
- [ ] Substituir regras fixas por modelos treinados (XGBoost, LSTM)
- [ ] Implementar aprendizado contínuo com feedback clínico
- [ ] Adicionar embeddings de pacientes similares

### Fase 2: Integração GCP
- [ ] Deploy no Vertex AI como endpoint online
- [ ] Pipeline batch no BigQuery para análise populacional
- [ ] Dashboard no Looker Studio

### Fase 3: Validação Clínica
- [ ] Teste retrospectivo com dataset MIMIC-III
- [ ] Validação com médicos especialistas
- [ ] Certificação FDA/ANVISA (classe II)

### Fase 4: Escala Enterprise
- [ ] Suporte a 100k+ dispositivos simultâneos
- [ ] Multi-tenancy para hospitais
- [ ] API FHIR R4 para integração com EHRs

---

## ⚠️ Disclaimer

Este software é um **sistema de suporte à decisão clínica** e NÃO substitui o julgamento médico profissional. Todos os alertas devem ser revisados por profissionais de saúde qualificados antes de qualquer intervenção.

Uso restrito a fins de pesquisa e desenvolvimento até aprovação regulatória.

---

## 📄 Licença

MIT License - Ver arquivo LICENSE para detalhes.

## 👥 Autores

Desenvolvido por Engenheiro de Dados & ML Specialist (GCP HealthTech)
