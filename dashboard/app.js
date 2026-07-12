/* ==========================================================================
   HealthTech Telemetry Dashboard JS — Chart.js & WebSocket Integration
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    // Configurações Globais
    const API_URL = "http://127.0.0.1:8000";
    const WS_URL = "ws://127.0.0.1:8000/ws/telemetry";
    let ws = null;
    let isConnected = false;

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
            text.textContent = "Conectado";
            isConnected = true;
        } else if (status === "connecting") {
            indicator.className = "status-indicator yellow";
            text.textContent = "Conectando...";
            isConnected = false;
        } else {
            indicator.className = "status-indicator red";
            text.textContent = "Desconectado";
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
            btnStart.disabled = false;
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            
            // Tratar mensagem de configuração inicial ou confirmação de estado
            if (data.type === "config") {
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
        if (isRunning) {
            btnStart.disabled = true;
            btnStop.disabled = false;
            btnStart.classList.add("active");
        } else {
            btnStart.disabled = false;
            btnStop.disabled = true;
            btnStart.classList.remove("active");
        }

        filterSelect.value = filterType;
        kalmanSelect.value = useUkf ? "UKF" : "EKF";
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
            const response = await fetch(`${API_URL}/api/search`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
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

    // Logger Simples
    const logger = {
        info: (msg) => console.log(`%c[INFO] ${msg}`, "color: #0ea5e9"),
        warning: (msg) => console.warn(`[WARN] ${msg}`),
        error: (msg) => console.error(`[ERROR] ${msg}`)
    };

    // Conectar ao WebSocket na inicialização
    connectWebSocket();
});
