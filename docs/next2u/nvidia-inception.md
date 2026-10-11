# Cadastro NVIDIA Inception — produto next2u SAÚDE

Textos para o formulário `programs.nvidia.com/phoenix/products/add-product`.
Fonte: este repositório (`docs/CRITICAL_PATH.md`, `docs/HBAND_COMPANION_CHECKLIST.md`,
`docs/next2u/matriz_expandida_158_alertas.txt`, `data/clinical_validation/latest_validation.json`).
O site next2u.com.br não pôde ser lido desta sessão; confira se os textos batem com ele.
O formulário é em inglês; a versão em português serve de referência.

## Campos curtos

| Campo | Valor sugerido |
|-------|----------------|
| Product/Service Name | next2u SAÚDE |
| Product/Service Webpage | https://next2u.com.br/ |
| Product/Service Type | Software / SaaS (plataforma + app Android) |
| Development Stage | Pilot / Beta (app v1.5; pulseira física em integração) |
| Accelerated by NVIDIA GPUs/DPUs at runtime? | **No** — o piloto roda em CPU (Cloud Run) com regras clínicas |
| Uses NVIDIA technologies? | **Yes** — CUDA (via PyTorch) no treino dos modelos de pesquisa |
| Which NVIDIA technologies are used? | CUDA |
| Considering NVIDIA technologies? | **Yes** |
| Which are being considered? | TensorRT, Triton Inference Server, RAPIDS (cuDF) |
| Non-NVIDIA technologies | Google Cloud (Cloud Run, Vertex AI, BigQuery, Cloud Storage), PyTorch, scikit-learn, FastAPI, PostgreSQL, Android/Kotlin, Bluetooth Low Energy, HL7 FHIR R4 |

## Product Logo

Arquivos em `docs/next2u/logo/`, quadrados, feitos a partir do logo oficial
(`dashboard/next2u-saude-logo.png`) centralizado com margem:

- `next2u-saude-logo-1024-branco.png` (1024×1024, fundo branco) — recomendado para o upload
- `next2u-saude-logo-600-branco.png` (600×600, fundo branco, logo em resolução nativa)
- `next2u-saude-logo-600-transparente.png` (600×600, fundo transparente)

## Description and value proposition (200–500 caracteres)

**EN (490 caracteres)**

next2u SAÚDE is a remote monitoring platform for chronic patients at home. A wristband sends heart rate, SpO2, blood pressure, temperature and sleep data to an Android companion app, which uploads it to a secure API. A matrix of 158 clinical rules flags early signs of deterioration in hypertension, diabetes, kidney, lung and liver disease and pregnancy on a care-team dashboard. Every alert is decision support for the clinician, never a diagnosis. Goal: fewer avoidable hospitalizations.

**PT (463 caracteres)**

O next2u SAÚDE monitora em casa pacientes com doenças crônicas. Uma pulseira envia frequência cardíaca, SpO2, pressão, temperatura e sono a um app Android, que repassa os dados a uma API segura. Uma matriz de 158 regras clínicas aponta sinais precoces de piora em hipertensão, diabetes, doença renal, pulmonar e hepática e gestação, num painel da equipe de saúde. Cada alerta apoia a decisão do profissional e não é diagnóstico. Meta: menos internações evitáveis.

## Technical Details (máx. 1.000 caracteres)

**EN (923 caracteres)**

Pipeline: BLE wristband (HBand/Veepoo SDK or standard Bluetooth health profile) -> Kotlin Android companion with offline outbox -> FastAPI ingest API (scoped API keys, rate limiting, per-patient authorization, idempotent writes to PostgreSQL) -> rule engine with 158 base alerts expanded to 971 patterns weighted by hospitalization risk, comorbidities and medication -> care-team dashboard. Data flows through a Bronze/Silver/Gold lakehouse on Google Cloud (Cloud Run, BigQuery, Cloud Storage) and exports HL7 FHIR R4. Signal processing: wavelet denoising, Bayesian sensor fusion, adaptive UKF. Research track, not in the pilot: PyTorch TCN forecasting deterioration at 6/24/72h. Challenges: the TCN scores F1 0.98 in training but 0.64 on real labels (5 patients), so we need more real data and patient-level validation before exposing forecasts; integration with the physical wristband and LGPD compliance are in progress.

**PT (881 caracteres)**

Fluxo: pulseira BLE (SDK HBand/Veepoo ou perfil Bluetooth de saúde padrão) -> app Android em Kotlin com fila offline -> API FastAPI de ingestão (chaves com escopo, rate limit, autorização por paciente, gravação idempotente em PostgreSQL) -> motor de 158 alertas-base expandidos para 971 padrões, ponderados por risco de internação, comorbidades e medicamentos -> painel da equipe. Os dados passam por um lakehouse Bronze/Silver/Gold no Google Cloud (Cloud Run, BigQuery, Cloud Storage) e saem em HL7 FHIR R4. Sinais: wavelet, fusão bayesiana de sensores e UKF adaptativo. Em pesquisa, fora do piloto: TCN em PyTorch para prever piora em 6/24/72h. Desafios: o TCN tem F1 0,98 no treino e 0,64 em rótulos reais (5 pacientes); faltam mais dados reais e validação por paciente antes de expor previsões. A integração com a pulseira física e a conformidade com a LGPD estão em andamento.

## Cuidados

- Não descreva o TCN, o conformal nem o classificador da matriz como validados clinicamente
  (ver `AGENTS.md`). O F1 do `alert_matrix_classifier.pkl` vem de dados sintéticos.
- Não diga que o produto roda em GPU NVIDIA hoje. Só o treino de pesquisa usa CUDA.
- Sessões `ble_sim` não contam como piloto.
