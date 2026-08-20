"""
api_monolith_runtime.py — Plataforma full (dashboard, WebSocket, phantom, Vertex).

Usado pela factory secure (`APP_MODE=full`) e reexportado por `src.api_server`.
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
from fastapi import Depends, FastAPI, Security, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# Garantir imports corretos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pydantic import BaseModel, Field, field_validator
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.requests import Request

from src.security.auth import (
    cors_allow_credentials,
    get_cors_origins,
    is_production,
    mask_api_key,
    require_api_key,
    require_patient_access,
    require_scope,
    validate_secret_salt,
    verify_api_key,
)

try:
    from app.security.headers import SecurityHeadersMiddleware
    from app.security.rate_limit import PathRateLimitMiddleware as RateLimitingMiddleware
    from app.services.audit import AuditLoggingMiddleware
except ImportError:  # execução sem pacote secure no PYTHONPATH
    from src.security.security_headers import SecurityHeadersMiddleware
    from src.security.rate_limiter import RateLimitingMiddleware
    from src.security.audit_logger import AuditLoggingMiddleware
from src.data_warehouse.datalake_manager import DataLakeManager
from src.ml_pipeline.slm_search_engine import SLMSearchEngine
from src.signal_processing import WaveletDenoiser, ButterworthFilter, AdaptiveSensorFusion, BMOAnalyzer
from src.signal_processing.noise_separation import BMODenoiser
from src.phantom_data import PhantomDataEngine, HRVAnalyzer
from src.ontology import ClinicalOntologyMapper, BayesianDiagnosticNetwork, OntologyEnrichedReport


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Saúde Responsiva — Plataforma Biomédica API",
    description="Servidor de telemetria biométrica, processamento de sinais e dados fantasmas em tempo real.",
    version="2.1.0",
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
)

# Registra Middlewares em ordem de execução
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitingMiddleware)
app.add_middleware(AuditLoggingMiddleware)

# CORS restrito (nunca * com credentials). Configure CORS_ORIGINS em produção.
_cors_origins = get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["https://healthtech-responsive-5794833455.us-central1.run.app"],
    allow_credentials=cors_allow_credentials(),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*", "X-API-Key", "X-Request-ID"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", "unknown")
    logger.error(f"Exceção não tratada [Request-ID: {req_id}]: {exc}", exc_info=not is_production())
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Ocorreu um erro interno no processamento da solicitação.",
            "error_code": "INTERNAL_SERVER_ERROR",
            "request_id": req_id,
        },
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
# Inicialização lazy do SLMSearchEngine para não travar a inicialização do container no Cloud Run
slm_engine_instance: Optional[SLMSearchEngine] = None

def get_slm_engine() -> SLMSearchEngine:
    global slm_engine_instance
    if slm_engine_instance is None:
        logger.info("Inicializando SLMSearchEngine (lazy load)...")
        slm_engine_instance = SLMSearchEngine()
    return slm_engine_instance

ontology_mapper = ClinicalOntologyMapper()
bayes_net = BayesianDiagnosticNetwork()
report_generator = OntologyEnrichedReport(ontology_mapper, bayes_net)
dl_manager = DataLakeManager()

# Inicializar clientes do GCP (BigQuery e Vertex Endpoint)
bq_client = None
vertex_detector = None

if gcp_project:
    logger.info(f"Conectando ao Google BigQuery no projeto '{gcp_project}'...")
    try:
        from google.cloud import bigquery
        from src.utils.gcp_auth import get_gcp_credentials
        creds, proj = get_gcp_credentials(gcp_project)
        bq_client = bigquery.Client(project=proj or gcp_project, credentials=creds)
    except Exception as e:
        logger.error(f"Erro ao instanciar cliente do BigQuery: {e}")
        
    if vertex_endpoint and "placeholder" not in str(vertex_endpoint):
        logger.info(f"Conectando ao Vertex AI Endpoint '{vertex_endpoint}'...")
        try:
            from src.ml_pipeline.online_inference import VertexOnlineDetector

            vertex_detector = VertexOnlineDetector(
                project=gcp_project,
                location=gcp_location,
                endpoint_id=vertex_endpoint,
            )
        except Exception as e:
            logger.error(f"Erro ao instanciar detector online do Vertex: {e}")
            vertex_detector = None

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
    return {"status": "healthy", "service": "Saúde Responsiva API"}


@app.get("/api/status")
def get_status(_api_key: str = Depends(require_scope("admin"))):
    """Retorna o status atual dos motores do sistema (requer escopo 'admin')."""
    df_lake = dl_manager.load_latest_knowledge()
    slm = get_slm_engine()
    return {
        "status": "online",
        "slm_loaded": slm.encoder is not None,
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
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Busca literatura nas teses da USP via SLM (RAG)."""
    if not search.query:
        raise HTTPException(status_code=400, detail="A consulta (query) não pode estar vazia.")
    
    try:
        results = get_slm_engine().search_medical_knowledge(search.query, n_results=search.n_results)
        
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
        raise HTTPException(status_code=500, detail="Erro ao realizar busca semântica na literatura médica.")


@app.post("/api/v1/admin/reindex")
@app.post("/api/reindex")
def reindex_data_lake(_api_key: str = Depends(require_scope("admin"))):
    """Re-indexa o Data Lake no banco vetorial ChromaDB (requer escopo 'admin')."""
    try:
        get_slm_engine().index_datalake(dl_manager)
        return {"status": "success", "message": "Data lake reindexado com sucesso."}
    except Exception as e:
        logger.error(f"Erro ao reindexar data lake: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao reindexar Data Lake.")


class BMOAnalysisRequest(BaseModel):
    signal: list[float]
    scales: Optional[list[int]] = None


class BMODenoiseRequest(BaseModel):
    signal: list[float]
    window_size: int = 8
    alpha: float = 0.5


class BMOHRVRequest(BaseModel):
    rr_intervals: list[float]


@app.post("/api/v1/signal/bmo-analysis")
def analyze_bmo(
    req: BMOAnalysisRequest,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Análise de Espaço de Oscilação Média Limitada (BMO) e VMO para sinais fisiológicos."""
    if not req.signal or len(req.signal) < 4:
        raise HTTPException(status_code=400, detail="Sinal deve conter pelo menos 4 amostras.")
    
    analyzer = BMOAnalyzer(default_scales=req.scales)
    profile = analyzer.multiscale_bmo_profile(np.array(req.signal), scales=req.scales)
    return profile


@app.post("/api/v1/signal/bmo-denoise")
def denoise_bmo(
    req: BMODenoiseRequest,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """Denoising 1D adaptativo com preservação de bordas sem efeito escada (staircasing)."""
    if not req.signal:
        raise HTTPException(status_code=400, detail="Sinal de entrada não pode ser vazio.")
    
    denoiser = BMODenoiser(window_size=req.window_size, alpha=req.alpha)
    filtered = denoiser.denoise(np.array(req.signal))
    return {
        "filtered_signal": filtered.tolist(),
        "original_len": len(req.signal),
        "window_size": req.window_size,
        "alpha": req.alpha,
    }


@app.post("/api/v1/hrv/bmo-metrics")
def bmo_hrv_metrics(
    req: BMOHRVRequest,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Métricas de HRV no domínio BMO para análise da variabilidade R-R."""
    if not req.rr_intervals or len(req.rr_intervals) < 4:
        raise HTTPException(status_code=400, detail="Sequência R-R deve conter pelo menos 4 intervalos.")
    
    hrv = HRVAnalyzer()
    metrics = hrv.compute_bmo_domain(np.array(req.rr_intervals))
    return metrics


# =====================================================================
# INGESTÃO DE TELEMETRIA E MONITORAMENTO DE WEARABLES DE PULSO
# =====================================================================

patient_engines: Dict[str, PhantomDataEngine] = {}
patient_history: Dict[str, list[dict]] = {}


class WearableTelemetryRequest(BaseModel):
    model_config = {"extra": "allow"}

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device_id: Optional[str] = Field("wrist_wearable", max_length=64)
    timestamp: Optional[str] = Field(None, max_length=64)
    heart_rate: float = Field(..., ge=20.0, le=250.0)
    hrv_rmssd: Optional[float] = Field(40.0, ge=0.0, le=300.0)
    skin_temp: Optional[float] = Field(33.0, ge=25.0, le=45.0)
    spo2: Optional[float] = Field(98.0, ge=50.0, le=100.0)
    activity_level: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    ppg_signal: Optional[list[float]] = None
    filter_type: Optional[str] = Field("BMO", max_length=32)
    # Opcionais HBand / matriz de alertas
    blood_pressure_sys: Optional[float] = Field(None, ge=50.0, le=300.0)
    blood_pressure_dia: Optional[float] = Field(None, ge=20.0, le=200.0)
    glucose_mgdl: Optional[float] = Field(None, ge=20.0, le=1000.0)
    body_temp_c: Optional[float] = Field(None, ge=30.0, le=45.0)
    steps_drop_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    sleep_worsen_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    hr_baseline_rise: Optional[float] = Field(None, ge=-80.0, le=120.0)
    spo2_drop_points: Optional[float] = Field(None, ge=0.0, le=50.0)
    pas_rise_mmhg: Optional[float] = Field(None, ge=0.0, le=150.0)
    pad_rise_mmhg: Optional[float] = Field(None, ge=0.0, le=100.0)
    pas_drop_mmhg: Optional[float] = Field(None, ge=0.0, le=150.0)
    glucose_rise_mgdl: Optional[float] = Field(None, ge=0.0, le=800.0)
    glucose_drop_mgdl: Optional[float] = Field(None, ge=0.0, le=800.0)
    temp_rise_c: Optional[float] = Field(None, ge=0.0, le=8.0)
    temp_drop_c: Optional[float] = Field(None, ge=0.0, le=8.0)
    at_rest: Optional[bool] = None
    fasting_or_preprandial: Optional[bool] = None
    consecutive_count: Optional[int] = Field(None, ge=1, le=48)
    sleep_hours: Optional[float] = Field(None, ge=0.0, le=24.0)
    steps_drop_consecutive_days: Optional[int] = Field(None, ge=0, le=30)
    poor_sleep_nights: Optional[int] = Field(None, ge=0, le=30)
    hourly_steps_available: Optional[bool] = None
    abrupt_steps_stop: Optional[bool] = None
    inactivity_rest_of_active_period: Optional[bool] = None
    consciousness_altered: Optional[bool] = None
    ingest_source: Optional[str] = Field("companion_manual", max_length=32)

    @field_validator("ingest_source")
    @classmethod
    def validate_ingest_source(cls, v: Optional[str]) -> Optional[str]:
        allowed = {"companion_manual", "ble_sim", "ble_hband", "http"}
        if v is None or v == "":
            return "companion_manual"
        if v not in allowed:
            raise ValueError(
                "ingest_source inválido. Valores aceitos: "
                + ", ".join(sorted(allowed))
            )
        return v

    @field_validator("filter_type")
    @classmethod
    def validate_filter_type(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {"BMO", "Wavelet", "Butterworth", "Raw", "Adaptive"}:
            raise ValueError("filter_type inválido. Valores aceitos: BMO, Wavelet, Butterworth, Raw, Adaptive.")
        return v


class WearableBatchIngestRequest(BaseModel):
    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    readings: list[WearableTelemetryRequest]


def get_patient_engine(patient_id: str, use_ukf: bool = False) -> PhantomDataEngine:
    if patient_id not in patient_engines:
        patient_engines[patient_id] = PhantomDataEngine(dt=1.0, use_ukf=use_ukf)
    return patient_engines[patient_id]


@app.post("/api/v1/wearables/ingest")
def ingest_wearable_reading(
    req: WearableTelemetryRequest,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """
    Endpoint principal para recepção de telemetria enviada por wearables no pulso dos pacientes
    (ex: Smartwatches, Smartbands, sensores PPG de pulso). Requer escopo 'wearables:write'.
    
    Aplica denoising (BMO/Wavelet), inferência de dados fantasmas (Pressão Arterial, Glicose, SpO2, Tônus Vagal),
    detecção de anomalias em tempo real e geração de código diagnóstico de ontologia médica (CID-10/SNOMED CT).
    """
    if req.heart_rate <= 0 or req.heart_rate > 300:
        raise HTTPException(status_code=400, detail="Frequência cardíaca fora dos limites fisiológicos válidos (1-300 BPM).")

    # 1. Denoising do Sinal Heart Rate / PPG se fornecido
    bpm_clean = req.heart_rate
    bmo_metrics = {}
    if req.ppg_signal and len(req.ppg_signal) >= 4:
        analyzer = BMOAnalyzer()
        bmo_metrics = analyzer.multiscale_bmo_profile(np.array(req.ppg_signal))
        if req.filter_type == "BMO":
            denoiser = BMODenoiser(window_size=8, alpha=0.5)
            filtered_ppg = denoiser.denoise(np.array(req.ppg_signal))
            bpm_clean = float(np.mean(filtered_ppg)) if np.mean(filtered_ppg) > 30 else req.heart_rate

    # 2. Inferência de Dados Fantasmas via Filtro de Kalman por Paciente
    engine = get_patient_engine(req.patient_id, use_ukf=sim_config.use_ukf)
    wearable_data = {
        'heart_rate': bpm_clean,
        'hrv_rmssd': req.hrv_rmssd or 40.0,
        'skin_temp': req.skin_temp or 33.0,
        'activity_level': req.activity_level or 0.0
    }
    phantom_res = engine.process_reading(wearable_data)
    states = phantom_res['states']

    # 3. Detecção de Anomalias Fisiológicas
    anomaly_res = {"alerta": False, "score": 0.0, "modo": "Deteção Local"}
    if vertex_detector:
        try:
            anomaly_res = vertex_detector.processar_nova_leitura(bpm_clean)
        except Exception as e:
            logger.error(f"Erro no Vertex AI: {e}")
    else:
        is_anomalia = bpm_clean > 100 or bpm_clean < 40 or (req.spo2 is not None and req.spo2 < 92)
        anomaly_res = {
            "alerta": bool(is_anomalia),
            "score": 0.95 if is_anomalia else 0.05,
            "modo": "Deteção Local BMO"
        }

    # 4. Diagnóstico Ontológico e Rede Bayesiana
    current_phantom = {k: v['estimate'] for k, v in states.items()}
    hrv_metrics = {'rmssd': req.hrv_rmssd or 40.0}
    
    hypotheses = bayes_net.generate_diagnostic_hypotheses(
        phantom_data=current_phantom,
        hrv_metrics=hrv_metrics,
        anomaly_score=anomaly_res,
        top_k=3
    )

    report = report_generator.generate_patient_report(
        patient_id=req.patient_id,
        phantom_data=current_phantom,
        hrv_metrics=hrv_metrics,
        anomaly_score=anomaly_res
    )

    ts = req.timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 5. Matriz de alertas clínicos (regras + ML de falsos positivos)
    phantom_for_alerts = {
        name: {
            "estimate": float(details["estimate"]),
            "ci_lower": float(details["ci_lower"]),
            "ci_upper": float(details["ci_upper"]),
            "reliable": details["reliable"],
        }
        for name, details in states.items()
    }
    # Extensões HBand / campos opcionais da matriz de alertas
    extra = getattr(req, "model_extra", None) or {}
    hband_ext = {}
    if isinstance(extra, dict):
        hband_ext = dict(extra.get("_hband") or extra.get("hband") or {})
    for key in (
        "blood_pressure_sys",
        "blood_pressure_dia",
        "glucose_mgdl",
        "body_temp_c",
        "steps_drop_pct",
        "sleep_worsen_pct",
        "hr_baseline_rise",
        "spo2_drop_points",
        "pas_rise_mmhg",
        "pad_rise_mmhg",
        "pas_drop_mmhg",
        "glucose_rise_mgdl",
        "glucose_drop_mgdl",
        "temp_rise_c",
        "temp_drop_c",
        "at_rest",
        "fasting_or_preprandial",
        "consecutive_count",
        "sleep_hours",
        "steps_drop_consecutive_days",
        "poor_sleep_nights",
        "hourly_steps_available",
        "abrupt_steps_stop",
        "inactivity_rest_of_active_period",
        "consciousness_altered",
        "ingest_source",
    ):
        val = getattr(req, key, None)
        if val is not None:
            hband_ext[key] = val
    try:
        from src.clinical_intelligence.alert_ingest import (
            assess_ingest_alerts,
            merge_anomaly_with_alerts,
        )

        clinical_alerts = assess_ingest_alerts(
            heart_rate=bpm_clean,
            spo2=req.spo2,
            skin_temp=req.body_temp_c if req.body_temp_c is not None else req.skin_temp,
            hrv_rmssd=req.hrv_rmssd,
            activity_level=req.activity_level,
            phantom=phantom_for_alerts,
            hband_ext=hband_ext,
            raw_telemetry={
                "heart_rate_bpm": req.heart_rate,
                "spo2_percent": req.spo2,
                "skin_temp_celsius": req.skin_temp,
                "blood_pressure_sys": req.blood_pressure_sys,
                "blood_pressure_dia": req.blood_pressure_dia,
                "glucose_mgdl": req.glucose_mgdl,
            },
        )
        anomaly_res = merge_anomaly_with_alerts(anomaly_res, clinical_alerts)
    except Exception as alert_err:
        logger.warning("Matriz de alertas indisponível no ingest: %s", alert_err)
        clinical_alerts = {
            "is_true_alert": False,
            "is_false_positive": False,
            "severity": "none",
            "decision": "unavailable",
            "error": str(alert_err),
        }

    ingest_source = req.ingest_source or "companion_manual"
    processed_frame = {
        "patient_id": req.patient_id,
        "device_id": req.device_id,
        "timestamp": ts,
        "ingest_source": ingest_source,
        "raw_telemetry": {
            "heart_rate_bpm": req.heart_rate,
            "hrv_rmssd_ms": req.hrv_rmssd,
            "skin_temp_celsius": req.skin_temp,
            "spo2_percent": req.spo2,
            "activity_level": req.activity_level,
            "ingest_source": ingest_source,
        },
        "cleaned_telemetry": {
            "heart_rate_clean": round(bpm_clean, 2),
            "filter_applied": req.filter_type,
            "bmo_metrics": bmo_metrics
        },
        "phantom_data": {
            name: {
                "estimate": round(details['estimate'], 2),
                "ci_lower": round(details['ci_lower'], 2),
                "ci_upper": round(details['ci_upper'], 2),
                "reliable": details['reliable']
            } for name, details in states.items()
        },
        "anomaly_detection": anomaly_res,
        "clinical_alerts": clinical_alerts,
        "diagnostic_hypotheses": [
            {
                "category": h['category'],
                "probability": round(h['posterior_probability'], 4),
                "severity": h['severity']
            } for h in hypotheses
        ],
        "clinical_codes": report['clinical_codes']
    }

    if req.patient_id not in patient_history:
        patient_history[req.patient_id] = []
    patient_history[req.patient_id].append(processed_frame)
    if len(patient_history[req.patient_id]) > 100:
        patient_history[req.patient_id].pop(0)

    if bq_client:
        try:
            row_to_insert = [{
                "patient_id": req.patient_id,
                "timestamp": ts,
                "heart_rate_bpm": int(round(bpm_clean)),
                "sensors_used": [req.device_id],
                "is_anomaly": bool(anomaly_res["alerta"])
            }]
            loop = asyncio.get_event_loop()
            loop.run_in_executor(
                None, 
                safe_insert_bq, 
                bq_client,
                f"{gcp_project}.healthtech_datalake.wearable_biometrics", 
                row_to_insert
            )
        except Exception as bq_err:
            logger.error(f"Erro ao agendar gravação no BigQuery: {bq_err}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast_json({"type": "patient_ingest", "data": processed_frame}))
    except RuntimeError:
        pass

    return processed_frame


@app.post("/api/v1/wearables/batch-ingest")
def batch_ingest_wearables(
    batch: WearableBatchIngestRequest,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """
    Ingestão em lote para sincronização periódica de leituras acumuladas por wearables no pulso. Requer escopo 'wearables:write'.
    """
    results = []
    for reading in batch.readings:
        reading.patient_id = batch.patient_id
        res = ingest_wearable_reading(reading, _api_key=_api_key)
        results.append(res)
    return {
        "status": "success",
        "patient_id": batch.patient_id,
        "processed_count": len(results),
        "latest_result": results[-1] if results else None
    }


@app.get("/api/v1/wearables/patient/{patient_id}/latest")
def get_latest_patient_telemetry(
    patient_id: str,
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """
    Retorna o último estado fisiológico e dados fantasmas inferidos para o paciente especificado. Requer escopo 'wearables:read' e autorização sobre o paciente.
    """
    history = patient_history.get(patient_id)
    if not history:
        raise HTTPException(status_code=404, detail=f"Nenhum dado encontrado para o paciente '{patient_id}'.")
    return history[-1]


@app.get("/api/v1/wearables/patient/{patient_id}/history")
def get_patient_telemetry_history(
    patient_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """
    Retorna o histórico recente de leituras do paciente (Proteção contra IDOR).
    """
    history = patient_history.get(patient_id)
    if not history:
        raise HTTPException(status_code=404, detail=f"Nenhum histórico encontrado para o paciente '{patient_id}'.")
    return {"patient_id": patient_id, "total_records": len(history), "records": history[-limit:]}


_optional_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


def _connections_public_view(full: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.connection_status import public_connection_view
    except ImportError:
        from saude_responsiva_secure.app.services.connection_status import (  # type: ignore
            public_connection_view,
        )
    return public_connection_view(full)


def _build_connections_payload(
    online_threshold_sec: int,
    stale_threshold_sec: int,
) -> Dict[str, Any]:
    try:
        from app.services.connection_status import build_connection_status
    except ImportError:
        from saude_responsiva_secure.app.services.connection_status import (  # type: ignore
            build_connection_status,
        )
    return build_connection_status(
        patient_history,
        online_threshold_sec=online_threshold_sec,
        stale_threshold_sec=stale_threshold_sec,
    )


@app.get("/api/v1/connections/status")
def get_mobile_device_connection_status(
    online_threshold_sec: int = Query(default=30, ge=5, le=600),
    stale_threshold_sec: int = Query(default=300, ge=30, le=3600),
    x_api_key: Optional[str] = Security(_optional_api_key),
):
    """
    Status das conexões: app companion Android e device (via app / BLE futuro).
    Sem chave → visão pública; com wearables:read → sessões completas.
    """
    full = _build_connections_payload(online_threshold_sec, stale_threshold_sec)
    try:
        from app.security.auth import get_key_scopes
        from app.config import get_settings as _gs
    except ImportError:
        from saude_responsiva_secure.app.security.auth import get_key_scopes  # type: ignore
        from saude_responsiva_secure.app.config import get_settings as _gs  # type: ignore

    settings = _gs()
    scopes = get_key_scopes(x_api_key, settings)
    if "wearables:read" in scopes or "admin" in scopes or settings.is_auth_disabled:
        full["public"] = False
        return full
    return _connections_public_view(full)


@app.get("/api/v1/connections/public")
def get_mobile_device_connection_status_public(
    online_threshold_sec: int = Query(default=30, ge=5, le=600),
    stale_threshold_sec: int = Query(default=300, ge=30, le=3600),
):
    """Visão pública das conexões mobile/device (sem API key)."""
    full = _build_connections_payload(online_threshold_sec, stale_threshold_sec)
    return _connections_public_view(full)


# ---------------------------------------------------------------------------
# Bridge: monólito full (dashboard) → secure-api (ingest real do app mobile)
# O companion grava na secure-api; o full tem memória separada. Este proxy
# same-origin evita CORS e permite o dashboard mostrar telemetria real.
# ---------------------------------------------------------------------------
# Vazio = só memória local. Produção injeta via deploy_to_gcp.sh.
SECURE_API_BASE_URL = os.getenv("SECURE_API_BASE_URL", "").rstrip("/")


def _secure_read_headers() -> Dict[str, str]:
    key = (
        os.getenv("READ_API_KEY")
        or os.getenv("API_KEY")
        or os.getenv("ADMIN_API_KEY")
        or ""
    ).strip()
    headers = {"Accept": "application/json"}
    if key:
        headers["X-API-Key"] = key
    return headers


@app.get("/api/v1/mobile/bridge/snapshot")
def mobile_bridge_snapshot(
    patient_id: str = Query(default="PAT-HBAND-001", min_length=3, max_length=64),
    online_threshold_sec: int = Query(default=30, ge=5, le=600),
):
    """
    Snapshot unificado para o dashboard: status de conexão + latest do app mobile.

    Busca na secure-api (onde o companion faz ingest). Sem autenticação no
    dashboard (visão operacional); a secure-api é autenticada server-side.
    """
    import urllib.error
    import urllib.request

    out: Dict[str, Any] = {
        "bridge": True,
        "secure_base_url": SECURE_API_BASE_URL or None,
        "patient_id": patient_id,
        "connections": None,
        "latest": None,
        "errors": [],
    }
    headers = _secure_read_headers()

    def _get_json(path: str, with_auth: bool = False) -> Any:
        req = urllib.request.Request(
            f"{SECURE_API_BASE_URL}{path}",
            headers=headers if with_auth else {"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    if not SECURE_API_BASE_URL:
        out["errors"].append("SECURE_API_BASE_URL unset — using local memory")
        full = _build_connections_payload(online_threshold_sec, 300)
        out["connections"] = _connections_public_view(full)
        out["connections"]["bridge_fallback"] = "local_memory"
    else:
        try:
            out["connections"] = _get_json(
                f"/api/v1/connections/public?online_threshold_sec={online_threshold_sec}",
                with_auth=False,
            )
        except Exception as exc:
            out["errors"].append(f"connections: {exc}")
            full = _build_connections_payload(online_threshold_sec, 300)
            out["connections"] = _connections_public_view(full)
            out["connections"]["bridge_fallback"] = "local_memory"

    if SECURE_API_BASE_URL:
        try:
            out["latest"] = _get_json(
                f"/api/v1/wearables/patient/{patient_id}/latest",
                with_auth=True,
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            out["errors"].append(f"latest HTTP {exc.code}: {body}")
        except Exception as exc:
            out["errors"].append(f"latest: {exc}")

        if out.get("connections") and isinstance(out["connections"], dict):
            out["connections"]["source"] = "secure-cloud-bridge"
            for sess in out["connections"].get("sessions") or []:
                sess["source"] = sess.get("source") or "secure-cloud-bridge"
    else:
        local = patient_history.get(patient_id) or []
        out["latest"] = local[-1] if local else None
        if out.get("connections") and isinstance(out["connections"], dict):
            out["connections"]["source"] = "local-memory"

    return out


@app.delete("/api/v1/patient/{patient_id}/anonymize")
def anonymize_patient_telemetry(
    patient_id: str,
    _api_key: str = Depends(require_scope("admin")),
):
    """
    Endpoint de conformidade LGPD: Purga e anonimiza todo o histórico de telemetria do paciente.
    Requer escopo 'admin'.
    """
    removed_history = patient_history.pop(patient_id, None)
    removed_engine = patient_engines.pop(patient_id, None)
    
    if removed_history is None and removed_engine is None:
        raise HTTPException(status_code=404, detail=f"Nenhum dado ativo registrado para o paciente '{patient_id}'.")
    
    return {
        "status": "success",
        "message": f"Dados do paciente '{patient_id}' purgados com sucesso para conformidade LGPD.",
        "patient_id": patient_id
    }




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
                pass


manager = ConnectionManager()


def safe_insert_bq(client, table_id, row):
    try:
        client.insert_rows_json(table_id, row)
    except Exception as e:
        logger.debug("Falha na gravação BigQuery (não bloqueante): %s", e)


async def telemetry_stream_loop():
    """
    Loop assíncrono em segundo plano para geração de sinais e inferência de dados fantasmas.
    Transmite os dados via WebSocket para todos os clientes conectados.
    """
    # Instanciar filtros
    wavelet_denoiser = WaveletDenoiser(wavelet='db4', level=2)
    butter_filter = ButterworthFilter(fs=1.0)
    bmo_denoiser = BMODenoiser(window_size=8, alpha=0.5)
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
        elif sim_config.filter_type == "BMO" and len(raw_bpm_buffer) >= 4:
            win = np.array(raw_bpm_buffer[-8:])
            denoised = bmo_denoiser.denoise(win)
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
                loop.run_in_executor(
                    None, 
                    safe_insert_bq, 
                    bq_client,
                    f"{gcp_project}.healthtech_datalake.wearable_biometrics", 
                    row_to_insert
                )
            except Exception as bq_err:
                logger.error(f"Erro ao agendar gravação no BigQuery: {bq_err}")

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
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, get_slm_engine)
    logger.info(
        "Serviço de streaming de telemetria inicializado (CORS=%s).",
        get_cors_origins(),
    )


@app.websocket("/ws/telemetry")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: Optional[str] = Query(default=None),
):
    """
    Canal WebSocket de telemetria do dashboard.

    - Sem chave: modo *viewer* (recebe stream/config; não controla simulação).
      Necessário para o dashboard web em produção (browser não envia X-API-Key no WS).
    - Com chave válida: controle completo (start/stop/filtros).
    - Chave inválida (não vazia): 4401.
    """
    header_key = websocket.headers.get("x-api-key")
    provided = (api_key or header_key or "").strip()
    can_control = verify_api_key(provided) if provided else False
    if provided and not can_control:
        await websocket.close(code=4401, reason="API key inválida")
        return

    await manager.connect(websocket)
    try:
        # Enviar estado de configuração atual
        await websocket.send_json({
            "type": "config",
            "filter_type": sim_config.filter_type,
            "use_ukf": sim_config.use_ukf,
            "is_running": sim_config.is_running,
            "auth_mode": "control" if can_control else "viewer",
        })

        while True:
            # Aguarda comandos do cliente
            data_str = await websocket.receive_text()
            data = json.loads(data_str)
            action = data.get("action")

            if not can_control and action in {"start", "stop", "set_filter", "set_kalman"}:
                await websocket.send_json({
                    "type": "error",
                    "error_code": "WS_AUTH_REQUIRED",
                    "detail": (
                        "Modo viewer: informe ?api_key= na URL do dashboard "
                        "para controlar a simulação."
                    ),
                })
                continue

            if action == "start":
                sim_config.is_running = True
                logger.info("Simulação iniciada via comando WebSocket.")
            elif action == "stop":
                sim_config.is_running = False
                logger.info("Simulação pausada via comando WebSocket.")
            elif action == "set_filter":
                filter_val = data.get("value")
                if filter_val in ["Sem Filtro", "Wavelet", "Butterworth", "BMO"]:
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



def build_monolith_app():
    """Entry point para a factory secure (APP_MODE=full)."""
    return app


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
