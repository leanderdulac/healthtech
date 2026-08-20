/* ==========================================================================
   HealthTech Telemetry Dashboard JS — Chart.js & WebSocket Integration
   ========================================================================== */

// Função Global de Alternância de Abas
window.switchTab = function(targetTab) {
    const navButtons = document.querySelectorAll(".nav-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    
    navButtons.forEach(b => b.classList.remove("active"));
    tabContents.forEach(c => {
        c.classList.remove("active");
        c.style.display = "none";
    });

    const activeBtn = document.querySelector(`.nav-btn[data-tab="${targetTab}"]`);
    if (activeBtn) activeBtn.classList.add("active");

    const activeContent = document.getElementById(`view-${targetTab}`);
    if (activeContent) {
        activeContent.classList.add("active");
        activeContent.style.display = "block";
    }
};

document.addEventListener("DOMContentLoaded", () => {
    // Configurações Globais (Detecção dinâmica de host para ambiente local ou Cloud Run)
    const CLOUD_RUN_URL = "https://healthtech-responsive-5794833455.us-central1.run.app";
    const CLOUD_RUN_HOST = "healthtech-responsive-5794833455.us-central1.run.app";

    const protocol = window.location.protocol;
    const host = window.location.host;
    const isHttps = protocol === "https:";
    const urlParams = new URLSearchParams(window.location.search);
    // Nunca embutir chave real no frontend versionado — use ?api_key= ou localStorage
    const apiKey = urlParams.get("api_key") || localStorage.getItem("api_key") || "";
    if (urlParams.get("api_key")) {
        try { localStorage.setItem("api_key", urlParams.get("api_key")); } catch (_) { /* ignore */ }
    }

    let API_URL = `${protocol}//${host}`;
    let WS_HOST = host;
    const SECURE_CLOUD_URL =
        "https://healthtech-secure-api-5794833455.us-central1.run.app";
    const isCloudRunHost = host.includes(".run.app");
    // App mobile de produção grava na secure-api (memória separada do monólito full)
    const defaultConnSource = isCloudRunHost ? "secure" : "local";

    // Fallback automático para o Cloud Run se aberto como arquivo local (file://) ou sem host válido
    if (protocol === "file:" || !host || host === "" || host.includes("null")) {
        API_URL = CLOUD_RUN_URL;
        WS_HOST = CLOUD_RUN_HOST;
    }

    const WS_URL = `${WS_HOST.includes(".run.app") || isHttps ? "wss:" : "ws:"}//${WS_HOST}/ws/telemetry${apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : ""}`;
    let ws = null;
    let isConnected = false;
    let wsAuthMode = apiKey ? "control" : "viewer";

    // Buffer de dados históricos para os gráficos (máximo 30 pontos)
    const MAX_POINTS = 30;
    const chartLabels = [];
    const hrData = { raw_watch: [], raw_band: [], clean: [] };
    const bpData = { sbp: [], sbp_low: [], sbp_up: [], dbp: [], dbp_low: [], dbp_up: [] };
    const oxData = { spo2: [], spo2_low: [], spo2_up: [], glucose: [], glucose_low: [], glucose_up: [] };

    // Elementos do DOM — Status e Controles
    const wsStatusIndicator = document.getElementById("ws-status");
    const btnStart = document.getElementById("btn-start");
    const btnStop = document.getElementById("btn-stop");
    const filterSelect = document.getElementById("filter-select");
    const kalmanSelect = document.getElementById("kalman-select");

    // Elementos do DOM — Métricas
    const valBpm = document.getElementById("val-bpm");
    const subBpm = document.getElementById("sub-bpm");
    const valBp = document.getElementById("val-bp");
    const subBp = document.getElementById("sub-bp");
    const valSpo2 = document.getElementById("val-spo2");
    const subSpo2 = document.getElementById("sub-spo2");
    const valGlucose = document.getElementById("val-glucose");
    const subGlucose = document.getElementById("sub-glucose");

    // Elementos do DOM — Ontologia
    const barCardio = document.getElementById("bar-cardiovascular");
    const pctCardio = document.getElementById("pct-cardiovascular");
    const barResp = document.getElementById("bar-respiratory");
    const pctResp = document.getElementById("pct-respiratory");
    const barMetabolic = document.getElementById("bar-metabolic");
    const pctMetabolic = document.getElementById("pct-metabolic");
    const barNeuro = document.getElementById("bar-neurological");
    const pctNeuro = document.getElementById("pct-neurological");

    const badgesIcd10 = document.getElementById("badges-icd10");
    const badgesSnomed = document.getElementById("badges-snomed");
    const badgesMesh = document.getElementById("badges-mesh");

    // Elementos do DOM — Busca RAG
    const searchInput = document.getElementById("search-input");
    const btnSearch = document.getElementById("btn-search");
    const searchResultsBox = document.getElementById("search-results-box");

    // ========================================================================
    // 1. INICIALIZAÇÃO DOS GRÁFICOS (Chart.js com Estética Dark Mode)
    // ========================================================================
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        scales: {
            x: {
                grid: { color: "rgba(255, 255, 255, 0.05)" },
                ticks: { color: "#94a3b8", font: { family: "Outfit" } }
            },
            y: {
                grid: { color: "rgba(255, 255, 255, 0.05)" },
                ticks: { color: "#94a3b8", font: { family: "Outfit" } }
            }
        },
        plugins: {
            legend: {
                labels: { color: "#e2e8f0", font: { family: "Outfit", size: 11 } }
            }
        }
    };

    // Gráfico 1: Heart Rate
    const ctxHr = document.getElementById("chart-hr").getContext("2d");
    const chartHr = new Chart(ctxHr, {
        type: "line",
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: "BPM Bruto (Watch)",
                    data: hrData.raw_watch,
                    borderColor: "rgba(239, 68, 68, 0.35)",
                    borderWidth: 1.5,
                    borderDash: [3, 3],
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "BPM Reconciliado & Filtrado",
                    data: hrData.clean,
                    borderColor: "#0ea5e9",
                    borderWidth: 2.5,
                    fill: false,
                    tension: 0.1,
                    pointRadius: 1,
                    shadowColor: "rgba(14, 165, 233, 0.4)",
                    shadowBlur: 10
                }
            ]
        },
        options: chartOptions
    });

    // Gráfico 2: Pressão Arterial (PAS/PAD)
    const ctxBp = document.getElementById("chart-bp").getContext("2d");
    const chartBp = new Chart(ctxBp, {
        type: "line",
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: "Sistólica (PAS) Estimada",
                    data: bpData.sbp,
                    borderColor: "#38bdf8",
                    borderWidth: 2,
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "PAS CI Inferior",
                    data: bpData.sbp_low,
                    borderColor: "rgba(56, 189, 248, 0.2)",
                    borderWidth: 1,
                    borderDash: [4, 4],
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "PAS CI Superior",
                    data: bpData.sbp_up,
                    borderColor: "rgba(56, 189, 248, 0.2)",
                    borderWidth: 1,
                    borderDash: [4, 4],
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "Diastólica (PAD) Estimada",
                    data: bpData.dbp,
                    borderColor: "#34d399",
                    borderWidth: 2,
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "PAD CI Inferior",
                    data: bpData.dbp_low,
                    borderColor: "rgba(52, 211, 153, 0.2)",
                    borderWidth: 1,
                    borderDash: [4, 4],
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "PAD CI Superior",
                    data: bpData.dbp_up,
                    borderColor: "rgba(52, 211, 153, 0.2)",
                    borderWidth: 1,
                    borderDash: [4, 4],
                    fill: false,
                    pointRadius: 0
                }
            ]
        },
        options: chartOptions
    });

    // Gráfico 3: Oxigênio & Glicose (Eixo Duplo)
    const ctxOxygen = document.getElementById("chart-oxygen").getContext("2d");
    const oxOptions = JSON.parse(JSON.stringify(chartOptions));
    oxOptions.scales.y.title = { display: true, text: "SpO₂ (%)", color: "#f59e0b" };
    
    // Adicionar eixo Y secundário para Glicose
    oxOptions.scales.yGlucose = {
        type: "linear",
        position: "right",
        grid: { drawOnChartArea: false }, // Não sobrepor linhas de grade
        title: { display: true, text: "Glicose (mg/dL)", color: "#ef4444" },
        ticks: { color: "#94a3b8", font: { family: "Outfit" } }
    };

    const chartOxygen = new Chart(ctxOxygen, {
        type: "line",
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: "SpO₂ (%)",
                    data: oxData.spo2,
                    borderColor: "#fbbf24",
                    borderWidth: 2,
                    yAxisID: "y",
                    fill: false,
                    pointRadius: 0
                },
                {
                    label: "Glicose (mg/dL)",
                    data: oxData.glucose,
                    borderColor: "#ef4444",
                    borderWidth: 2,
                    yAxisID: "yGlucose",
                    fill: false,
                    pointRadius: 0
                }
            ]
        },
        options: oxOptions
    });


    // ========================================================================
    // 2. CONEXÃO WEBSOCKET E COMUNICAÇÃO BIDIRECIONAL
    // ========================================================================
    function updateStatusIndicator(status) {
        wsStatusIndicator.className = "connection-status";
        const indicator = wsStatusIndicator.querySelector(".status-indicator");
        const text = wsStatusIndicator.querySelector(".status-text");

        if (status === "connected") {
            indicator.className = "status-indicator green";
            text.textContent =
                wsAuthMode === "viewer" ? "WS conectado (viewer)" : "WS conectado";
            isConnected = true;
        } else if (status === "connecting") {
            indicator.className = "status-indicator yellow";
            text.textContent = "Conectando WS...";
            isConnected = false;
        } else {
            indicator.className = "status-indicator red";
            text.textContent = "WS desconectado";
            isConnected = false;
            // Desativar botões
            btnStart.disabled = true;
            btnStop.disabled = true;
        }
    }

    function connectWebSocket() {
        updateStatusIndicator("connecting");
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            logger.info("Conectado ao WebSocket de Telemetria.");
            updateStatusIndicator("connected");
            // Controles só com chave; viewer pode ver stream
            btnStart.disabled = wsAuthMode === "viewer";
            btnStop.disabled = true;
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.type === "error") {
                logger.warning(data.detail || data.error_code || "Erro WS");
                return;
            }

            // Tratar mensagem de configuração inicial ou confirmação de estado
            if (data.type === "config") {
                if (data.auth_mode) wsAuthMode = data.auth_mode;
                updateStatusIndicator("connected");
                updateUIState(data.is_running, data.filter_type, data.use_ukf);
                return;
            }

            // Tratar telemetria em tempo real
            handleTelemetryFrame(data);
        };

        ws.onclose = () => {
            logger.warning("Conexão WebSocket perdida. Tentando reconectar em 3s...");
            updateStatusIndicator("disconnected");
            setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = (err) => {
            logger.error("Erro na conexão WebSocket: " + err);
            ws.close();
        };
    }

    function updateUIState(isRunning, filterType, useUkf) {
        const canControl = wsAuthMode !== "viewer";
        if (isRunning) {
            btnStart.disabled = true;
            btnStop.disabled = !canControl;
            btnStart.classList.add("active");
        } else {
            btnStart.disabled = !canControl;
            btnStop.disabled = true;
            btnStart.classList.remove("active");
        }

        filterSelect.value = filterType;
        kalmanSelect.value = useUkf ? "UKF" : "EKF";
        filterSelect.disabled = !canControl;
        kalmanSelect.disabled = !canControl;
    }

    // ========================================================================
    // 3. PROCESSAMENTO DE LEITURA E RENDERIZAÇÃO NO DOM/GRAFICOS
    // ========================================================================
    function handleTelemetryFrame(frame) {
        // A. Atualizar buffers de dados deslizantes (MAX_POINTS)
        const label = frame.step.toString();
        chartLabels.push(label);
        if (chartLabels.length > MAX_POINTS) chartLabels.shift();

        // 1. Frequência Cardíaca
        hrData.raw_watch.push(frame.sensor_readings.pixel_watch_raw);
        hrData.clean.push(frame.sensor_readings.clean_estimate);
        if (hrData.raw_watch.length > MAX_POINTS) {
            hrData.raw_watch.shift();
            hrData.clean.shift();
        }

        // 2. Pressão Arterial
        const s = frame.phantom_data.systolic_bp;
        const d = frame.phantom_data.diastolic_bp;
        bpData.sbp.push(s.estimate);
        bpData.sbp_low.push(s.ci_lower);
        bpData.sbp_up.push(s.ci_upper);
        bpData.dbp.push(d.estimate);
        bpData.dbp_low.push(d.ci_lower);
        bpData.dbp_up.push(d.ci_upper);

        if (bpData.sbp.length > MAX_POINTS) {
            bpData.sbp.shift(); bpData.sbp_low.shift(); bpData.sbp_up.shift();
            bpData.dbp.shift(); bpData.dbp_low.shift(); bpData.dbp_up.shift();
        }

        // 3. SpO2 & Glicose
        const o = frame.phantom_data.spo2;
        const g = frame.phantom_data.glucose;
        oxData.spo2.push(o.estimate);
        oxData.spo2_low.push(o.ci_lower);
        oxData.spo2_up.push(o.ci_upper);
        oxData.glucose.push(g.estimate);
        oxData.glucose_low.push(g.ci_lower);
        oxData.glucose_up.push(g.ci_upper);

        if (oxData.spo2.length > MAX_POINTS) {
            oxData.spo2.shift(); oxData.spo2_low.shift(); oxData.spo2_up.shift();
            oxData.glucose.shift(); oxData.glucose_low.shift(); oxData.glucose_up.shift();
        }

        // B. Atualizar Instâncias de Gráficos Chart.js
        chartHr.update();
        chartBp.update();
        chartOxygen.update();

        // C. Atualizar Métricas Textuais no DOM
        // BPM
        valBpm.textContent = Math.round(frame.sensor_readings.clean_estimate);
        const pwWeight = Math.round(frame.sensor_weights.pixel_watch * 100);
        const fbWeight = Math.round(frame.sensor_weights.fitbit_band * 100);
        subBpm.textContent = `Pesos: Watch (${pwWeight}%) | Band (${fbWeight}%)`;

        // Pressão Arterial
        valBp.textContent = `${Math.round(s.estimate)} / ${Math.round(d.estimate)}`;
        subBp.textContent = `Intervalo PAS: (${Math.round(s.ci_lower)} - ${Math.round(s.ci_upper)})`;

        // SpO2
        valSpo2.textContent = o.estimate.toFixed(1);
        subSpo2.textContent = o.reliable ? "Sinal Válido ✓" : "Incerteza Alta ⚠️";
        subSpo2.className = o.reliable ? "metric-sub text-green" : "metric-sub text-red";

        // Glicose
        valGlucose.textContent = Math.round(g.estimate);
        subGlucose.textContent = g.reliable ? "Sinal Válido ✓" : "Incerteza Alta ⚠️";

        // D. Atualizar Probabilidades da Rede Bayesiana (Barras)
        frame.hypotheses.forEach(h => {
            const pct = (h.probability * 100).toFixed(1) + "%";
            const width = (h.probability * 100) + "%";
            
            if (h.category === "cardiovascular") {
                barCardio.style.width = width;
                pctCardio.textContent = pct;
            } else if (h.category === "respiratory") {
                barResp.style.width = width;
                pctResp.textContent = pct;
            } else if (h.category === "metabolic") {
                barMetabolic.style.width = width;
                pctMetabolic.textContent = pct;
            } else if (h.category === "neurological_autonomic") {
                barNeuro.style.width = width;
                pctNeuro.textContent = pct;
            }
        });

        // E. Atualizar Badges de Códigos Clínicos (Interoperabilidade)
        updateBadges(badgesIcd10, frame.clinical_codes.icd10);
        updateBadges(badgesSnomed, frame.clinical_codes.snomed);
        updateBadges(badgesMesh, frame.clinical_codes.mesh);
    }

    function updateBadges(container, codesArray) {
        container.innerHTML = "";
        if (!codesArray || codesArray.length === 0) {
            container.innerHTML = '<span class="badge-code" style="opacity:0.5;">Nenhum</span>';
            return;
        }
        codesArray.forEach(code => {
            const badge = document.createElement("span");
            badge.className = "badge-code";
            badge.textContent = code;
            container.appendChild(badge);
        });
    }

    // ========================================================================
    // 4. TRATAMENTO DE EVENTOS DOS CONTROLES
    // ========================================================================
    btnStart.addEventListener("click", () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: "start" }));
        }
    });

    btnStop.addEventListener("click", () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: "stop" }));
        }
    });

    filterSelect.addEventListener("change", () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: "set_filter", value: filterSelect.value }));
        }
    });

    kalmanSelect.addEventListener("change", () => {
        if (ws && isConnected) {
            ws.send(JSON.stringify({ action: "set_kalman", value: kalmanSelect.value }));
        }
    });


    // ========================================================================
    // 5. TRATAMENTO DE BUSCA RAG (INTEGRAÇÃO COM SLM)
    // ========================================================================
    async function performSearch() {
        const query = searchInput.value.trim();
        if (!query) return;

        searchResultsBox.innerHTML = '<div class="no-results">🔍 Buscando contexto...</div>';

        try {
            const headers = { "Content-Type": "application/json" };
            if (apiKey) headers["X-API-Key"] = apiKey;

            const response = await fetch(`${API_URL}/api/search`, {
                method: "POST",
                headers: headers,
                body: JSON.stringify({ query: query, n_results: 2 })
            });

            if (!response.ok) throw new Error("Erro na resposta da API.");

            const data = await response.json();
            searchResultsBox.innerHTML = "";

            if (data.results && data.results.length > 0) {
                data.results.forEach(res => {
                    const item = document.createElement("div");
                    item.className = "result-item";
                    
                    const title = document.createElement("div");
                    title.className = "result-title";
                    title.textContent = res.topico_dominante;
                    
                    const meta = document.createElement("div");
                    meta.className = "result-meta";
                    meta.textContent = `Por: ${res.autor} | Dist L2: ${res.distance_l2.toFixed(3)}`;
                    
                    const text = document.createElement("div");
                    text.className = "result-text";
                    text.textContent = res.document.length > 200 ? res.document.substring(0, 200) + "..." : res.document;
                    
                    item.appendChild(title);
                    item.appendChild(meta);
                    item.appendChild(text);
                    searchResultsBox.appendChild(item);
                });
            } else {
                searchResultsBox.innerHTML = '<div class="no-results">Nenhum resultado encontrado.</div>';
            }
        } catch (err) {
            searchResultsBox.innerHTML = `<div class="no-results" style="color:#ef4444;">Erro ao buscar: ${err.message}</div>`;
        }
    }

    btnSearch.addEventListener("click", performSearch);
    searchInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") performSearch();
    });

    // ========================================================================
    // 6. CONTROLADOR DE ABAS DA NAVEGAÇÃO
    // ========================================================================
    const navButtons = document.querySelectorAll(".nav-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    const apiBaseUrlSpan = document.getElementById("api-base-url");
    if (apiBaseUrlSpan) apiBaseUrlSpan.textContent = API_URL;

    navButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.getAttribute("data-tab");
            
            navButtons.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));

            btn.classList.add("active");
            const activeContent = document.getElementById(`view-${targetTab}`);
            if (activeContent) activeContent.classList.add("active");
        });
    });

    // Cópia de API Key
    const btnCopyKey = document.getElementById("btn-copy-key");
    const apiKeyDisplay = document.getElementById("api-key-display");
    const copyFeedback = document.getElementById("copy-feedback");

    if (btnCopyKey && apiKeyDisplay) {
        btnCopyKey.addEventListener("click", () => {
            navigator.clipboard.writeText(apiKeyDisplay.value).then(() => {
                copyFeedback.textContent = "✓ Chave copiada para a área de transferência!";
                setTimeout(() => { copyFeedback.textContent = ""; }, 3000);
            });
        });
    }

    // Testador de Conexão com API
    const btnCheckStatus = document.getElementById("btn-check-status");
    const apiHealthBadge = document.getElementById("api-health-badge");

    if (btnCheckStatus) {
        btnCheckStatus.addEventListener("click", async () => {
            btnCheckStatus.disabled = true;
            btnCheckStatus.innerHTML = '<span class="material-icons-round">hourglass_empty</span> Testando...';
            try {
                const res = await fetch(`${API_URL}/api/health`);
                if (res.ok) {
                    apiHealthBadge.textContent = "Online (200 OK)";
                    apiHealthBadge.className = "badge-status green";
                } else {
                    apiHealthBadge.textContent = `Erro (${res.status})`;
                    apiHealthBadge.className = "badge-status red";
                }
            } catch (e) {
                apiHealthBadge.textContent = "Instável / Off-line";
                apiHealthBadge.className = "badge-status red";
            } finally {
                btnCheckStatus.disabled = false;
                btnCheckStatus.innerHTML = '<span class="material-icons-round">refresh</span> Testar Conexão Agora';
            }
        });
    }

    // ========================================================================
    // 7. SIMULADOR INTERATIVO DE INGESTÃO DE WEARABLE
    // ========================================================================
    const simulatorForm = document.getElementById("simulator-form");
    const simResponseJson = document.getElementById("sim-response-json");

    if (simulatorForm && simResponseJson) {
        simulatorForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const submitBtn = simulatorForm.querySelector("button[type='submit']");
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="material-icons-round">hourglass_empty</span> Processando BMO & EKF...';
            simResponseJson.textContent = "// Enviando requisição de telemetria biométrica...";

            const payload = {
                patient_id: document.getElementById("sim-patient-id").value,
                device_id: document.getElementById("sim-device-id").value,
                heart_rate: parseFloat(document.getElementById("sim-hr").value),
                hrv_rmssd: parseFloat(document.getElementById("sim-hrv").value),
                skin_temp: parseFloat(document.getElementById("sim-temp").value),
                filter_type: document.getElementById("sim-filter").value
            };

            try {
                const res = await fetch(`${API_URL}/api/v1/wearables/ingest`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-API-Key": apiKey
                    },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();
                simResponseJson.textContent = JSON.stringify(data, null, 2);
            } catch (err) {
                simResponseJson.textContent = JSON.stringify({ error: err.message, note: "Verifique se a API está rodando localmente ou no Cloud Run." }, null, 2);
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<span class="material-icons-round">send</span> Enviar Telemetria para API';
            }
        });
    }

    // ========================================================================
    // 8. ALTERNÂNCIA DE SNIPPETS DE CÓDIGO (cURL, Python, JS)
    // ========================================================================
    const codeTabBtns = document.querySelectorAll(".code-tab-btn");
    const codeSnippetBlock = document.getElementById("code-snippet");

    const snippets = {
        curl: `curl -X POST "${API_URL}/api/v1/wearables/ingest" \\
     -H "X-API-Key: healthtech_live_key_2026" \\
     -H "Content-Type: application/json" \\
     -d '{
       "patient_id": "PAT-PULSO-101",
       "device_id": "smartwatch_pulso_v1",
       "heart_rate": 78.5,
       "hrv_rmssd": 42.0,
       "skin_temp": 33.2,
       "filter_type": "BMO"
     }'`,
        python: `import requests

url = "${API_URL}/api/v1/wearables/ingest"
headers = {
    "X-API-Key": "healthtech_live_key_2026",
    "Content-Type": "application/json"
}
payload = {
    "patient_id": "PAT-PULSO-101",
    "device_id": "smartwatch_pulso_v1",
    "heart_rate": 78.5,
    "hrv_rmssd": 42.0,
    "skin_temp": 33.2,
    "filter_type": "BMO"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())`,
        js: `const response = await fetch("${API_URL}/api/v1/wearables/ingest", {
    method: "POST",
    headers: {
        "X-API-Key": "healthtech_live_key_2026",
        "Content-Type": "application/json"
    },
    body: JSON.stringify({
        patient_id: "PAT-PULSO-101",
        device_id: "smartwatch_pulso_v1",
        heart_rate: 78.5,
        hrv_rmssd: 42.0,
        skin_temp: 33.2,
        filter_type: "BMO"
    })
});

const data = await response.json();
console.log(data);`
    };

    codeTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            codeTabBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const lang = btn.getAttribute("data-lang");
            if (codeSnippetBlock && snippets[lang]) {
                codeSnippetBlock.textContent = snippets[lang];
            }
        });
    });

    // Logger Simples
    const logger = {
        info: (msg) => console.log(`%c[INFO] ${msg}`, "color: #0ea5e9"),
        warning: (msg) => console.warn(`[WARN] ${msg}`),
        error: (msg) => console.error(`[ERROR] ${msg}`)
    };

    // ========================================================================
    // 9. CONEXÕES APP MOBILE + DEVICE (HBand) + SYNC DE VITAIS
    // ========================================================================
    const SECURE_DEFAULT = SECURE_CLOUD_URL;
    const CONN_ONLINE_SEC = 30;
    const CONN_POLL_MS = 5000;
    let lastMobileTs = null;

    /**
     * Aplica frame de ingest do companion (schema wearables) nos cards e gráficos.
     * Diferente do frame WebSocket de simulação (sensor_readings / hypotheses).
     */
    function applyMobileIngestToDashboard(frame) {
        if (!frame || typeof frame !== "object") return;
        const ts = frame.timestamp || "";
        if (ts && ts === lastMobileTs) return; // evita replot do mesmo ponto
        lastMobileTs = ts || lastMobileTs;

        const raw = frame.raw_telemetry || {};
        const cleaned = frame.cleaned_telemetry || {};
        const phantom = frame.phantom_data || {};
        const hr =
            cleaned.heart_rate_clean ??
            raw.heart_rate_bpm ??
            frame.heart_rate ??
            null;

        const label = (ts || new Date().toISOString()).slice(11, 19);
        chartLabels.push(label);
        if (chartLabels.length > MAX_POINTS) chartLabels.shift();

        const hrNum = hr != null ? Number(hr) : null;
        hrData.raw_watch.push(hrNum);
        hrData.clean.push(hrNum);
        if (hrData.raw_watch.length > MAX_POINTS) {
            hrData.raw_watch.shift();
            hrData.clean.shift();
        }

        const s = phantom.systolic_bp || {};
        const d = phantom.diastolic_bp || {};
        const sEst = s.estimate != null ? Number(s.estimate) : null;
        const dEst = d.estimate != null ? Number(d.estimate) : null;
        bpData.sbp.push(sEst);
        bpData.sbp_low.push(s.ci_lower != null ? Number(s.ci_lower) : null);
        bpData.sbp_up.push(s.ci_upper != null ? Number(s.ci_upper) : null);
        bpData.dbp.push(dEst);
        bpData.dbp_low.push(d.ci_lower != null ? Number(d.ci_lower) : null);
        bpData.dbp_up.push(d.ci_upper != null ? Number(d.ci_upper) : null);
        if (bpData.sbp.length > MAX_POINTS) {
            bpData.sbp.shift(); bpData.sbp_low.shift(); bpData.sbp_up.shift();
            bpData.dbp.shift(); bpData.dbp_low.shift(); bpData.dbp_up.shift();
        }

        // SpO2: preferir medido; glicose: phantom
        const spo2 =
            raw.spo2_percent != null
                ? Number(raw.spo2_percent)
                : phantom.spo2?.estimate != null
                  ? Number(phantom.spo2.estimate)
                  : null;
        const g = phantom.glucose_mgdl || phantom.glucose || {};
        const gEst = g.estimate != null ? Number(g.estimate) : null;
        oxData.spo2.push(spo2);
        oxData.spo2_low.push(spo2 != null ? spo2 - 1 : null);
        oxData.spo2_up.push(spo2 != null ? spo2 + 1 : null);
        oxData.glucose.push(gEst);
        oxData.glucose_low.push(g.ci_lower != null ? Number(g.ci_lower) : null);
        oxData.glucose_up.push(g.ci_upper != null ? Number(g.ci_upper) : null);
        if (oxData.spo2.length > MAX_POINTS) {
            oxData.spo2.shift(); oxData.spo2_low.shift(); oxData.spo2_up.shift();
            oxData.glucose.shift(); oxData.glucose_low.shift(); oxData.glucose_up.shift();
        }

        chartHr.update();
        chartBp.update();
        chartOxygen.update();

        if (hrNum != null && valBpm) {
            valBpm.textContent = Math.round(hrNum);
            if (subBpm) {
                subBpm.textContent = `App mobile · ${frame.device_id || "device"} · ${ts || "agora"}`;
            }
        }
        if (sEst != null && dEst != null && valBp) {
            valBp.textContent = `${Math.round(sEst)} / ${Math.round(dEst)}`;
            if (subBp) {
                subBp.textContent = `Estimativa via app (phantom) · ${frame.patient_id || ""}`;
            }
        }
        if (spo2 != null && valSpo2) {
            valSpo2.textContent = Number(spo2).toFixed(1);
            if (subSpo2) {
                subSpo2.textContent = "Medido no ingest do app ✓";
                subSpo2.className = "metric-sub text-green";
            }
        }
        if (gEst != null && valGlucose) {
            valGlucose.textContent = Math.round(gEst);
            if (subGlucose) {
                subGlucose.textContent = g.reliable === false ? "Incerteza alta ⚠️" : "Phantom via app ✓";
            }
        }
    }

    async function fetchMobileBridgeSnapshot(patientId) {
        const q = new URLSearchParams({
            patient_id: patientId || "PAT-HBAND-001",
            online_threshold_sec: String(CONN_ONLINE_SEC),
        });
        // same-origin bridge no monólito full (usa READ_API_KEY server-side)
        const res = await fetch(`${API_URL}/api/v1/mobile/bridge/snapshot?${q}`, {
            headers: { Accept: "application/json" },
        });
        if (!res.ok) {
            const err = new Error(`bridge HTTP ${res.status}`);
            err.status = res.status;
            throw err;
        }
        return res.json();
    }

    const connEls = {
        patientId: document.getElementById("conn-patient-id"),
        source: document.getElementById("conn-source"),
        secureUrl: document.getElementById("conn-secure-url"),
        refreshBtn: document.getElementById("btn-refresh-connections"),
        pollHint: document.getElementById("conn-poll-hint"),
        appLabel: document.getElementById("conn-app-label"),
        appMeta: document.getElementById("conn-app-meta"),
        deviceLabel: document.getElementById("conn-device-label"),
        deviceMeta: document.getElementById("conn-device-meta"),
        apiLabel: document.getElementById("conn-api-label"),
        apiMeta: document.getElementById("conn-api-meta"),
        nodeApp: document.getElementById("conn-node-app"),
        nodeDevice: document.getElementById("conn-node-device"),
        nodeApi: document.getElementById("conn-node-api"),
        dotApp: document.getElementById("conn-dot-app"),
        dotDevice: document.getElementById("conn-dot-device"),
        dotApi: document.getElementById("conn-dot-api"),
        linkDeviceApp: document.getElementById("conn-link-device-app"),
        linkAppApi: document.getElementById("conn-link-app-api"),
        linkDeviceCaption: document.getElementById("conn-link-device-caption"),
        linkAppCaption: document.getElementById("conn-link-app-caption"),
        statOnline: document.getElementById("conn-stat-online"),
        statPatients: document.getElementById("conn-stat-patients"),
        statHr: document.getElementById("conn-stat-hr"),
        statDevice: document.getElementById("conn-stat-device"),
        statTs: document.getElementById("conn-stat-ts"),
        statAge: document.getElementById("conn-stat-age"),
        sessionsBody: document.getElementById("conn-sessions-body"),
        roadmap: document.getElementById("conn-roadmap-list"),
    };

    // Prefer patient do companion se já usado em simulação
    try {
        const savedPatient = localStorage.getItem("conn_patient_id");
        if (savedPatient && connEls.patientId) connEls.patientId.value = savedPatient;
        const savedSource = localStorage.getItem("conn_source");
        if (connEls.source) {
            connEls.source.value = savedSource || defaultConnSource;
        }
        const savedSecure = localStorage.getItem("conn_secure_url");
        if (connEls.secureUrl) {
            connEls.secureUrl.value = savedSecure || SECURE_DEFAULT;
        }
    } catch (_) {
        if (connEls.source) connEls.source.value = defaultConnSource;
    }

    function statusDotClass(status) {
        if (status === "online" || status === "ble_hband") return "conn-dot green";
        if (status === "ble_sim" || status === "via_app") return "conn-dot yellow";
        if (status === "idle" || status === "planned") return "conn-dot blue";
        return "conn-dot red";
    }

    function formatAge(sec) {
        if (sec == null || Number.isNaN(sec)) return "—";
        if (sec < 60) return `${Math.round(sec)}s`;
        if (sec < 3600) return `${Math.round(sec / 60)} min`;
        return `${(sec / 3600).toFixed(1)} h`;
    }

    function authHeaders() {
        const h = { Accept: "application/json" };
        if (apiKey) h["X-API-Key"] = apiKey;
        return h;
    }

    async function fetchConnectionStatus(baseUrl) {
        const root = baseUrl.replace(/\/$/, "");
        // Preferir /public (sem auth). Fallback para /status (público ou autenticado).
        const candidates = [
            `${root}/api/v1/connections/public?online_threshold_sec=${CONN_ONLINE_SEC}`,
            `${root}/api/v1/connections/status?online_threshold_sec=${CONN_ONLINE_SEC}`,
        ];
        let lastErr = null;
        for (const url of candidates) {
            try {
                const res = await fetch(url, { headers: authHeaders() });
                if (res.ok) return res.json();
                lastErr = new Error(`HTTP ${res.status}`);
                lastErr.status = res.status;
                // 404 → tentar próximo path
                if (res.status !== 404) break;
            } catch (e) {
                lastErr = e;
            }
        }
        throw lastErr || new Error("Falha ao obter status de conexões");
    }

    async function fetchLatestFallback(baseUrl, patientId) {
        const url = `${baseUrl.replace(/\/$/, "")}/api/v1/wearables/patient/${encodeURIComponent(patientId)}/latest`;
        const res = await fetch(url, { headers: authHeaders() });
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    function synthesizeFromLatest(frame, sourceLabel) {
        if (!frame) {
            return {
                mobile_app: { status: "offline", label: "Sem dados", active_sessions: 0, total_patients: 0, latest: null },
                device: { status: "planned", label: "Aguardando simulador BLE ou HBand", model_hint: null, pairing_ready: false },
                sessions: [],
                source: sourceLabel,
            };
        }
        const ts = frame.timestamp ? new Date(frame.timestamp) : null;
        const age = ts ? (Date.now() - ts.getTime()) / 1000 : null;
        let mobile = "offline";
        if (age != null && age <= CONN_ONLINE_SEC) mobile = "online";
        else if (age != null && age <= 300) mobile = "idle";
        const deviceId = frame.device_id || "—";
        const hr =
            frame.cleaned_telemetry?.heart_rate_clean ??
            frame.raw_telemetry?.heart_rate_bpm ??
            null;
        const session = {
            patient_id: frame.patient_id,
            device_id: deviceId,
            timestamp: frame.timestamp,
            age_seconds: age != null ? Math.round(age * 10) / 10 : null,
            mobile_status: mobile,
            device_status: deviceId && deviceId !== "—" ? "via_app" : "planned",
            heart_rate_bpm: hr,
            samples: 1,
            source: sourceLabel,
        };
        return {
            mobile_app: {
                status: mobile,
                label:
                    mobile === "online"
                        ? "App mobile conectado (ingest ativo)"
                        : mobile === "idle"
                          ? "App mobile com telemetria recente"
                          : "Nenhum ingest recente do app",
                active_sessions: mobile === "online" ? 1 : 0,
                total_patients: 1,
                latest: session,
            },
            device: {
                status: session.device_status === "via_app" ? "via_app" : "planned",
                label:
                    session.device_status === "via_app"
                        ? "Device visto só via ingest HTTP (sem BLE)"
                        : "Aguardando simulador BLE ou HBand",
                model_hint: deviceId,
                pairing_ready: false,
            },
            sessions: [session],
            source: sourceLabel,
        };
    }

    function mergeConnectionPayloads(parts) {
        const sessions = [];
        parts.forEach((p) => {
            (p.sessions || []).forEach((s) => {
                sessions.push({ ...s, source: s.source || p.source || "api" });
            });
        });
        // dedupe by patient+device keeping freshest
        const byKey = new Map();
        sessions.forEach((s) => {
            const key = `${s.patient_id}::${s.device_id}`;
            const prev = byKey.get(key);
            if (!prev || (s.age_seconds ?? 1e12) < (prev.age_seconds ?? 1e12)) {
                byKey.set(key, s);
            }
        });
        const mergedSessions = Array.from(byKey.values()).sort(
            (a, b) => (a.age_seconds ?? 1e12) - (b.age_seconds ?? 1e12)
        );
        const online = mergedSessions.filter((s) => s.mobile_status === "online");
        const idle = mergedSessions.filter((s) => s.mobile_status === "idle");
        const best = online[0] || idle[0] || mergedSessions[0] || null;
        let mobileStatus = "offline";
        if (online.length) mobileStatus = "online";
        else if (idle.length) mobileStatus = "idle";
        else if (mergedSessions.length) mobileStatus = "offline";

        const rank = ["ble_hband", "ble_sim", "via_app"];
        let deviceStatus = "planned";
        for (const wanted of rank) {
            if (mergedSessions.some((s) => s.device_status === wanted && s.mobile_status !== "offline")) {
                deviceStatus = wanted;
                break;
            }
        }
        if (mobileStatus === "offline" && deviceStatus === "planned" && mergedSessions.length) {
            deviceStatus = "offline";
        }

        return {
            mobile_app: {
                status: mobileStatus,
                label: {
                    online: "App mobile conectado (ingest ativo)",
                    idle: "App mobile com telemetria recente",
                    offline: "Nenhum ingest recente do app",
                }[mobileStatus],
                active_sessions: online.length,
                total_patients: new Set(mergedSessions.map((s) => s.patient_id)).size,
                latest: best,
            },
            device: {
                status: deviceStatus,
                label: {
                    ble_hband: "HBand pareado via BLE (SDK)",
                    ble_sim: "Device simulado no companion (não é BLE físico)",
                    via_app: "Device visto só via ingest HTTP (sem BLE)",
                    planned: "Aguardando simulador BLE ou HBand",
                    offline: "Device sem telemetria recente",
                }[deviceStatus],
                model_hint: best?.device_id || null,
                pairing_ready: deviceStatus === "ble_sim" || deviceStatus === "ble_hband",
                ble_physical: deviceStatus === "ble_hband",
                ble_simulated: deviceStatus === "ble_sim",
            },
            sessions: mergedSessions,
            sources: parts.map((p) => p.source).filter(Boolean),
        };
    }

    function setNodeStatus(nodeEl, dotEl, status) {
        if (nodeEl) nodeEl.setAttribute("data-status", status || "offline");
        if (dotEl) dotEl.className = statusDotClass(status);
    }

    function renderConnections(data) {
        if (!connEls.appLabel) return;
        const mobile = data.mobile_app || {};
        const device = data.device || {};
        const latest = mobile.latest || null;

        connEls.appLabel.textContent = mobile.label || mobile.status || "—";
        connEls.deviceLabel.textContent = device.label || device.status || "—";
        setNodeStatus(connEls.nodeApp, connEls.dotApp, mobile.status);
        setNodeStatus(connEls.nodeDevice, connEls.dotDevice, device.status);
        setNodeStatus(connEls.nodeApi, connEls.dotApi, "online");

        if (connEls.linkAppApi) {
            connEls.linkAppApi.classList.toggle("active", mobile.status === "online" || mobile.status === "idle");
            connEls.linkAppApi.classList.toggle("planned", false);
        }
        if (connEls.linkDeviceApp) {
            const live = ["ble_sim", "ble_hband", "via_app"].includes(device.status);
            connEls.linkDeviceApp.classList.toggle("active", live && mobile.status !== "offline");
            connEls.linkDeviceApp.classList.toggle("planned", device.status === "planned");
        }
        if (connEls.linkDeviceCaption) {
            connEls.linkDeviceCaption.textContent = {
                ble_hband: "BLE HBand",
                ble_sim: "simulado",
                via_app: "HTTP",
                planned: "device → app",
                offline: "offline",
            }[device.status] || "device → app";
        }
        if (connEls.linkAppCaption) {
            connEls.linkAppCaption.textContent =
                mobile.status === "online" ? "ingest" : "HTTPS";
        }

        const sources = data.sources || [data.source].filter(Boolean);
        connEls.apiLabel.textContent = sources.length
            ? `Fonte: ${sources.join(" + ")}`
            : "API Healthtech";
        connEls.apiMeta.textContent = API_URL;
        connEls.appMeta.textContent =
            mobile.status === "online"
                ? `Sessões ativas: ${mobile.active_sessions || 0}`
                : "OkHttp → POST /wearables/ingest";
        connEls.deviceMeta.textContent = device.model_hint
            ? `device_id: ${device.model_hint}`
            : "Protocolo planejado: BLE GATT / HBand SDK";

        if (connEls.statOnline) connEls.statOnline.textContent = String(mobile.active_sessions ?? 0);
        if (connEls.statPatients) connEls.statPatients.textContent = String(mobile.total_patients ?? 0);
        if (connEls.statHr) {
            const hr = latest?.heart_rate_bpm;
            connEls.statHr.textContent = hr != null ? `${Math.round(hr)} bpm` : "—";
        }
        if (connEls.statDevice) connEls.statDevice.textContent = latest?.device_id || device.model_hint || "—";
        if (connEls.statTs) connEls.statTs.textContent = latest?.timestamp || "—";
        if (connEls.statAge) connEls.statAge.textContent = formatAge(latest?.age_seconds);

        // Prefer patient filter for table highlight
        const focusPatient = (connEls.patientId?.value || "").trim();
        const rows = (data.sessions || []).slice(0, 12);
        if (connEls.sessionsBody) {
            if (!rows.length) {
                connEls.sessionsBody.innerHTML =
                    '<tr class="empty-row"><td colspan="7">Nenhuma sessão de ingest ainda. Envie telemetria pelo app ou simulador.</td></tr>';
            } else {
                connEls.sessionsBody.innerHTML = rows
                    .map((s) => {
                        const focus =
                            focusPatient && s.patient_id === focusPatient
                                ? ' style="background:rgba(14,165,233,0.08)"'
                                : "";
                        return `<tr${focus}>
                            <td>${s.patient_id || "—"}</td>
                            <td>${s.device_id || "—"}</td>
                            <td><span class="pill ${s.mobile_status || "offline"}">${s.mobile_status || "—"}</span></td>
                            <td><span class="pill ${s.device_status || "planned"}">${s.device_status || "—"}</span></td>
                            <td>${s.heart_rate_bpm != null ? Math.round(s.heart_rate_bpm) : "—"}</td>
                            <td>${formatAge(s.age_seconds)}</td>
                            <td>${s.source || "—"}</td>
                        </tr>`;
                    })
                    .join("");
            }
        }

        if (connEls.roadmap) {
            const items = device.roadmap;
            if (Array.isArray(items) && items.length && typeof items[0] === "object") {
                connEls.roadmap.innerHTML = items.map((it) =>
                    `<li class="${it.done ? "done" : "todo"}">${it.label}</li>`
                ).join("");
            } else {
                connEls.roadmap.innerHTML = `
                    <li class="done">App envia telemetria via HTTPS (ingest)</li>
                    <li class="${device.ble_simulated ? "done" : "todo"}">Simulador BLE no companion</li>
                    <li class="${device.ble_physical ? "done" : "todo"}">Pairing HBand real (SDK + pulseira)</li>
                    <li class="done">Dashboard distingue simulado vs BLE físico</li>
                `;
            }
        }
    }

    async function refreshConnections() {
        if (!connEls.appLabel) return;
        const source = connEls.source?.value || defaultConnSource;
        const patientId = (connEls.patientId?.value || "PAT-HBAND-001").trim();
        const secureUrl = (connEls.secureUrl?.value || SECURE_DEFAULT).trim();

        try {
            localStorage.setItem("conn_patient_id", patientId);
            localStorage.setItem("conn_source", source);
            localStorage.setItem("conn_secure_url", secureUrl);
        } catch (_) { /* ignore */ }

        if (connEls.pollHint) connEls.pollHint.textContent = "Sincronizando app mobile…";
        const parts = [];
        let bridgeLatest = null;

        // 1) Bridge same-origin (preferido em Cloud Run): secure-api via monólito
        try {
            const snap = await fetchMobileBridgeSnapshot(patientId);
            if (snap.connections) {
                const c = snap.connections;
                c.source = c.source || "secure-cloud-bridge";
                parts.push(c);
            }
            if (snap.latest) {
                bridgeLatest = snap.latest;
                applyMobileIngestToDashboard(snap.latest);
            }
            if (snap.errors?.length) {
                logger.warning("Bridge: " + snap.errors.join("; "));
            }
        } catch (bridgeErr) {
            logger.warning(`Bridge mobile indisponível: ${bridgeErr.message}`);
        }

        async function loadOne(base, label) {
            try {
                const data = await fetchConnectionStatus(base);
                data.source = label;
                if (patientId && (!data.sessions || !data.sessions.length)) {
                    const latest = await fetchLatestFallback(base, patientId);
                    if (latest) {
                        if (!bridgeLatest) applyMobileIngestToDashboard(latest);
                        return synthesizeFromLatest(latest, label);
                    }
                }
                (data.sessions || []).forEach((s) => {
                    s.source = s.source || label;
                });
                return data;
            } catch (err) {
                if (err.status === 404 || err.status === 405) {
                    try {
                        const latest = await fetchLatestFallback(base, patientId);
                        if (latest && !bridgeLatest) applyMobileIngestToDashboard(latest);
                        return synthesizeFromLatest(latest, label);
                    } catch (e2) {
                        logger.warning(`Conexões (${label}): ${e2.message}`);
                        return synthesizeFromLatest(null, label);
                    }
                }
                logger.warning(`Conexões (${label}): ${err.message}`);
                return synthesizeFromLatest(null, label);
            }
        }

        // 2) Fontes extras conforme seletor (se bridge falhou ou usuário pediu both/local)
        if (!parts.length || source === "local" || source === "both") {
            if (source === "local" || source === "both") {
                parts.push(await loadOne(API_URL, "local"));
            }
        }
        if (!parts.length || source === "secure" || source === "both") {
            // Cross-origin direto na secure (CORS liberado)
            if (source === "secure" || source === "both" || !parts.length) {
                parts.push(await loadOne(secureUrl, "secure-cloud"));
            }
        }

        const merged =
            parts.length === 1
                ? { ...parts[0], sources: [parts[0].source || "api"] }
                : mergeConnectionPayloads(parts);

        if (bridgeLatest && merged.mobile_app) {
            // Garante latest rico no painel
            const ageSec = bridgeLatest.timestamp
                ? (Date.now() - new Date(bridgeLatest.timestamp).getTime()) / 1000
                : null;
            merged.mobile_app.latest = {
                ...(merged.mobile_app.latest || {}),
                patient_id: bridgeLatest.patient_id,
                device_id: bridgeLatest.device_id,
                timestamp: bridgeLatest.timestamp,
                age_seconds: ageSec != null ? Math.round(ageSec * 10) / 10 : null,
                heart_rate_bpm:
                    bridgeLatest.cleaned_telemetry?.heart_rate_clean ??
                    bridgeLatest.raw_telemetry?.heart_rate_bpm,
                spo2_percent: bridgeLatest.raw_telemetry?.spo2_percent,
                mobile_status:
                    ageSec != null && ageSec <= CONN_ONLINE_SEC
                        ? "online"
                        : ageSec != null && ageSec <= 300
                          ? "idle"
                          : "offline",
                device_status: "via_app",
                source: "secure-cloud-bridge",
            };
            if (merged.mobile_app.latest.mobile_status === "online") {
                merged.mobile_app.status = "online";
                merged.mobile_app.label = "App mobile conectado (ingest ativo)";
                merged.mobile_app.active_sessions = Math.max(
                    1,
                    merged.mobile_app.active_sessions || 0
                );
            }
            if (merged.device) {
                merged.device.status = "via_app";
                merged.device.model_hint = bridgeLatest.device_id;
                merged.device.label = "Device visto via app companion";
            }
        }

        if (patientId && merged.sessions?.length) {
            const focus = merged.sessions.find((s) => s.patient_id === patientId);
            if (focus && merged.mobile_app && !bridgeLatest) {
                merged.mobile_app.latest = focus;
            }
        }

        renderConnections(merged);
        if (connEls.pollHint) {
            const t = new Date().toLocaleTimeString();
            const live = bridgeLatest ? " · vitais do app" : "";
            connEls.pollHint.textContent = `Atualizado ${t} · a cada ${CONN_POLL_MS / 1000}s${live}`;
        }
    }

    if (connEls.refreshBtn) {
        connEls.refreshBtn.addEventListener("click", () => refreshConnections());
    }
    ["change", "blur"].forEach((ev) => {
        connEls.source?.addEventListener(ev, () => refreshConnections());
        connEls.patientId?.addEventListener(ev, () => refreshConnections());
        connEls.secureUrl?.addEventListener(ev, () => refreshConnections());
    });

    // Conectar ao WebSocket na inicialização
    connectWebSocket();

    // Poll de conexões mobile/device
    refreshConnections();
    setInterval(refreshConnections, CONN_POLL_MS);
});

