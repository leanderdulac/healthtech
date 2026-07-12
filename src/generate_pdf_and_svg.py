"""
generate_pdf_and_svg.py — Script para Geração do Documento PDF e do Diagrama SVG Matemático

Este script gera:
1. Um diagrama de fluxo vetorial SVG de alta qualidade estética, representando o
   pipeline matemático do projeto.
2. Um documento PDF detalhado de 3 páginas contendo toda a matemática envolvida,
   formatado profissionalmente com a biblioteca ReportLab.
"""

import os
import shutil
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT

# Diretórios de Destino
ARTIFACTS_DIR = r"C:\Users\leand\.gemini\antigravity\brain\a7f42c60-eaed-4a84-b071-97633b5c04cb"
DASHBOARD_DIR = r"c:\Users\leand\Downloads\Projetos\HealthTech\dashboard"


def generate_svg():
    """Gera um arquivo SVG representativo do fluxo matemático do sistema."""
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 650" width="100%" height="100%">
    <!-- Filtros de Glow (Efeito Neon) -->
    <defs>
        <linearGradient id="grad-blue" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#0284c7;stop-opacity:1" />
            <stop offset="100%" style="stop-color:#0ea5e9;stop-opacity:1" />
        </linearGradient>
        <linearGradient id="grad-green" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#059669;stop-opacity:1" />
            <stop offset="100%" style="stop-color:#10b981;stop-opacity:1" />
        </linearGradient>
        <linearGradient id="grad-yellow" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#d97706;stop-opacity:1" />
            <stop offset="100%" style="stop-color:#f59e0b;stop-opacity:1" />
        </linearGradient>
        <linearGradient id="grad-red" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#dc2626;stop-opacity:1" />
            <stop offset="100%" style="stop-color:#ef4444;stop-opacity:1" />
        </linearGradient>
        
        <filter id="glow-blue" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <filter id="glow-green" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <filter id="glow-yellow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <filter id="glow-red" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
    </defs>

    <!-- Fundo Escuro -->
    <rect width="1000" height="650" fill="#090b10" rx="15" />
    <rect width="990" height="640" x="5" y="5" fill="none" stroke="#1e293b" stroke-width="2" rx="10" />

    <!-- Título Principal -->
    <text x="500" y="45" fill="#f8fafc" font-family="Outfit, sans-serif" font-size="24" font-weight="bold" text-anchor="middle" letter-spacing="1">
        FLUXO MATEMÁTICO — SAÚDE RESPONSIVA
    </text>
    <text x="500" y="70" fill="#64748b" font-family="Outfit, sans-serif" font-size="14" text-anchor="middle">
        Pipeline Biomédico de Processamento, Fusão e Estimativa de Sinais Ocultos
    </text>

    <!-- 1. BLOCO DE ENTRADA (SINAIS DE SENSORES) -->
    <g transform="translate(60, 120)">
        <rect width="250" height="110" fill="#0f172a" stroke="url(#grad-blue)" stroke-width="2" rx="12" filter="url(#glow-blue)" />
        <text x="20" y="30" fill="#38bdf8" font-family="Outfit, sans-serif" font-size="14" font-weight="bold">1. ENTRADA DE WEARABLES</text>
        <text x="20" y="55" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="12">Frequência Cardíaca Bruta: z_k</text>
        <text x="20" y="75" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="12">Ruído Estocástico Fisiológico</text>
        <text x="20" y="95" fill="#64748b" font-family="Outfit, sans-serif" font-size="10">Pixel Watch &amp; Fitbit Band</text>
    </g>

    <!-- Linha de conexão 1 -> 2 -->
    <path d="M 310 175 L 380 175" stroke="#38bdf8" stroke-width="2" marker-end="url(#arrow)" fill="none" stroke-dasharray="4" />

    <!-- 2. BLOCO FUSÃO BAYESIANA (BLUE) -->
    <g transform="translate(390, 120)">
        <rect width="250" height="110" fill="#0f172a" stroke="url(#grad-blue)" stroke-width="2" rx="12" filter="url(#glow-blue)" />
        <text x="20" y="30" fill="#38bdf8" font-family="Outfit, sans-serif" font-size="14" font-weight="bold">2. FUSÃO BAYESIANA (BLUE)</text>
        <text x="20" y="55" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">x_fused = Σ(w_i * z_i)</text>
        <text x="20" y="75" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">w_i = (1/σ²_i) / Σ(1/σ²_j)</text>
        <text x="20" y="95" fill="#64748b" font-family="Outfit, sans-serif" font-size="10">Variância adaptativa via EWMA</text>
    </g>

    <!-- Linha de conexão 2 -> 3 -->
    <path d="M 640 175 L 710 175" stroke="#38bdf8" stroke-width="2" fill="none" />

    <!-- 3. BLOCO FILTRAGEM WAVELET (DWT) -->
    <g transform="translate(720, 120)">
        <rect width="220" height="110" fill="#0f172a" stroke="url(#grad-blue)" stroke-width="2" rx="12" filter="url(#glow-blue)" />
        <text x="20" y="30" fill="#38bdf8" font-family="Outfit, sans-serif" font-size="14" font-weight="bold">3. DENOISING DWT</text>
        <text x="20" y="55" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="12">Wavelet db4 &amp; Soft Threshold</text>
        <text x="20" y="75" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">λ = σ * sqrt(2 * ln(N))</text>
        <text x="20" y="95" fill="#64748b" font-family="Outfit, sans-serif" font-size="10">Remoção de artefatos de movimento</text>
    </g>

    <!-- Curva de conexão 3 -> 4 -->
    <path d="M 830 230 L 830 290 L 500 290 L 500 340" stroke="#10b981" stroke-width="2" fill="none" />

    <!-- 4. BLOCO KALMAN FILTER (DADOS FANTASMAS) -->
    <g transform="translate(350, 350)">
        <rect width="300" height="130" fill="#0f172a" stroke="url(#grad-green)" stroke-width="2" rx="12" filter="url(#glow-green)" />
        <text x="20" y="30" fill="#34d399" font-family="Outfit, sans-serif" font-size="14" font-weight="bold">4. FILTRO DE KALMAN (EKF / UKF)</text>
        <text x="20" y="55" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="12">Estimativa de Variáveis Ocultas (Fantasmas):</text>
        <text x="20" y="75" fill="#38bdf8" font-family="Outfit, sans-serif" font-size="11" font-weight="bold">PAS / PAD | SpO₂ | Glicose | Tono Vagal</text>
        <text x="20" y="95" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">x_k = f(x_k-1) + w_k  |  z_k = h(x_k) + v_k</text>
        <text x="20" y="115" fill="#64748b" font-family="Outfit, sans-serif" font-size="10">Homeostase via processo Ornstein-Uhlenbeck</text>
    </g>

    <!-- Linha de conexão 4 -> 5 -->
    <path d="M 350 415 L 290 415" stroke="#f59e0b" stroke-width="2" fill="none" />
    <path d="M 650 415 L 710 415" stroke="#ef4444" stroke-width="2" fill="none" />

    <!-- 5. BLOCO DETECTOR DE ANOMALIAS (MAHALANOBIS) -->
    <g transform="translate(60, 350)">
        <rect width="220" height="130" fill="#0f172a" stroke="url(#grad-yellow)" stroke-width="2" rx="12" filter="url(#glow-yellow)" />
        <text x="20" y="30" fill="#fbbf24" font-family="Outfit, sans-serif" font-size="14" font-weight="bold">5. ANOMALIAS (MAHALANOBIS)</text>
        <text x="20" y="55" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="12">Distância Multivariada Escalar</text>
        <text x="20" y="75" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">D_M² = (x-μ)ᵀ Σ⁻¹ (x-μ)</text>
        <text x="20" y="95" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">D_M² ~ χ²(p) → p-value</text>
        <text x="20" y="115" fill="#64748b" font-family="Outfit, sans-serif" font-size="10">Alarme se p-value &lt; 0.01</text>
    </g>

    <!-- 6. BLOCO REDE BAYESIANA DIAGNÓSTICA -->
    <g transform="translate(720, 350)">
        <rect width="220" height="130" fill="#0f172a" stroke="url(#grad-red)" stroke-width="2" rx="12" filter="url(#glow-red)" />
        <text x="20" y="30" fill="#f87171" font-family="Outfit, sans-serif" font-size="14" font-weight="bold">6. REDE BAYESIANA</text>
        <text x="20" y="55" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="11" font-family="monospace">P(C_i|x) ∝ P(x|C_i)*P(C_i)</text>
        <text x="20" y="75" fill="#cbd5e1" font-family="Outfit, sans-serif" font-size="12">Ponte Ontológica Clínica</text>
        <text x="20" y="95" fill="#38bdf8" font-family="Outfit, sans-serif" font-size="11" font-weight="bold">ICD-10 | SNOMED | MeSH</text>
        <text x="20" y="115" fill="#64748b" font-family="Outfit, sans-serif" font-size="10">Corpus de Teses da USP (RAG)</text>
    </g>

    <!-- Marcador de Seta -->
    <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#38bdf8" />
        </marker>
    </defs>
</svg>"""
    
    # Gravar SVG localmente
    svg_paths = [
        os.path.join(DASHBOARD_DIR, "math_diagram.svg"),
        os.path.join(ARTIFACTS_DIR, "math_diagram.svg")
    ]
    for path in svg_paths:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg_content)
        print(f"Diagrama SVG salvo em: {path}")


def generate_pdf():
    """Gera um arquivo PDF contendo a explicação da matemática do projeto."""
    pdf_filename = "Sobre_matematica_envolvida.pdf"
    local_pdf_path = os.path.join(DASHBOARD_DIR, pdf_filename)
    
    # Configurar documento
    doc = SimpleDocTemplate(
        local_pdf_path,
        pagesize=A4,
        rightMargin=40, leftMargin=40,
        topMargin=45, bottomMargin=45
    )
    
    # Folha de Estilos
    styles = getSampleStyleSheet()
    
    # Modificar estilos existentes para evitar conflitos de nomes
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0f172a'),
        alignment=TA_CENTER,
        spaceAfter=15
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        alignment=TA_CENTER,
        spaceAfter=25
    )
    
    h1_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#0284c7'),
        spaceBefore=15,
        spaceAfter=8,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'DocBodyText',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1e293b'),
        alignment=TA_JUSTIFY,
        spaceAfter=10
    )
    
    formula_style = ParagraphStyle(
        'MathFormula',
        parent=styles['Normal'],
        fontName='Courier-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#0f172a'),
        backColor=colors.HexColor('#f8fafc'),
        borderColor=colors.HexColor('#e2e8f0'),
        borderWidth=1,
        borderPadding=8,
        alignment=TA_CENTER,
        spaceAfter=10,
        spaceBefore=5
    )

    story = []
    
    # ── CAPA / CABEÇALHO ──
    story.append(Paragraph("SOBRE A MATEMÁTICA ENVOLVIDA NO PROJETO SAÚDE RESPONSIVA", title_style))
    story.append(Paragraph("Manual de Modelagem Matemática, Fusão Fisiológica e Inferência de Dados Fantasmas", subtitle_style))
    story.append(Spacer(1, 10))
    
    intro_text = (
        "Este manual descreve em detalhes a infraestrutura matemática e biológica implementada "
        "na plataforma <b>Saúde Responsiva</b>. O sistema foi projetado para ler dados de wearables redundantes, "
        "remover ruídos físicos causados por movimentação, fundir leituras de sensores de forma ótima via inferência "
        "Bayesiana e estimar variáveis latentes internas (Dados Fantasmas) através de Filtros de Kalman "
        "não-lineares, correlacionando-as com a ontologia de teses de saúde da USP."
    )
    story.append(Paragraph(intro_text, body_style))
    story.append(Spacer(1, 15))
    
    # ── SEÇÃO 1: ORNSTEIN-UHLENBECK ──
    story.append(Paragraph("1. Simulação Fisiológica: Processo de Ornstein-Uhlenbeck (OU)", h1_style))
    story.append(Paragraph(
        "A frequência cardíaca e os estados internos do corpo não se comportam como random walks independentes. "
        "Eles possuem mecanismos homeostáticos de autorregulação (feedback autonômico). Modela-se essa dinâmica "
        "usando a Equação Diferencial Estocástica (SDE) de Ornstein-Uhlenbeck:", body_style))
    story.append(Paragraph("dX_t = &theta; * (&mu; - X_t) dt + &sigma; * dW_t", formula_style))
    story.append(Paragraph(
        "Onde: <b>&theta;</b> é a taxa de reversão que determina a velocidade de retorno ao equilíbrio; "
        "<b>&mu;</b> é o setpoint de equilíbrio fisiológico; <b>&sigma;</b> é a volatilidade intrínseca do organismo; "
        "e <b>dW_t</b> é o incremento do processo de Wiener (ruído Browniano).<br/>"
        "<i>Aplicação no código:</i> Implementado na geração de frequência cardíaca artificial "
        "em <code>physiological_signal_model.py</code> e no modelo de transição biológica do Filtro de Kalman em "
        "<code>state_space_model.py</code>.", body_style))
    
    # ── SEÇÃO 2: FUSÃO BAYESIANA ──
    story.append(Paragraph("2. Reconciliação Bayesiana de Sensores (BLUE &amp; EWMA)", h1_style))
    story.append(Paragraph(
        "wearables redundantes possuem diferentes níveis de precisão. O estimador BLUE (Best Linear Unbiased Estimator) "
        "fornece a combinação linear com variância mínima imparcial:", body_style))
    story.append(Paragraph("x_fused = &Sigma; (w_i * z_i)    onde    w_i = (1/&sigma;²_i) / &Sigma;(1/&sigma;²_j)", formula_style))
    story.append(Paragraph(
        "A variância de cada sensor é estimada online pelo desvio quadrático móvel exponencial (EWMA):", body_style))
    story.append(Paragraph("&sigma;²_new = &lambda; * &sigma;²_old + (1 - &lambda;) * (z_t - x_fused)²", formula_style))
    story.append(Paragraph(
        "Onde &lambda; &isin; (0,1) dita o peso do histórico. "
        "<i>Aplicação no código:</i> A classe <code>AdaptiveSensorFusion</code> (em <code>sensor_fusion.py</code>) "
        "ajusta os pesos em tempo real de forma que sensores ruidosos perdem peso instantaneamente.", body_style))
    
    story.append(PageBreak()) # Quebra para a página 2

    # ── SEÇÃO 3: SEPARAÇÃO DE RUÍDO ──
    story.append(Paragraph("3. Separação Física de Ruídos (DWT Wavelet)", h1_style))
    story.append(Paragraph(
        "Para remover artefatos de movimento sem defasar o sinal ou suavizar picos reais (como faz a média móvel), "
        "utilizamos a Decomposição Wavelet Discreta (DWT). O sinal é decomposto e limiarizado suavemente pelo limiar universal:", body_style))
    story.append(Paragraph("&lambda; = &sigma; * sqrt(2 * ln(N))", formula_style))
    story.append(Paragraph(
        "O ruído &sigma; é estimado robustamente no domínio de frequências pela mediana absoluta dos coeficientes (MAD):", body_style))
    story.append(Paragraph("&sigma; = median(|d_1|) / 0.6745", formula_style))
    story.append(Paragraph(
        "<i>Aplicação no código:</i> A classe <code>WaveletDenoiser</code> (em <code>noise_separation.py</code>) "
        "decompõe o sinal em wavelets Daubechies 'db4' para realizar denoising adaptativo.", body_style))

    # ── SEÇÃO 4: KALMAN FILTER (DADOS FANTASMAS) ──
    story.append(Paragraph("4. Estimativa de Sinais Ocultos: Dados Fantasmas via EKF e UKF", h1_style))
    story.append(Paragraph(
        "Os wearables de pulso medem apenas a superfície (frequência cardíaca e temperatura), mas a verdadeira "
        "condição hemodinâmica do paciente depende de estados latentes não-observáveis direta ou continuamente (Dados Fantasmas: "
        "Pressão Sistólica/Diastólica, SpO₂ e Glicose). "
        "Modelamos a fisiologia como um sistema de espaço de estados estimável pelo Filtro de Kalman Estendido (EKF):", body_style))
    story.append(Paragraph(
        "Predição:<br/>"
        "x_pred = f(x_k-1)  |  P_pred = F * P_k-1 * Fᵀ + Q<br/>"
        "Atualização:<br/>"
        "K = P_pred * Hᵀ * (H * P_pred * Hᵀ + R)⁻¹<br/>"
        "x_k = x_pred + K * (z - h(x_pred))  |  P_k = (I - K * H) * P_pred",
        formula_style
    ))
    story.append(Paragraph(
        "Onde <b>F</b> e <b>H</b> são as matrizes Jacobianas analíticas lineares de transição e observação fisiológica. "
        "O envelope de variância diagonal de <b>P_k</b> fornece o intervalo de confiança dinâmico da estimativa fantasma.<br/>"
        "<i>Aplicação no código:</i> Mapeado nas classes <code>ExtendedKalmanFilter</code> e <code>UnscentedKalmanFilter</code> "
        "em <code>state_space_model.py</code>.", body_style))

    story.append(PageBreak()) # Quebra para a página 3

    # ── SEÇÃO 5: DISTÂNCIA DE MAHALANOBIS ──
    story.append(Paragraph("5. Anomalias Fisiológicas (Distância de Mahalanobis)", h1_style))
    story.append(Paragraph(
        "Diferente da distância Euclidiana clássica, a distância de Mahalanobis leva em consideração a covariância "
        "e correlação mútua das features de saúde:", body_style))
    story.append(Paragraph("D_M(x) = sqrt( (x - &mu;)ᵀ * &Sigma;⁻¹ * (x - &mu;) )", formula_style))
    story.append(Paragraph(
        "A distância quadrática D_M² obedece a uma distribuição de Qui-Quadrado (&chi;²). Medimos a probabilidade (p-value) "
        "de a leitura atual ocorrer sob condições basais normais. Se o p-value &lt; 0.01, classificamos como anômalo.", body_style))

    # ── SEÇÃO 6: PONTE BAYESIANA E ONTOLOGIA ──
    story.append(Paragraph("6. Rede Diagnóstica Bayesiana &amp; Ontologia USP", h1_style))
    story.append(Paragraph(
        "A inferência clínica é efetuada no espaço de probabilidade posterior das patologias (\(C_i\)) usando "
        "as variáveis fantasmas estimadas \(\mathbf{x}\) e métricas de HRV:", body_style))
    story.append(Paragraph("P(C_i | x) = P(x | C_i) * P(C_i) / &Sigma; [ P(x | C_j) * P(C_j) ]", formula_style))
    story.append(Paragraph(
        "A verossimilhança gaussiana de risco é modulada a partir da distância das estimativas aos limites normais "
        "da ontologia de teses da USP (como a faixa saudável de pressão arterial sistólica 90–140 mmHg):", body_style))
    story.append(Paragraph("P(x_k | C_i) &prop; exp( - dist(x_k, [L_L, L_U])² / (2 * &sigma;_tol²) )", formula_style))
    story.append(Paragraph(
        "<i>Aplicação no código:</i> A classe <code>BayesianDiagnosticNetwork</code> calcula e atualiza as "
        "probabilidades sob demanda, vinculando o diagnóstico a códigos de faturamento de saúde (ICD-10, SNOMED, MeSH).", body_style))
    
    # Rodapé de assinatura
    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>HealthTech Biomedical Platform</b> — Departamento de Engenharia de Algoritmos", subtitle_style))

    # Construir PDF
    doc.build(story)
    print(f"Documento PDF criado com sucesso em: {local_pdf_path}")
    
    # Copiar para diretório de artefatos
    artifact_pdf_path = os.path.join(ARTIFACTS_DIR, pdf_filename)
    shutil.copy2(local_pdf_path, artifact_pdf_path)
    print(f"Cópia de PDF salva no repositório de artefatos: {artifact_pdf_path}")


if __name__ == "__main__":
    generate_svg()
    generate_pdf()
