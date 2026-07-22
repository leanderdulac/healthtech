"""
api_server.py — Servidor API FastAPI e WebSocket Streaming

Este script fornece o backend web para o dashboard da plataforma HealthTech.
Ele gerencia a conexão WebSocket para transmitir leituras de wearables e dados fantasmas
inferidos em tempo real para o navegador, além de endpoints REST para busca semântica
RAG (SLM) e controle de parâmetros.
"""

from __future__ import annotations

import asyncio
import json
import logging
import datetime
import os
import sys
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# Garantir imports corretos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.security.auth import (
    cors_allow_credentials,
    get_cors_origins,
    require_api_key,
    validate_secret_salt,
    verify_api_key,
)
from src.data_warehouse.datalake_manager import DataLakeManager
from src.ml_pipeline.slm_search_engine import SLMSearchEngine
from src.ml_pipeline.online_inference import VertexOnlineDetector
from src.signal_processing import WaveletDenoiser, ButterworthFilter, AdaptiveSensorFusion
from src.phantom_data import PhantomDataEngine, HRVAnalyzer
from src.ontology import ClinicalOntologyMapper, BayesianDiagnosticNetwork, OntologyEnrichedReport

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HealthTech Advanced API Server",
    description="Servidor de telemetria biométrica, processamento de sinais e dados fantasmas.",
    version="2.1.0"
)

# CORS restrito (nunca * com credentials). Configure CORS_ORIGINS em produção.
_cors_origins = get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:8080"],
    allow_credentials=cors_allow_credentials(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*", "X-API-Key"],
)

# Montar diretório de frontend estático
app.mount("/dashboard", StaticFiles(directory="dashboard"), name="dashboard")

@app.get("/")
def read_root():
    """Redireciona a raiz para o dashboard estático."""
    return RedirectResponse(url="/dashboard/index.html")


# Carregar configurações do GCP
gcp_project = os.getenv("GCP_PROJECT_ID")
gcp_location = os.getenv("GCP_LOCATION", "us-central1")
gcs_staging_bucket = os.getenv("GCS_STAGING_BUCKET")
vertex_endpoint = os.getenv("VERTEX_ENDPOINT_ID")

# Inicializar gerenciadores compartilhados
# Se tivermos GCS staging bucket configurado, usar como caminho do Data Lake
lake_path = f"gs://{gcs_staging_bucket.replace('gs://', '').strip()}" if gcs_staging_bucket else 'data/lake'
dl_manager = DataLakeManager(lake_path=lake_path)
slm_engine = SLMSearchEngine()

ontology_mapper = ClinicalOntologyMapper()
bayes_net = BayesianDiagnosticNetwork()
report_generator = OntologyEnrichedReport(ontology_mapper, bayes_net)

# Inicializar clientes do GCP (BigQuery e Vertex Endpoint)
bq_client = None
vertex_detector = None

if gcp_project:
    logger.info(f"Conectando ao Google BigQuery no projeto '{gcp_project}'...")
    try:
        from google.cloud import bigquery
        bq_client = bigquery.Client(project=gcp_project)
    except Exception as e:
        logger.error(f"Erro ao instanciar cliente do BigQuery: {e}")
        
    if vertex_endpoint:
        logger.info(f"Conectando ao Vertex AI Endpoint '{vertex_endpoint}'...")
        try:
            vertex_detector = VertexOnlineDetector(
                project=gcp_project, 
                location=gcp_location, 
                endpoint_id=vertex_endpoint
            )
        except Exception as e:
            logger.error(f"Erro ao instanciar detector online do Vertex: {e}")

# Configurações globais de simulação modificáveis via WebSocket
class SimConfig:
    def __init__(self):
        self.is_running: bool = False
        self.filter_type: str = "Sem Filtro"  # "Sem Filtro", "Wavelet", "Butterworth"
        self.use_ukf: bool = False            # False=EKF, True=UKF
        self.dt: float = 1.0                  # Passo de tempo (segundos)

sim_config = SimConfig()


class SearchQuery(BaseModel):
    query: str
    n_results: int = 3


@app.get("/api/health")
def health_probe():
    """Probe público para orquestradores (Cloud Run / k8s)."""
    return {"status": "healthy", "service": "HealthTech API"}


@app.get("/api/status")
def get_status(_api_key: Optional[str] = Depends(require_api_key)):
    """Retorna o status atual dos motores do sistema (requer API key)."""
    df_lake = dl_manager.load_latest_knowledge()
    return {
        "status": "online",
        "slm_loaded": slm_engine.encoder is not None,
        "ontology_loaded": len(ontology_mapper.ontology) > 0,
        "data_lake_size": len(df_lake),
        "config": {
            "simulation_running": sim_config.is_running,
            "filter_type": sim_config.filter_type,
            "use_ukf": sim_config.use_ukf
        }
    }


@app.post("/api/search")
def search_literature(
    search: SearchQuery,
    _api_key: Optional[str] = Depends(require_api_key),
):
    """Busca literatura nas teses da USP via SLM (RAG)."""
    if not search.query:
        raise HTTPException(status_code=400, detail="A consulta (query) não pode estar vazia.")
    
    try:
        results = slm_engine.search_medical_knowledge(search.query, n_results=search.n_results)
        
        parsed_docs = []
        if results['documents'] and len(results['documents'][0]) > 0:
            for i in range(len(results['documents'][0])):
                meta = results['metadatas'][0][i]
                dist = results['distances'][0][i] if 'distances' in results and results['distances'] else 0.0
                parsed_docs.append({
                    "document": results['documents'][0][i],
                    "url": meta.get('url', ''),
                    "autor": meta.get('autor', 'Desconhecido'),
                    "topico_dominante": meta.get('topico_dominante', 'N/A'),
                    "distance_l2": float(dist)
                })
        return {"results": parsed_docs}
    except Exception as e:
        logger.error(f"Erro na busca do SLM: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reindex")
def reindex_data_lake(_api_key: Optional[str] = Depends(require_api_key)):
    """Re-indexa o Data Lake no banco vetorial ChromaDB."""
    try:
        slm_engine.index_datalake(dl_manager)
        return {"status": "success", "message": "Data lake reindexado com sucesso."}
    except Exception as e:
        logger.error(f"Erro ao reindexar data lake: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Gerenciador de conexões WebSocket ativas
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Nova conexão WebSocket aceita. Total de conexões: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Conexão WebSocket encerrada. Restantes: {len(self.active_connections)}")

    async def broadcast_json(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Conexão corrompida será limpa na leitura
                pass

manager = ConnectionManager()


async def telemetry_stream_loop():
    """
    Loop assíncrono em segundo plano para geração de sinais e inferência de dados fantasmas.
    Transmite os dados via WebSocket para todos os clientes conectados.
    """
    # Instanciar filtros
    wavelet_denoiser = WaveletDenoiser(wavelet='db4', level=2)
    butter_filter = ButterworthFilter(fs=1.0)
    sensor_fuser = AdaptiveSensorFusion(sensor_ids=["pixel_watch", "fitbit_band"])
    phantom_engine = PhantomDataEngine(dt=sim_config.dt, use_ukf=sim_config.use_ukf)
    
    # buffers históricos locais para filtros
    raw_bpm_buffer = []
    
    # Estados de simulação fisiológica
    hr_state = 70.0
    rmssd_state = 40.0
    temp_state = 33.0
    step = 0
    
    while True:
        if not sim_config.is_running or not manager.active_connections:
            await asyncio.sleep(0.5)
            continue
            
        step += 1
        
        # 1. Simular transições de estresse/arritmia fisiológica
        # Entre os passos 40 e 80, simular evento de taquicardia sinusal e estresse agudo
        is_stress = 40 <= (step % 120) <= 80
        target_hr = 115.0 if is_stress else 70.0
        target_rmssd = 15.0 if is_stress else 45.0
        target_temp = 33.6 if is_stress else 33.0
        
        # Ornstein-Uhlenbeck
        hr_state += 0.3 * (target_hr - hr_state) + np.random.normal(0, 2.5)
        rmssd_state += 0.3 * (target_rmssd - rmssd_state) + np.random.normal(0, 2)
        temp_state += 0.1 * (target_temp - temp_state) + np.random.normal(0, 0.05)
        
        hr_state = np.clip(hr_state, 40.0, 180.0)
        rmssd_state = max(5.0, rmssd_state)
        temp_state = np.clip(temp_state, 31.0, 39.0)
        
        # 2. Simular leituras brutas de 2 wearables com ruídos diferentes
        watch_noise = np.random.normal(0, 1.8)
        band_noise = np.random.normal(0, 4.0) # fitbit mais barulhento
        
        watch_reading = hr_state + watch_noise
        band_reading = hr_state + band_noise
        
        # 3. Sensor Fusion Bayesiana
        fused = sensor_fuser.fuse_readings({
            "pixel_watch": watch_reading,
            "fitbit_band": band_reading
        })
        bpm_fused = fused['fused_estimate']
        raw_bpm_buffer.append(watch_reading)
        
        # Manter buffer compacto
        if len(raw_bpm_buffer) > 100:
            raw_bpm_buffer.pop(0)
            
        # 4. Denoising Físico
        if sim_config.filter_type == "Wavelet" and len(raw_bpm_buffer) >= 4:
            win = np.array(raw_bpm_buffer[-8:])
            denoised = wavelet_denoiser.denoise(win)
            bpm_clean = denoised[-1]
        elif sim_config.filter_type == "Butterworth" and len(raw_bpm_buffer) >= 4:
            win = np.array(raw_bpm_buffer[-8:])
            denoised = butter_filter.lowpass(win, cutoff=0.3)
            bpm_clean = denoised[-1]
        else:
            bpm_clean = bpm_fused
            
        # 5. Injetar no Motor de Dados Fantasmas
        # Ajustar tipo de filtro se houver alteração
        if phantom_engine.use_ukf != sim_config.use_ukf:
            phantom_engine = PhantomDataEngine(dt=sim_config.dt, use_ukf=sim_config.use_ukf)
            
        wearable_reading = {
            'heart_rate': bpm_clean,
            'hrv_rmssd': rmssd_state,
            'skin_temp': temp_state,
            'activity_level': 1.5 if is_stress else 0.0
        }
        
        # 5.5 Detectar Anomalia via Vertex AI (ou Fallback Local)
        anomaly_res = {"alerta": False, "score": 0.0, "modo": "Simulação"}
        if vertex_detector:
            try:
                anomaly_res = vertex_detector.processar_nova_leitura(bpm_clean)
            except Exception as e:
                logger.error(f"Erro ao chamar Vertex AI Endpoint: {e}")
        else:
            # Fallback local de detecção: anomalia se bpm fora de [40, 100]
            is_anomalia_mock = bpm_clean > 100 or bpm_clean < 40
            anomaly_res = {
                "alerta": is_anomalia_mock,
                "score": 0.99 if is_anomalia_mock else 0.1,
                "modo": "Simulação Local"
            }
        is_anomaly = anomaly_res["alerta"]

        # Se BigQuery client estiver instanciado, gravar a leitura no banco em background
        if bq_client:
            try:
                row_to_insert = [{
                    "patient_id": "SECURE_PATIENT_001",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "heart_rate_bpm": int(round(bpm_clean)),
                    "sensors_used": ["pixel_watch", "fitbit_band"],
                    "is_anomaly": bool(is_anomaly)
                }]
                loop = asyncio.get_event_loop()
                # insert_rows_json faz requisição HTTP POST para a API do BigQuery Streaming Ingest
                loop.run_in_executor(
                    None, 
                    bq_client.insert_rows_json, 
                    f"{gcp_project}.healthtech_datalake.wearable_biometrics", 
                    row_to_insert
                )
            except Exception as bq_err:
                logger.error(f"Erro ao inserir biometria no BigQuery: {bq_err}")

        phantom_res = phantom_engine.process_reading(wearable_reading)
        states = phantom_res['states']
        
        # 6. Diagnóstico Bayesiano e Ontologia
        current_phantom = {k: v['estimate'] for k, v in states.items()}
        hrv_metrics = {'rmssd': rmssd_state}
        
        hypotheses = bayes_net.generate_diagnostic_hypotheses(
            phantom_data=current_phantom,
            hrv_metrics=hrv_metrics,
            anomaly_score=anomaly_res,
            top_k=4
        )
        
        report = report_generator.generate_patient_report(
            patient_id="SECURE_PATIENT_001",
            phantom_data=current_phantom,
            hrv_metrics=hrv_metrics,
            anomaly_score=anomaly_res
        )
        
        # 7. Montar Frame de Telemetria
        frame = {
            "step": step,
            "is_stress": is_stress,
            "anomaly_detection": {
                "is_anomaly": is_anomaly,
                "score": round(anomaly_res["score"], 4),
                "modo": anomaly_res["modo"]
            },
            "sensor_readings": {
                "pixel_watch_raw": round(watch_reading, 1),
                "fitbit_band_raw": round(band_reading, 1),
                "fused_estimate": round(bpm_fused, 1),
                "clean_estimate": round(bpm_clean, 1)
            },
            "sensor_weights": fused['weights'],
            "phantom_data": {
                name: {
                    "estimate": round(details['estimate'], 2),
                    "ci_lower": round(details['ci_lower'], 2),
                    "ci_upper": round(details['ci_upper'], 2),
                    "reliable": details['reliable']
                } for name, details in states.items()
            },
            "hypotheses": [
                {
                    "category": h['category'],
                    "probability": round(h['posterior_probability'], 4),
                    "severity": h['severity'],
                    "confidence": h['confidence_level']
                } for h in hypotheses
            ],
            "clinical_codes": report['clinical_codes']
        }
        
        # Transmitir via websocket
        await manager.broadcast_json(frame)
        
        # Latência de transmissão controlada (250ms = 4 frames por segundo)
        await asyncio.sleep(0.4)


@app.on_event("startup")
async def startup_event():
    """Inicializa tarefas em segundo plano no arranque do app."""
    validate_secret_salt(raise_in_production=True)
    asyncio.create_task(telemetry_stream_loop())
    logger.info(
        "Serviço de streaming de telemetria inicializado (CORS=%s).",
        get_cors_origins(),
    )


@app.websocket("/ws/telemetry")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: Optional[str] = Query(default=None),
):
    """Canal WebSocket. Auth via query ?api_key=... (browsers não enviam X-API-Key em WS)."""
    header_key = websocket.headers.get("x-api-key")
    if not verify_api_key(api_key or header_key):
        await websocket.close(code=4401, reason="API key inválida ou ausente")
        return

    await manager.connect(websocket)
    try:
        # Enviar estado de configuração atual
        await websocket.send_json({
            "type": "config",
            "filter_type": sim_config.filter_type,
            "use_ukf": sim_config.use_ukf,
            "is_running": sim_config.is_running
        })
        
        while True:
            # Aguarda comandos do cliente
            data_str = await websocket.receive_text()
            data = json.loads(data_str)
            action = data.get("action")
            
            if action == "start":
                sim_config.is_running = True
                logger.info("Simulação iniciada via comando WebSocket.")
            elif action == "stop":
                sim_config.is_running = False
                logger.info("Simulação pausada via comando WebSocket.")
            elif action == "set_filter":
                filter_val = data.get("value")
                if filter_val in ["Sem Filtro", "Wavelet", "Butterworth"]:
                    sim_config.filter_type = filter_val
                    logger.info(f"Filtro alterado para: {filter_val}")
            elif action == "set_kalman":
                kalman_val = data.get("value")
                sim_config.use_ukf = (kalman_val == "UKF")
                logger.info(f"Filtro de Kalman alterado. Use UKF: {sim_config.use_ukf}")
                
            # Retornar confirmação de configuração
            await manager.broadcast_json({
                "type": "config",
                "filter_type": sim_config.filter_type,
                "use_ukf": sim_config.use_ukf,
                "is_running": sim_config.is_running
            })
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Erro na conexão WebSocket: {e}")
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
