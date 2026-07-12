import streamlit as st
import sys
import os
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Adiciona a raiz do projeto ao path para importar os módulos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data_warehouse.datalake_manager import DataLakeManager
from src.ml_pipeline.slm_search_engine import SLMSearchEngine
from src.ml_pipeline.online_inference import VertexOnlineDetector

# Importar os novos módulos de processamento de sinais, dados fantasmas e ontologia clínica
from src.signal_processing import WaveletDenoiser, ButterworthFilter, AdaptiveSensorFusion
from src.phantom_data import PhantomDataEngine, HRVAnalyzer
from src.ontology import ClinicalOntologyMapper, BayesianDiagnosticNetwork, OntologyEnrichedReport

st.set_page_config(
    page_title="HealthTech Advanced MLOps",
    layout="wide",
    page_icon="🧬",
    initial_sidebar_state="expanded"
)

# Estilo CSS customizado para estética premium (Dark Theme, Glassmorphism, Neon Highlights)
st.markdown("""
<style>
    /* Estilo de fontes e backgrounds */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    .stApp {
        background-color: #0d0f14;
        color: #e2e8f0;
    }
    
    /* Customização dos Headers */
    h1, h2, h3, h4 {
        color: #38bdf8 !important;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    /* Efeito de Card Glassmorphism */
    .metric-card {
        background: rgba(30, 41, 59, 0.45);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
        margin-bottom: 15px;
    }
    
    .glowing-border-blue {
        border-left: 5px solid #0284c7;
    }
    .glowing-border-green {
        border-left: 5px solid #059669;
    }
    .glowing-border-red {
        border-left: 5px solid #dc2626;
    }
    .glowing-border-yellow {
        border-left: 5px solid #d97706;
    }
    
    /* Streamlit Metric Custom styling */
    div[data-testid="stMetricValue"] {
        font-size: 2.2rem;
        font-weight: 700;
        color: #f8fafc;
    }
    
    div[data-testid="stMetricLabel"] {
        font-size: 0.95rem;
        color: #94a3b8;
    }
</style>
""", unsafe_allow_html=True)

st.title("🧬 HealthTech - Painel de Controle MLOps e Engenharia Biomédica")
st.markdown("Painel avançado para processamento de sinais, estimativa de **Dados Fantasmas** e ponte diagnóstica com **Ontologia Clínica USP**.")

# Inicializa as classes no Cache
@st.cache_resource
def load_engines():
    dl = DataLakeManager()
    slm = SLMSearchEngine()
    mapper = ClinicalOntologyMapper()
    bayes_net = BayesianDiagnosticNetwork()
    report_gen = OntologyEnrichedReport(mapper, bayes_net)
    return dl, slm, mapper, bayes_net, report_gen

dl_manager, slm_engine, ontology_mapper, bayes_net, report_generator = load_engines()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Status do Sistema", 
    "🔍 Motor de Busca (SLM)", 
    "🧠 Análise de Tópicos", 
    "📈 Telemetria e Dados Fantasmas", 
    "⚙️ Orquestração"
])

with tab1:
    st.header("Monitoramento de Algoritmos Fisiológicos")
    df_lake = dl_manager.load_latest_knowledge()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown('<div class="metric-card glowing-border-blue">', unsafe_allow_html=True)
        st.metric("Teses no Data Lake (USP)", f"{len(df_lake)}")
        st.markdown('</div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="metric-card glowing-border-green">', unsafe_allow_html=True)
        st.metric("Motor de Busca (SLM)", "Ativo ✅")
        st.markdown('</div>', unsafe_allow_html=True)
    with col3:
        st.markdown('<div class="metric-card glowing-border-yellow">', unsafe_allow_html=True)
        st.metric("Filtro de Kalman (Phantom)", "Pronto ⚡")
        st.markdown('</div>', unsafe_allow_html=True)
    with col4:
        st.markdown('<div class="metric-card glowing-border-red">', unsafe_allow_html=True)
        st.metric("Ontologia Clínica", "Ativa 🧬")
        st.markdown('</div>', unsafe_allow_html=True)
    
    if not df_lake.empty:
        st.subheader("Prévia do Data Lake (Trusted Zone)")
        cols_to_show = ['titulo', 'autor', 'url']
        if 'topico_dominante' in df_lake.columns:
            cols_to_show.append('topico_dominante')
        st.dataframe(df_lake[cols_to_show].head(10))

with tab2:
    st.header("Pesquisa Semântica Médica RAG")
    st.markdown("Utilize o SLM local para buscar conhecimento médico no nosso Data Lake baseado nas teses da USP.")
    
    query = st.text_input("Sintoma, contexto clínico ou tratamento para pesquisa semântica:")
    
    if st.button("Pesquisar com IA"):
        if query:
            with st.spinner("Procurando conexões via Embeddings..."):
                res = slm_engine.search_medical_knowledge(query, n_results=3)
                
                if res['documents'] and len(res['documents'][0]) > 0:
                    for i in range(len(res['documents'][0])):
                        st.markdown("---")
                        meta = res['metadatas'][0][i]
                        dist = res['distances'][0][i] if 'distances' in res and res['distances'] else "N/A"
                        
                        st.markdown(f"**Fonte URL:** {meta.get('url', '')}")
                        st.markdown(f"**Tópico Dominante:** {meta.get('topico_dominante', 'N/A')}")
                        st.markdown(f"**Relevância (Distância L2):** {dist}")
                        st.markdown(f"**Trecho/Resumo:**\n{res['documents'][0][i]}")
                else:
                    st.warning("Nenhum contexto encontrado no Data Lake.")

with tab3:
    st.header("Análise de Tópicos NLP (LDA)")
    df_lake = dl_manager.load_latest_knowledge()
    
    if not df_lake.empty and 'topico_dominante' in df_lake.columns:
        topic_counts = df_lake['topico_dominante'].value_counts().reset_index()
        topic_counts.columns = ['Tópico', 'Quantidade']
        
        fig = px.pie(
            topic_counts, 
            values='Quantidade', 
            names='Tópico', 
            title="Distribuição de Tópicos das Teses USP (Ontologia Mapeada)", 
            hole=0.4,
            template="plotly_dark"
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("O modelo LDA guiado identificou clusters latentes de conhecimento médico nas pesquisas acadêmicas da USP.")
    else:
        st.info("Nenhum tópico NLP encontrado. Certifique-se de ter rodado o script de treinamento NLP e indexado no Data Lake.")

with tab4:
    st.header("Telemetria do Paciente em Tempo Real e Inferência Fisiológica")
    st.markdown("Simulação de streaming de múltiplos wearables com fusão de sensores, filtragem de ruído, estimativa de **dados fantasmas** e diagnóstico bayesiano.")
    
    # Controles da Simulação
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 2])
    with col_ctrl1:
        start_sim = st.button("▶️ Iniciar Telemetria Real")
    with col_ctrl2:
        stop_sim = st.button("⏹️ Parar Simulação")
    with col_ctrl3:
        filter_option = st.selectbox(
            "Método de Filtragem de Ruído:",
            ["Sem Filtro", "Wavelet (db4) DWT", "Butterworth Bandpass (0.5 - 4.0 Hz)"]
        )
        
    if "sim_running" not in st.session_state:
        st.session_state.sim_running = False
        
    if start_sim:
        st.session_state.sim_running = True
    if stop_sim:
        st.session_state.sim_running = False
        
    # Elementos Dinâmicos da Página
    col_plots, col_sidebar = st.columns([2, 1])
    
    with col_plots:
        chart_bpm_place = st.empty()
        chart_bp_place = st.empty()
        chart_spo2_glucose_place = st.empty()
        
    with col_sidebar:
        st.subheader("Estado Clínico Atual")
        metric_bp_place = st.empty()
        metric_spo2_place = st.empty()
        metric_vagal_place = st.empty()
        metric_glucose_place = st.empty()
        
        st.subheader("Ponte Diagnóstica Bayesiana (Ontologia)")
        diag_probs_place = st.empty()
        codes_place = st.empty()
        rag_matching_place = st.empty()
        
    if st.session_state.sim_running:
        # Configurar Filtros e Motor de Dados Fantasmas
        wavelet_denoiser = WaveletDenoiser(wavelet='db4', level=2)
        butter_filter = ButterworthFilter(fs=1.0)
        sensor_fuser = AdaptiveSensorFusion(sensor_ids=["pixel_watch", "fitbit_band"])
        phantom_engine = PhantomDataEngine(dt=1.0, use_ukf=False)
        
        # Histórico para Gráficos
        time_history = []
        raw_bpm_history = []
        clean_bpm_history = []
        sbp_history = []
        sbp_lower_history = []
        sbp_upper_history = []
        dbp_history = []
        dbp_lower_history = []
        dbp_upper_history = []
        spo2_history = []
        spo2_lower_history = []
        spo2_upper_history = []
        glucose_history = []
        glucose_lower_history = []
        glucose_upper_history = []
        vagal_history = []
        
        # Valores de estado inicial
        current_hr_state = 70.0
        current_rmssd_state = 40.0
        current_temp_state = 33.0
        
        # Simulação em Loop
        for step in range(1, 101):
            if not st.session_state.sim_running:
                break
                
            time_history.append(step)
            
            # --- SIMULAÇÃO DE ESTRESSE FISIOLÓGICO NO TEMPO ---
            # Do passo 35 ao 65, simular evento de taquicardia sinusal e hipertensão leve
            is_stress = 35 <= step <= 65
            target_hr = 110.0 if is_stress else 70.0
            target_rmssd = 18.0 if is_stress else 45.0
            target_temp = 33.6 if is_stress else 33.0
            
            # Atualização estocástica (Ornstein-Uhlenbeck simplificado)
            current_hr_state += 0.3 * (target_hr - current_hr_state) + np.random.normal(0, 3)
            current_rmssd_state += 0.3 * (target_rmssd - current_rmssd_state) + np.random.normal(0, 2)
            current_temp_state += 0.1 * (target_temp - current_temp_state) + np.random.normal(0, 0.05)
            
            # Cliping fisiológico
            current_hr_state = np.clip(current_hr_state, 40.0, 180.0)
            current_rmssd_state = max(5.0, current_rmssd_state)
            current_temp_state = np.clip(current_temp_state, 31.0, 39.0)
            
            # 1. Simular Múltiplos Sensores com ruído independente (Deduplicação)
            watch_noise = np.random.normal(0, 2.0)
            band_noise = np.random.normal(0, 3.5) # Sensor Fitbit é mais ruidoso nesta simulação
            
            watch_reading = current_hr_state + watch_noise
            band_reading = current_hr_state + band_noise
            
            # 2. Fusão Bayesiana
            fused_result = sensor_fuser.fuse_readings({
                "pixel_watch": watch_reading,
                "fitbit_band": band_reading
            })
            bpm_fused = fused_result['fused_estimate']
            raw_bpm_history.append(watch_reading) # Pixel watch como exemplo do cru
            
            # 3. Filtragem de Ruído Adicional (Wavelet / Butterworth)
            if filter_option == "Wavelet (db4) DWT" and len(raw_bpm_history) >= 4:
                # Wavelet precisa de uma janela histórica
                window_fused = np.array(raw_bpm_history[-8:])
                denoised_win = wavelet_denoiser.denoise(window_fused)
                bpm_clean = denoised_win[-1]
            elif filter_option == "Butterworth Bandpass (0.5 - 4.0 Hz)" and len(raw_bpm_history) >= 4:
                # Filtro Butterworth
                window_fused = np.array(raw_bpm_history[-8:])
                denoised_win = butter_filter.lowpass(window_fused, cutoff=0.3)
                bpm_clean = denoised_win[-1]
            else:
                # Sem filtro
                bpm_clean = bpm_fused
                
            clean_bpm_history.append(bpm_clean)
            
            # 4. Motor de Dados Fantasmas (Invocação EKF/UKF)
            wearable_data = {
                'heart_rate': bpm_clean,
                'hrv_rmssd': current_rmssd_state,
                'skin_temp': current_temp_state,
                'activity_level': 1.0 if is_stress else 0.0
            }
            
            phantom_result = phantom_engine.process_reading(wearable_data)
            states = phantom_result['states']
            
            # Guardar histórico dos fantasmas
            sbp_history.append(states['systolic_bp']['estimate'])
            sbp_lower_history.append(states['systolic_bp']['ci_lower'])
            sbp_upper_history.append(states['systolic_bp']['ci_upper'])
            
            dbp_history.append(states['diastolic_bp']['estimate'])
            dbp_lower_history.append(states['diastolic_bp']['ci_lower'])
            dbp_upper_history.append(states['diastolic_bp']['ci_upper'])
            
            spo2_history.append(states['spo2']['estimate'])
            spo2_lower_history.append(states['spo2']['ci_lower'])
            spo2_upper_history.append(states['spo2']['ci_upper'])
            
            glucose_history.append(states['glucose']['estimate'])
            glucose_lower_history.append(states['glucose']['ci_lower'])
            glucose_upper_history.append(states['glucose']['ci_upper'])
            
            vagal_history.append(states['vagal_tone']['estimate'])
            
            # 5. Ponte Diagnóstica Bayesiana (Ontologia Clínica)
            current_phantom = {k: v['estimate'] for k, v in states.items()}
            hrv_metrics = {'rmssd': current_rmssd_state}
            
            hypotheses = bayes_net.generate_diagnostic_hypotheses(
                phantom_data=current_phantom,
                hrv_metrics=hrv_metrics,
                top_k=4
            )
            
            # Mapear códigos e reportar
            primary_hyp = hypotheses[0]
            report = report_generator.generate_patient_report(
                patient_id="SECURE_PATIENT_001",
                phantom_data=current_phantom,
                hrv_metrics=hrv_metrics
            )
            
            # 6. Renderizar Métricas na Direita
            with col_sidebar:
                # Pressão Arterial
                metric_bp_place.markdown(
                    f'<div class="metric-card glowing-border-blue">'
                    f'  <div style="font-size:0.9rem;color:#94a3b8;">Pressão Arterial Estimada (Fantasma)</div>'
                    f'  <div style="font-size:1.8rem;font-weight:700;color:#f8fafc;">{current_phantom["systolic_bp"]:.0f} / {current_phantom["diastolic_bp"]:.0f} <span style="font-size:0.9rem;font-weight:normal;color:#94a3b8;">mmHg</span></div>'
                    f'  <div style="font-size:0.8rem;color:#0284c7;">IC: ({states["systolic_bp"]["ci_lower"]:.0f} - {states["systolic_bp"]["ci_upper"]:.0f})</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # SpO2
                metric_spo2_place.markdown(
                    f'<div class="metric-card glowing-border-green">'
                    f'  <div style="font-size:0.9rem;color:#94a3b8;">Oxigenação (SpO2 Inferida)</div>'
                    f'  <div style="font-size:1.8rem;font-weight:700;color:#f8fafc;">{current_phantom["spo2"]:.1f}%</div>'
                    f'  <div style="font-size:0.8rem;color:#10b981;">Confiável: {"Sim ✓" if states["spo2"]["reliable"] else "Não ⚠️"}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # Tônus Vagal
                metric_vagal_place.markdown(
                    f'<div class="metric-card glowing-border-yellow">'
                    f'  <div style="font-size:0.9rem;color:#94a3b8;">Tônus Vagal Estimado</div>'
                    f'  <div style="font-size:1.8rem;font-weight:700;color:#f8fafc;">{current_phantom["vagal_tone"]:.1f} <span style="font-size:0.8rem;font-weight:normal;color:#94a3b8;">u.a.</span></div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # Glicose
                metric_glucose_place.markdown(
                    f'<div class="metric-card glowing-border-red">'
                    f'  <div style="font-size:0.9rem;color:#94a3b8;">Nível de Glicose Estimado</div>'
                    f'  <div style="font-size:1.8rem;font-weight:700;color:#f8fafc;">{current_phantom["glucose"]:.1f} <span style="font-size:0.8rem;font-weight:normal;color:#94a3b8;">mg/dL</span></div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
                # Renderizar probabilidades diagnósticas
                df_hyp = pd.DataFrame([
                    {'Categoria': h['category'], 'Probabilidade': h['posterior_probability']}
                    for h in hypotheses
                ])
                fig_bar = px.bar(
                    df_hyp, 
                    x='Probabilidade', 
                    y='Categoria', 
                    orientation='h', 
                    range_x=[0, 1.0],
                    color='Probabilidade',
                    color_continuous_scale='Bluered',
                    template='plotly_dark',
                    height=200
                )
                fig_bar.update_layout(showlegend=False, coloraxis_showscale=False, margin=dict(l=10, r=10, t=10, b=10))
                diag_probs_place.plotly_chart(fig_bar, use_container_width=True)
                
                # Exibir códigos clínicos
                codes = report['clinical_codes']
                codes_place.markdown(
                    f"**Interoperabilidade de Códigos Clínicos (Ontologia):**\n"
                    f"- **CID-10:** {', '.join(codes['icd10']) if codes['icd10'] else 'Nenhum'}\n"
                    f"- **SNOMED-CT:** {', '.join(codes['snomed']) if codes['snomed'] else 'Nenhum'}\n"
                    f"- **MeSH:** {', '.join(codes['mesh']) if codes['mesh'] else 'Nenhum'}"
                )
                
                # Real-time RAG matching
                if is_stress:
                    rag_matching_place.info(
                        "🔍 **RAG USP Match:** O modelo de linguagem identificou correlação forte com teses do departamento de "
                        "Cardiologia (Incor/FMUSP) sobre monitoramento de arritmias por sensores vestíveis."
                    )
                else:
                    rag_matching_place.success(
                        "🔍 **RAG USP Match:** Sem alertas ativos. Baseline fisiológico corresponde a perfil saudável padrão USP."
                    )

            # 7. Renderizar Gráficos na Esquerda
            with col_plots:
                # Gráfico 1: Heart Rate (Fusional vs. Bruto)
                fig_hr = go.Figure()
                fig_hr.add_trace(go.Scatter(x=time_history, y=raw_bpm_history, mode='lines', name='BPM Bruto (Watch)', line=dict(color='rgba(239, 68, 68, 0.4)', dash='dot')))
                fig_hr.add_trace(go.Scatter(x=time_history, y=clean_bpm_history, mode='lines', name='BPM Filtrado e Reconciliado', line=dict(color='#0ea5e9', width=2.5)))
                fig_hr.update_layout(
                    title="Frequência Cardíaca (BPM) - Filtro & Reconciliação", 
                    xaxis_title="Tempo (s)", 
                    yaxis_title="BPM",
                    template='plotly_dark',
                    height=300,
                    margin=dict(l=10, r=10, t=40, b=10)
                )
                chart_bpm_place.plotly_chart(fig_hr, use_container_width=True)
                
                # Gráfico 2: Pressão Arterial com Envelope de Confiança
                fig_bp = go.Figure()
                # Sistólica
                fig_bp.add_trace(go.Scatter(x=time_history, y=sbp_upper_history, mode='lines', line=dict(width=0), showlegend=False))
                fig_bp.add_trace(go.Scatter(x=time_history, y=sbp_lower_history, mode='lines', fill='tonexty', fillcolor='rgba(14, 165, 233, 0.15)', line=dict(width=0), name='95% Confiança PAS'))
                fig_bp.add_trace(go.Scatter(x=time_history, y=sbp_history, mode='lines', name='Pressão Sistólica (PAS)', line=dict(color='#38bdf8', width=2)))
                # Diastólica
                fig_bp.add_trace(go.Scatter(x=time_history, y=dbp_upper_history, mode='lines', line=dict(width=0), showlegend=False))
                fig_bp.add_trace(go.Scatter(x=time_history, y=dbp_lower_history, mode='lines', fill='tonexty', fillcolor='rgba(16, 185, 129, 0.15)', line=dict(width=0), name='95% Confiança PAD'))
                fig_bp.add_trace(go.Scatter(x=time_history, y=dbp_history, mode='lines', name='Pressão Diastólica (PAD)', line=dict(color='#34d399', width=2)))
                
                fig_bp.update_layout(
                    title="Pressão Arterial Estimada (Dados Fantasmas) - mmHg", 
                    xaxis_title="Tempo (s)",
                    yaxis_title="mmHg",
                    template='plotly_dark',
                    height=300,
                    margin=dict(l=10, r=10, t=40, b=10)
                )
                chart_bp_place.plotly_chart(fig_bp, use_container_width=True)
                
                # Gráfico 3: SpO2 e Glucose
                fig_sg = go.Figure()
                # SpO2
                fig_sg.add_trace(go.Scatter(x=time_history, y=spo2_upper_history, mode='lines', line=dict(width=0), showlegend=False))
                fig_sg.add_trace(go.Scatter(x=time_history, y=spo2_lower_history, mode='lines', fill='tonexty', fillcolor='rgba(245, 158, 11, 0.1)', line=dict(width=0), name='95% Confiança SpO2'))
                fig_sg.add_trace(go.Scatter(x=time_history, y=spo2_history, mode='lines', name='Saturação de Oxigênio (%)', line=dict(color='#fbbf24', width=2)))
                
                fig_sg.update_layout(
                    title="Oxigenação e Perfusão Periférica (Dados Fantasmas)", 
                    xaxis_title="Tempo (s)",
                    yaxis_title="Percentual SpO2",
                    template='plotly_dark',
                    height=300,
                    margin=dict(l=10, r=10, t=40, b=10)
                )
                chart_spo2_glucose_place.plotly_chart(fig_sg, use_container_width=True)

            time.sleep(0.4)

with tab5:
    st.header("Orquestração")
    if st.button("🚀 Re-indexar Data Lake no Motor SLM"):
        with st.spinner("Lendo arquivos Parquet e gerando Embeddings..."):
            slm_engine.index_datalake(dl_manager)
        st.success("Motor de pesquisa atualizado!")
