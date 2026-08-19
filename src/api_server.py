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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# Garantir imports corretos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
    version="3.0.0"
)

# Habilitar CORS para permitir requisições do frontend local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montar diretório de frontend estático
if os.path.exists("dashboard"):
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
lake_path = f"gs://{gcs_staging_bucket.replace('gs://', '').strip()}" if gcs_staging_bucket else 'data/lake'
dl_manager = DataLakeManager(lake_path=lake_path)
slm_engine = SLMSearchEngine()

ontology_mapper = ClinicalOntologyMapper()
bayes_net = BayesianDiagnosticNetwork()
report_generator = OntologyEnrichedReport(ontology_mapper, bayes_net)

# Inicializar clientes do GCP (BigQuery e Vertex Endpoint)
bq_client = None
vertex_detector = None

if gcp_project and not os.getenv("TESTING"):
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


@app.get("/api/status")
def get_status():
    """Retorna o status atual dos motores do sistema."""
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
def search_literature(search: SearchQuery):
    """Busca literatura nas teses da USP via SLM (RAG)."""
    if not search.query:
        raise HTTPException(status_code=400, detail="Query de busca vazia.")
    
    results = slm_engine.search_theses(search.query, n_results=search.n_results)
    return {"results": results}


@app.post("/api/reindex")
def reindex_theses():
    """Reindexa o acervo de teses do Data Lake."""
    df_theses = dl_manager.load_theses_raw()
    if df_theses.empty:
        return {"status": "warning", "message": "Nenhuma tese encontrada no Data Lake."}
    
    count = slm_engine.index_theses(df_theses)
    return {"status": "success", "message": f"{count} teses indexadas no ChromaDB."}


class ConnectionManager:
    """Gerencia conexões WebSocket ativas com os clientes web."""
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Cliente conectado. Total de conexões ativas: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Cliente desconectado. Total de conexões ativas: {len(self.active_connections)}")

    async def broadcast_json(self, data: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception as e:
                logger.error(f"Erro ao transmitir dados via WebSocket: {e}")
                self.disconnect(connection)

manager = ConnectionManager()


async def telemetry_stream_loop():
    """Loop contínuo de geração e transmissão de dados a 4Hz."""
    logger.info("Iniciando gerador contínuo de telemetria e inferência...")
    
    # Instanciar pipelines matemáticos
    sensor_fuser = AdaptiveSensorFusion(["pixel_watch", "fitbit_band"])
    wavelet_denoiser = WaveletDenoiser()
    butter_filter = ButterworthFilter(fs=4.0)
    phantom_engine = PhantomDataEngine(dt=sim_config.dt, use_ukf=sim_config.use_ukf)
    hrv_analyzer = HRVAnalyzer(fs=4.0)
    
    # Buffers para cálculos temporais
    raw_bpm_buffer = []
    rr_intervals_buffer = []
    
    # Estados latentes basais para o paciente simulado
    hr_state = 72.0
    rmssd_state = 42.0
    temp_state = 33.2
    
    while True:
        if not sim_config.is_running:
            await asyncio.sleep(0.5)
            continue
            
        # 1. Simular evolução fisiológica (Ornstein-Uhlenbeck simplificado com drift)
        # Eventos estocásticos de stress a cada ~30 segundos
        is_stress = np.random.random() < 0.05
        drift = 15.0 if is_stress else 0.0
        
        hr_state += 0.1 * (72.0 + drift - hr_state) + np.random.normal(0, 1.2)
        rmssd_state += 0.05 * (42.0 - (drift * 0.8) - rmssd_state) + np.random.normal(0, 0.8)
        temp_state += 0.02 * (33.2 - temp_state) + np.random.normal(0, 0.05)
        
        hr_state = max(40.0, min(180.0, hr_state))
        rmssd_state = max(5.0, rmssd_state)
        temp_state = np.clip(temp_state, 31.0, 39.0)
        
        # 2. Simular leituras brutas de 2 wearables com ruídos diferentes
        watch_noise = np.random.normal(0, 1.8)
        band_noise = np.random.normal(0, 4.0)
        
        watch_reading = hr_state + watch_noise
        band_reading = hr_state + band_noise
        
        # 3. Sensor Fusion Bayesiana
        fused = sensor_fuser.fuse_readings({
            "pixel_watch": watch_reading,
            "fitbit_band": band_reading
        })
        bpm_fused = fused['fused_estimate']
        raw_bpm_buffer.append(watch_reading)
        
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
            
        if phantom_engine.use_ukf != sim_config.use_ukf:
            phantom_engine = PhantomDataEngine(dt=sim_config.dt, use_ukf=sim_config.use_ukf)
            
        wearable_reading = {
            'heart_rate': bpm_clean,
            'hrv_rmssd': rmssd_state,
            'skin_temp': temp_state,
            'activity_level': 1.5 if is_stress else 0.0
        }
        
        anomaly_res = {"alerta": False, "score": 0.0, "modo": "Simulação"}
        if vertex_detector:
            try:
                anomaly_res = vertex_detector.processar_nova_leitura(bpm_clean)
            except Exception as e:
                logger.error(f"Erro ao chamar Vertex AI Endpoint: {e}")
        else:
            is_anomalia_mock = bpm_clean > 100 or bpm_clean < 40
            anomaly_res = {
                "alerta": is_anomalia_mock,
                "score": 0.99 if is_anomalia_mock else 0.1,
                "modo": "Simulação Local"
            }
            
        # Inserção assíncrona no BigQuery
        if bq_client and gcp_project:
            row_to_insert = [{
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "patient_id": "SECURE_PATIENT_001",
                "bpm_bruto_watch": float(watch_reading),
                "bpm_bruto_band": float(band_reading),
                "bpm_fused": float(bpm_fused),
                "bpm_clean": float(bpm_clean),
                "is_anomalia": bool(anomaly_res.get("alerta", False)),
                "score_anomalia": float(anomaly_res.get("score", 0.0))
            }]
            table_id = f"{gcp_project}.healthtech_datalake.telemetria_tempo_real"
            try:
                bq_client.insert_rows_json(table_id, row_to_insert)
            except Exception as e:
                logger.debug(f"BigQuery stream buffer: {e}")
                
        phantom_states = phantom_engine.process_reading(wearable_reading)
        
        rr_interval = (60.0 / bpm_clean) * 1000.0 + np.random.normal(0, 5.0)
        rr_intervals_buffer.append(rr_interval)
        if len(rr_intervals_buffer) > 60:
            rr_intervals_buffer.pop(0)
            
        hrv_metrics = hrv_analyzer.compute_time_domain(np.array(rr_intervals_buffer))
        
        hypotheses = bayes_net.generate_diagnostic_hypotheses(
            phantom_data=phantom_states,
            hrv_metrics=hrv_metrics,
            anomaly_score=anomaly_res
        )
        
        report = report_generator.generate_patient_report(
            patient_id="SECURE_PATIENT_001",
            phantom_data=phantom_states,
            hrv_metrics=hrv_metrics,
            anomaly_score=anomaly_res
        )
        
        frame = {
            "type": "telemetry",
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "wearable": {
                "watch_raw": round(watch_reading, 1),
                "band_raw": round(band_reading, 1),
                "fused_bpm": round(bpm_fused, 1),
                "clean_bpm": round(bpm_clean, 1),
                "rmssd": round(rmssd_state, 1),
                "skin_temp": round(temp_state, 2)
            },
            "phantom_data": {
                k: {
                    "estimate": round(v['estimate'], 2),
                    "ci_lower": round(v['ci_lower'], 2),
                    "ci_upper": round(v['ci_upper'], 2),
                    "is_reliable": v['is_reliable']
                } for k, v in phantom_states.items()
            },
            "anomaly": anomaly_res,
            "hrv": {
                "sdnn": round(hrv_metrics.get('sdnn', 0), 1),
                "rmssd": round(hrv_metrics.get('rmssd', 0), 1),
                "pnn50": round(hrv_metrics.get('pnn50', 0), 1)
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
        
        await manager.broadcast_json(frame)
        await asyncio.sleep(0.4)


@app.on_event("startup")
async def startup_event():
    """Inicializa tarefas em segundo plano no arranque do app."""
    if not os.getenv("TESTING"):
        asyncio.create_task(telemetry_stream_loop())
        logger.info("Serviço de streaming de telemetria inicializado no background.")


@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    """Canal WebSocket para comunicação bidirecional de dados e controle."""
    await manager.connect(websocket)
    try:
        await websocket.send_json({
            "type": "config",
            "filter_type": sim_config.filter_type,
            "use_ukf": sim_config.use_ukf,
            "is_running": sim_config.is_running
        })
        
        while True:
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
            elif action == "set_ukf":
                sim_config.use_ukf = bool(data.get("value"))
                logger.info(f"Modo UKF alterado para: {sim_config.use_ukf}")
                
            await manager.broadcast_json({
                "type": "config",
                "filter_type": sim_config.filter_type,
                "use_ukf": sim_config.use_ukf,
                "is_running": sim_config.is_running
            })
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Erro na sessão WebSocket: {e}")
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("src.api_server:app", host="0.0.0.0", port=port, reload=False)
