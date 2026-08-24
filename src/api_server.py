"""
api_server.py — Servidor API FastAPI e WebSocket Streaming

Este script fornece o backend web para o dashboard da plataforma HealthTech.
Ele gerencia a conexão WebSocket para transmitir leituras de wearables e dados fantasmas
inferidos em tempo real para o navegador, além de endpoints REST para busca semântica
RAG (SLM), simulação biofísica Windkessel 4-Elementos, Teoria dos Jogos e Consenso Multi-Agente.
"""

from __future__ import annotations

import asyncio
import json
import logging
import datetime
import os
import sys
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from src.security.auth import (
    cors_allow_credentials,
    get_cors_origins,
    is_production,
    require_patient_access,
    require_scope,
)
from src.security.audit_logger import AuditLoggingMiddleware
from src.security.rate_limiter import RateLimitingMiddleware
from src.security.security_headers import SecurityHeadersMiddleware

# Garantir imports corretos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_warehouse.datalake_manager import DataLakeManager
from src.ml_pipeline.slm_search_engine import SLMSearchEngine
from src.signal_processing import WaveletDenoiser, ButterworthFilter, AdaptiveSensorFusion
from src.phantom_data import PhantomDataEngine, HRVAnalyzer
from src.ontology import ClinicalOntologyMapper, BayesianDiagnosticNetwork, OntologyEnrichedReport
from src.hemodynamics.windkessel import Windkessel4ESimulator, Windkessel4EParams, BaroreflexParams
from src.clinical_intelligence.game_theory import TriageGameEngine
from src.clinical_intelligence.agents import ClinicalConsensusCoordinator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HealthTech Advanced API Server",
    description="Servidor de telemetria biométrica, processamento de sinais, biofísica hemodinâmica e inteligência clínica.",
    version="3.1.0",
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitingMiddleware)
app.add_middleware(AuditLoggingMiddleware)

# CORS restrito por ambiente (nunca "*" com credenciais). Configure CORS_ORIGINS em produção.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=cors_allow_credentials(),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*", "X-API-Key", "X-Request-ID"],
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
slm_engine = SLMSearchEngine() if not os.getenv("TESTING") else None

ontology_mapper = ClinicalOntologyMapper()
bayes_net = BayesianDiagnosticNetwork()
report_generator = OntologyEnrichedReport(ontology_mapper, bayes_net)
consensus_coordinator = ClinicalConsensusCoordinator()

# Cache de motores de dados fantasmas e histórico por paciente
patient_engines: Dict[str, PhantomDataEngine] = {}
patient_telemetry_history: Dict[str, List[Dict[str, Any]]] = {}

def get_patient_engine(patient_id: str, use_ukf: bool = False) -> PhantomDataEngine:
    if patient_id not in patient_engines:
        patient_engines[patient_id] = PhantomDataEngine(dt=sim_config.dt, use_ukf=use_ukf)
    return patient_engines[patient_id]

triage_engine = TriageGameEngine()

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
            from src.ml_pipeline.online_inference import VertexOnlineDetector

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
        self.sim_wk4_live: bool = True        # Acopla simulador WK4 em tempo real

sim_config = SimConfig()


# =====================================================================
# PYDANTIC SCHEMAS PARA OS NOVOS ENDPOINTS REST
# =====================================================================

class SearchQuery(BaseModel):
    query: str
    n_results: int = 3


class WearableTelemetryRequest(BaseModel):
    model_config = {"extra": "allow"}

    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device_id: str = Field(default="HBAND-VE30", min_length=2, max_length=128)
    timestamp: Optional[str] = None
    heart_rate: float = Field(..., ge=1.0, le=300.0)
    spo2: Optional[float] = Field(None, ge=50.0, le=100.0)
    skin_temp: Optional[float] = Field(None, ge=25.0, le=45.0)
    blood_pressure_sys: Optional[float] = Field(None, ge=50.0, le=300.0)
    blood_pressure_dia: Optional[float] = Field(None, ge=30.0, le=200.0)
    hrv_rmssd: Optional[float] = Field(None, ge=0.0, le=300.0)
    activity_level: Optional[float] = Field(0.0, ge=0.0, le=100.0)
    steps: Optional[int] = Field(None, ge=0)
    calories: Optional[float] = Field(None, ge=0.0)
    wear_status: Optional[bool] = True
    ppg_signal: Optional[List[float]] = None
    filter_type: Optional[str] = Field("BMO", max_length=32)
    device: Optional[Dict[str, Any]] = None

    @field_validator("filter_type")
    @classmethod
    def validate_filter_type(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {"BMO", "Wavelet", "Butterworth", "Raw", "Adaptive"}:
            raise ValueError("filter_type inválido. Valores aceitos: BMO, Wavelet, Butterworth, Raw, Adaptive.")
        return v


class WearableBatchItem(BaseModel):
    timestamp: str
    heart_rate: Optional[float] = None
    spo2: Optional[float] = None
    blood_pressure_sys: Optional[float] = None
    blood_pressure_dia: Optional[float] = None
    hrv: Optional[float] = None
    step_count: Optional[int] = None
    cal_value: Optional[float] = None


class WearableBatchIngestRequest(BaseModel):
    patient_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$")
    device_id: str = Field(default="HBAND-VE30", min_length=2, max_length=128)
    readings: List[Dict[str, Any]]


class WindkesselSimRequest(BaseModel):
    Rp: float = Field(1.0, description="Resistência vascular periférica (mmHg*s/mL)")
    C: float = Field(1.2, description="Complacência arterial total (mL/mmHg)")
    Zc: float = Field(0.05, description="Impedância característica da raiz da aorta (mmHg*s/mL)")
    L: float = Field(0.005, description="Inertância da coluna de sangue (mmHg*s^2/mL)")
    hr: float = Field(75.0, description="Frequência cardíaca (bpm)")
    sv: float = Field(70.0, description="Volume sistólico ejetado por batimento (mL)")
    duration_s: float = Field(3.0, description="Duração temporal da simulação (segundos)")
    with_baroreflex: bool = Field(True, description="Ativar feedback autonômico do barorreflexo")


class TriageSolveRequest(BaseModel):
    icu_capacity: int = Field(10, description="Capacidade total de leitos de UTI")
    ward_capacity: int = Field(40, description="Capacidade de leitos de enfermaria")
    icu_demand: int = Field(14, description="Demanda de pacientes com indicação de UTI")
    ward_demand: int = Field(35, description="Demanda de leitos de enfermaria")
    high_risk_fraction: float = Field(0.4, description="Fração de pacientes em estado crítico (0 a 1)")


class MultiAgentConsensusRequest(BaseModel):
    patient_id: str = Field("PATIENT-001", description="Identificador do paciente")
    vitals: Dict[str, float] = Field(..., description="Dicionário com frequência cardíaca, SpO2, etc.")
    phantom_data: Optional[Dict[str, Any]] = Field(None, description="Estimativas dos estados latentes")
    hrv_metrics: Optional[Dict[str, float]] = Field(None, description="Métricas de variabilidade cardíaca")
    hemodynamics: Optional[Dict[str, Any]] = Field(None, description="Métricas hemodinâmicas adicionais")


# =====================================================================
# ENDPOINTS REST
# =====================================================================

from src.ops.billing_routes import register_billing_routes

register_billing_routes(app)


@app.get("/api/health")
def health_probe():
    """Probe público para orquestradores e healthchecks."""
    return {"status": "healthy", "service": "HealthTech Advanced API Server"}


@app.get("/api/status")
def get_status(_api_key: str = Depends(require_scope("admin"))):
    """Retorna o status atual dos motores do sistema."""
    df_lake = dl_manager.load_latest_knowledge() if not os.getenv("TESTING") else []
    return {
        "status": "online",
        "slm_loaded": (slm_engine is not None and slm_engine.encoder is not None) if slm_engine else True,
        "ontology_loaded": len(ontology_mapper.ontology) > 0,
        "data_lake_size": len(df_lake),
        "config": {
            "simulation_running": sim_config.is_running,
            "filter_type": sim_config.filter_type,
            "use_ukf": sim_config.use_ukf,
            "sim_wk4_live": getattr(sim_config, "sim_wk4_live", True),
        }
    }


@app.post("/api/v1/admin/reindex")
@app.post("/api/reindex")
def reindex_theses(_api_key: str = Depends(require_scope("admin"))):
    """Reindexa o acervo de teses do Data Lake."""
    if slm_engine is None:
        return {"status": "warning", "message": "SLM indisponível no modo de teste."}
    df_theses = dl_manager.load_theses_raw() if hasattr(dl_manager, "load_theses_raw") else []
    if isinstance(df_theses, list):
        return {"status": "success", "message": "Data lake reindexado com sucesso."}
    count = slm_engine.index_theses(df_theses)
    return {"status": "success", "message": f"{count} teses indexadas no ChromaDB."}


@app.post("/api/search")
def search_literature(search: SearchQuery):
    """Busca literatura nas teses da USP via SLM (RAG)."""
    if not search.query:
        raise HTTPException(status_code=400, detail="Query de busca vazia.")
    
    results = slm_engine.search_theses(search.query, n_results=search.n_results)
    return {"results": results}


# =====================================================================
# ENDPOINTS DE INGESTÃO DE WEARABLES (VE30 / HBAND / VEEPOO)
# =====================================================================

@app.post("/api/v1/wearables/ingest")
def ingest_wearable_reading(
    req: WearableTelemetryRequest,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """
    Endpoint principal para recepção de telemetria contínua de smartwatches VE30.
    Executa: Denoising BMO/Wavelet, Inferência UKF de Dados Fantasmas, Detecção de Anomalias
    e Parecer Deliberativo do Conselho Clínico Multi-Agente (Dempster-Shafer).
    """
    if req.heart_rate <= 0 or req.heart_rate > 300:
        raise HTTPException(status_code=400, detail="Frequência cardíaca fora dos limites fisiológicos (1-300 BPM).")

    # 1. Denoising Fisiológico
    bpm_clean = req.heart_rate
    if req.ppg_signal and len(req.ppg_signal) >= 4:
        try:
            w_denoiser = WaveletDenoiser()
            clean_ppg = w_denoiser.denoise(np.array(req.ppg_signal))
            bpm_clean = float(np.mean(clean_ppg)) if 30.0 < np.mean(clean_ppg) < 220.0 else req.heart_rate
        except Exception:
            bpm_clean = req.heart_rate

    # 2. Inferência de Dados Fantasmas via UKF/EKF por Paciente
    engine = get_patient_engine(req.patient_id, use_ukf=sim_config.use_ukf)
    wearable_data = {
        'heart_rate': bpm_clean,
        'hrv_rmssd': req.hrv_rmssd or 42.0,
        'skin_temp': req.skin_temp or 33.2,
        'activity_level': req.activity_level or 0.0
    }
    phantom_res = engine.process_reading(wearable_data)
    phantom_states = phantom_res.get('states', phantom_res)

    # 3. Detecção de Anomalias Fisiológicas
    anomaly_res = {"alerta": False, "score": 0.0, "modo": "Simulação Local"}
    if vertex_detector:
        try:
            anomaly_res = vertex_detector.processar_nova_leitura(bpm_clean)
        except Exception as e:
            logger.error(f"Erro no Vertex AI: {e}")
    else:
        is_anomalia = bpm_clean > 105 or bpm_clean < 45 or (req.spo2 is not None and req.spo2 < 92)
        anomaly_res = {
            "alerta": bool(is_anomalia),
            "score": 0.95 if is_anomalia else 0.05,
            "modo": "Deteção Local"
        }

    # 4. Diagnóstico Ontológico e Rede Bayesiana
    current_phantom_vals = {k: v['estimate'] for k, v in phantom_states.items() if isinstance(v, dict) and 'estimate' in v}
    hrv_metrics = {'rmssd': req.hrv_rmssd or 42.0, 'sdnn': 50.0, 'pnn50': 20.0}

    hypotheses = bayes_net.generate_diagnostic_hypotheses(
        phantom_data=phantom_states,
        hrv_metrics=hrv_metrics,
        anomaly_score=anomaly_res,
        top_k=3
    )

    report = report_generator.generate_patient_report(
        patient_id=req.patient_id,
        phantom_data=phantom_states,
        hrv_metrics=hrv_metrics,
        anomaly_score=anomaly_res
    )

    # 5. Parecer do Conselho Clínico Multi-Agente (Dempster-Shafer)
    consensus_data = consensus_coordinator.reach_consensus(
        patient_id=req.patient_id,
        vitals={"heart_rate": bpm_clean, "spo2": req.spo2 or 98.0},
        phantom_data=phantom_states,
        hrv_metrics=hrv_metrics
    )

    ts = req.timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        from src.clinical_intelligence.alert_ingest import assess_ingest_alerts, merge_anomaly_with_alerts

        phantom_for_alerts = {
            name: {
                "estimate": float(details["estimate"]),
                "ci_lower": float(details.get("ci_lower", details["estimate"])),
                "ci_upper": float(details.get("ci_upper", details["estimate"])),
                "reliable": bool(details.get("reliable", True)),
            }
            for name, details in phantom_states.items()
            if isinstance(details, dict)
        }
        hband_ext = {
            key: value
            for key, value in {
                "blood_pressure_sys": req.blood_pressure_sys,
                "blood_pressure_dia": req.blood_pressure_dia,
                "glucose_mgdl": None,
                "body_temp_c": req.skin_temp,
                "steps_drop_pct": None,
                "sleep_worsen_pct": None,
            }.items()
            if value is not None
        }
        clinical_alerts = assess_ingest_alerts(
            heart_rate=bpm_clean,
            spo2=req.spo2,
            skin_temp=req.skin_temp,
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
            },
        )
        anomaly_res = merge_anomaly_with_alerts(anomaly_res, clinical_alerts)
    except Exception as alert_err:
        logger.warning("Matriz de alertas indisponível no ingest do servidor padrão: %s", alert_err)
        clinical_alerts = {
            "is_true_alert": False,
            "is_false_positive": False,
            "severity": "none",
            "decision": "unavailable",
            "error": str(alert_err),
        }

    response_payload = {
        "status": "success",
        "patient_id": req.patient_id,
        "device_id": req.device_id,
        "timestamp": ts,
        "raw_telemetry": {
            "heart_rate_bpm": req.heart_rate,
            "spo2_percent": req.spo2,
            "skin_temp_c": req.skin_temp,
            "blood_pressure_sys": req.blood_pressure_sys,
            "blood_pressure_dia": req.blood_pressure_dia,
            "hrv_rmssd_ms": req.hrv_rmssd,
            "steps": req.steps,
            "wear_status": req.wear_status,
        },
        "cleaned_telemetry": {
            "heart_rate_clean": round(float(bpm_clean), 2),
            "filter_applied": req.filter_type,
            "bmo_metrics": {},
        },
        "phantom_data": {
            "systolic_bp": phantom_states.get("systolic_bp", {}),
            "diastolic_bp": phantom_states.get("diastolic_bp", {}),
            "spo2": phantom_states.get("spo2", {}),
            "vagal_tone": phantom_states.get("vagal_tone", {}),
            "glucose": phantom_states.get("glucose", {}),
        },
        "anomaly_detection": anomaly_res,
        "diagnostic_hypotheses": [
            {
                "category": h['category'],
                "probability": round(h['posterior_probability'], 4),
                "severity": h['severity'],
                "confidence": h['confidence_level']
            } for h in hypotheses
        ],
        "clinical_codes": report['clinical_codes'],
        "multi_agent_consensus": {
            "consensus_risk": consensus_data["consensus_risk"],
            "action_summary": consensus_data["action_summary"],
            "probabilities": consensus_data["consensus_probabilities"]
        },
        "clinical_alerts": clinical_alerts,
    }

    # Armazenar no buffer histórico do paciente
    if req.patient_id not in patient_telemetry_history:
        patient_telemetry_history[req.patient_id] = []
    patient_telemetry_history[req.patient_id].append(response_payload)
    if len(patient_telemetry_history[req.patient_id]) > 500:
        patient_telemetry_history[req.patient_id].pop(0)
    try:
        from src.ops.device_registry import upsert_frame

        upsert_frame(response_payload)
    except Exception:
        pass

    return response_payload


@app.post("/api/v1/wearables/batch-ingest")
@app.post("/api/v1/wearables/ingest/batch")
def ingest_wearable_batch(
    req: WearableBatchIngestRequest,
    _api_key: str = Depends(require_scope("wearables:write")),
):
    """
    Ingestão em lote de registros históricos descarregados da memória do VE30 (OriginData3).
    """
    if not req.readings:
        return {"status": "warning", "message": "Lote vazio recebido.", "count": 0}

    processed_count = 0
    results = []
    for item in req.readings:
        hr = float(item.get("heart_rate") or item.get("rate_value") or 72.0)
        if hr > 0:
            single_req = WearableTelemetryRequest(
                patient_id=req.patient_id,
                device_id=req.device_id,
                timestamp=str(item.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat()),
                heart_rate=hr,
                spo2=float(item.get("spo2") or item.get("spo2_value") or 98.0),
                blood_pressure_sys=float(item["blood_pressure_sys"]) if item.get("blood_pressure_sys") else None,
                blood_pressure_dia=float(item["blood_pressure_dia"]) if item.get("blood_pressure_dia") else None,
                hrv_rmssd=float(item["hrv"]) if item.get("hrv") else 42.0,
                steps=int(item["step_count"]) if item.get("step_count") else None
            )
            result = ingest_wearable_reading(single_req)
            results.append(result)
            processed_count += 1

    latest_result = results[-1] if results else None
    return {
        "status": "success",
        "patient_id": req.patient_id,
        "processed_count": processed_count,
        "processed_samples": processed_count,
        "latest_result": latest_result,
        "message": f"{processed_count} amostras históricas do VE30 processadas com sucesso na IA."
    }


@app.get("/api/v1/ops/dashboard-bootstrap")
def dashboard_bootstrap():
    """Injeta a chave de leitura no dashboard."""
    key = (os.environ.get("READ_API_KEY") or os.environ.get("API_KEY") or "").strip()
    return {"ok": True, "api_key": key, "fleet_poll_ms": 2000, "page_size": 50, "max_devices": 500}


@app.get("/api/v1/wearables/devices")
def list_wearable_devices(
    q: str = Query(default=""),
    online: Optional[bool] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10000),
    include_latest: bool = Query(default=False),
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Frota de relógios (payload compacto)."""
    from src.ops.device_registry import list_devices as fleet_list

    return fleet_list(
        q=q,
        online=online,
        limit=limit,
        offset=offset,
        include_latest=include_latest,
    )


@app.get("/api/v1/wearables/patient/{patient_id}/latest")
def get_patient_latest_telemetry(
    patient_id: str,
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """Retorna a última leitura biométrica e inferência de IA para um paciente."""
    history = patient_telemetry_history.get(patient_id, [])
    if not history:
        raise HTTPException(status_code=404, detail=f"Nenhuma telemetria encontrada para o paciente '{patient_id}'.")
    return history[-1]


@app.get("/api/v1/wearables/patient/{patient_id}/history")
def get_patient_telemetry_history(
    patient_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    _api_key: str = Depends(require_patient_access("wearables:read")),
):
    """Retorna histórico de leituras biométricas de um paciente."""
    history = patient_telemetry_history.get(patient_id, [])
    return {
        "patient_id": patient_id,
        "total_records": len(history),
        "records": history[-max(1, min(limit, 200)):]
    }


@app.delete("/api/v1/patient/{patient_id}/anonymize")
def anonymize_patient_telemetry(
    patient_id: str,
    _api_key: str = Depends(require_scope("admin")),
):
    """Endpoint de conformidade LGPD: purga dados do paciente."""
    removed_history = patient_telemetry_history.pop(patient_id, None)
    removed_engine = patient_engines.pop(patient_id, None)
    if removed_history is None and removed_engine is None:
        raise HTTPException(status_code=404, detail=f"Nenhum dado ativo registrado para o paciente '{patient_id}'.")
    return {
        "status": "success",
        "message": f"Dados do paciente '{patient_id}' purgados com sucesso para conformidade LGPD.",
        "patient_id": patient_id,
    }


@app.post("/api/hemodynamics/simulate_wk4")
def simulate_windkessel_4e(req: WindkesselSimRequest):
    """Simula dinâmica cardiovascular com Windkessel de 4 Elementos e Runge-Kutta 4ª Ordem."""
    params = Windkessel4EParams(Rp=req.Rp, C=req.C, Zc=req.Zc, L=req.L)
    baro = BaroreflexParams() if req.with_baroreflex else None
    sim = Windkessel4ESimulator(params=params, baroreflex=baro)
    
    res = sim.simulate(
        duration_s=req.duration_s,
        dt=0.005,
        heart_rate=req.hr,
        stroke_volume=req.sv
    )
    
    # Subamostragem para transmissão eficiente JSON (max 300 pontos)
    step = max(1, len(res.t) // 250)
    return {
        "time": [float(round(v, 4)) for v in res.t[::step]],
        "pressure": [float(round(v, 2)) for v in res.pressure[::step]],
        "flow": [float(round(v, 2)) for v in res.flow[::step]],
        "metrics": {
            "systolic_bp": float(round(res.systolic_bp, 1)),
            "diastolic_bp": float(round(res.diastolic_bp, 1)),
            "mean_arterial_pressure": float(round(res.mean_arterial_pressure, 1)),
            "pulse_pressure": float(round(res.pulse_pressure, 1)),
            "pwv_bramwell_hill": float(round(res.pwv_bramwell_hill, 2)),
            "arterial_compliance": float(round(req.C, 2)),
            "peripheral_resistance": float(round(req.Rp, 2)),
        }
    }


@app.post("/api/game_theory/solve_triage")
def solve_triage_game(req: TriageSolveRequest):
    """Calcula o Equilíbrio de Nash e a Fronteira de Pareto para alocação de leitos hospitalares."""
    result = triage_engine.solve_triage_game(
        icu_capacity=req.icu_capacity,
        ward_capacity=req.ward_capacity,
        icu_demand=req.icu_demand,
        ward_demand=req.ward_demand,
        high_risk_fraction=req.high_risk_fraction,
    )
    return result


@app.post("/api/clinical/multi_agent_consensus")
def evaluate_clinical_consensus(req: MultiAgentConsensusRequest):
    """Executa consulta deliberativa ao conselho de agentes clínicos especialistas (Dempster-Shafer)."""
    consensus = consensus_coordinator.reach_consensus(
        patient_id=req.patient_id,
        vitals=req.vitals,
        phantom_data=req.phantom_data,
        hrv_metrics=req.hrv_metrics,
        hemodynamics=req.hemodynamics,
    )
    return consensus


# =====================================================================
# WEBSOCKET STREAMING ENGINE
# =====================================================================

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
    wk4_sim = Windkessel4ESimulator()
    
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
            
        # 1. Simular evolução fisiológica (Ornstein-Uhlenbeck com drift estocástico)
        is_stress = np.random.random() < 0.05
        drift = 15.0 if is_stress else 0.0
        
        hr_state += 0.1 * (72.0 + drift - hr_state) + np.random.normal(0, 1.2)
        rmssd_state += 0.05 * (42.0 - (drift * 0.8) - rmssd_state) + np.random.normal(0, 0.8)
        temp_state += 0.02 * (33.2 - temp_state) + np.random.normal(0, 0.05)
        
        hr_state = max(40.0, min(180.0, hr_state))
        rmssd_state = max(5.0, rmssd_state)
        temp_state = np.clip(temp_state, 31.0, 39.0)
        
        # 2. Simular leituras brutas de 2 wearables com ruídos heterogêneos
        watch_noise = np.random.normal(0, 1.8)
        band_noise = np.random.normal(0, 4.0)
        
        watch_reading = hr_state + watch_noise
        band_reading = hr_state + band_noise
        
        # 3. Sensor Fusion Bayesiana BLUE
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
            
        # Inserção assíncrona no BigQuery se configurado
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

        # 5. Simulação Hemodinâmica WK4 acoplada
        wk4_res = wk4_sim.simulate(duration_s=1.2, dt=0.01, heart_rate=bpm_clean, stroke_volume=70.0)
        
        # 6. Avaliação Multi-Agente
        consensus_data = consensus_coordinator.reach_consensus(
            patient_id="SECURE_PATIENT_001",
            vitals={"heart_rate": bpm_clean, "spo2": phantom_states.get("spo2", {}).get("estimate", 97.0)},
            phantom_data=phantom_states,
            hrv_metrics=hrv_metrics,
            hemodynamics={"pwv_bramwell_hill": wk4_res.pwv_bramwell_hill}
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
            "hemodynamics_wk4": {
                "systolic_bp": round(wk4_res.systolic_bp, 1),
                "diastolic_bp": round(wk4_res.diastolic_bp, 1),
                "map": round(wk4_res.mean_arterial_pressure, 1),
                "pwv": round(wk4_res.pwv_bramwell_hill, 2),
            },
            "consensus": {
                "risk": consensus_data["consensus_risk"],
                "action": consensus_data["action_summary"],
                "probabilities": consensus_data["consensus_probabilities"]
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
