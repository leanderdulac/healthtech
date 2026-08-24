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

    if (targetTab === "biophysics" && typeof window.initBiophysicsView === "function") {
        window.initBiophysicsView();
    }
    if (targetTab === "billing" && typeof window.initGcpBilling === "function") {
        window.initGcpBilling();
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
    let apiKey = urlParams.get("api_key") || localStorage.getItem("api_key") || "";
    
    let API_URL = `${protocol}//${host}`;
    let WS_HOST = host;

    // Fallback automático para o Cloud Run se aberto como arquivo local (file://) ou sem host válido
    if (protocol === "file:" || !host || host === "" || host.includes("null")) {
        API_URL = CLOUD_RUN_URL;
        WS_HOST = CLOUD_RUN_HOST;
    }

    function wsUrl() {
        const scheme = WS_HOST.includes(".run.app") || isHttps ? "wss:" : "ws:";
        const keyQs = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : "";
        return `${scheme}//${WS_HOST}/ws/telemetry${keyQs}`;
    }
    let ws = null;
    let isConnected = false;
    let reconnectTimer = null;
    let devicePollTimer = null;
    let lastIngestStamp = "";
    let fleetDevices = [];
    let selectedDeviceId = "";
    let fleetPage = 0;
    const FLEET_PAGE_SIZE = 50;
    const DISPLAY_TZ = "America/Sao_Paulo";
    const localDateFmt = new Intl.DateTimeFormat("pt-BR", {
        timeZone: DISPLAY_TZ,
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });
    const localClockFmt = new Intl.DateTimeFormat("pt-BR", {
        timeZone: DISPLAY_TZ,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });

    function parseStamp(value) {
        if (!value) return null;
        if (/^\d{2}\/\d{2}\/\d{4}/.test(String(value))) return null;
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? null : d;
    }

    function formatLocal(value) {
        if (!value) return "—";
        if (/^\d{2}\/\d{2}\/\d{4}/.test(String(value))) return String(value);
        const d = parseStamp(value);
        return d ? localDateFmt.format(d) : "—";
    }

    function formatClock(value) {
        const d = parseStamp(value) || new Date();
        return localClockFmt.format(d);
    }

    function formatAge(value) {
        const d = parseStamp(value);
        if (!d) return "";
        const sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
        if (sec < 4) return "agora";
        if (sec < 60) return `há ${sec}s`;
        if (sec < 3600) return `há ${Math.floor(sec / 60)} min`;
        return `há ${Math.floor(sec / 3600)} h`;
    }

    function liveStamp(rowOrFrame) {
        return rowOrFrame.received_at || rowOrFrame.last_seen || rowOrFrame.timestamp || "";
    }

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
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (!apiKey) {
            updateStatusIndicator("disconnected");
            const hint = document.getElementById("watch-sub");
            if (hint) hint.textContent = "Informe a API key no canto superior para ver o relógio.";
            return;
        }
        updateStatusIndicator("connecting");
        try {
            if (ws) {
                ws.onclose = null;
                ws.close();
            }
        } catch (err) {
            /* ignore */
        }
        ws = new WebSocket(wsUrl());

        ws.onopen = () => {
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
            if (data.type === "patient_ingest") {
                applyIngestFrame(data.data || data);
                return;
            }
            if (data && data.sensor_readings) {
                handleTelemetryFrame(data);
            }
        };

        ws.onclose = () => {
            updateStatusIndicator("disconnected");
            if (!apiKey) return;
            reconnectTimer = setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = () => {
            if (ws) ws.close();
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
    function phantomOr(value, fallback) {
        if (value && typeof value.estimate === "number") return value;
        return {
            estimate: fallback,
            ci_lower: fallback,
            ci_upper: fallback,
            reliable: fallback != null
        };
    }

    function applyIngestFrame(ing) {
        if (!ing) return;
        const deviceId = ing.device_id || "";
        if (deviceId && !selectedDeviceId) selectedDeviceId = deviceId;
        if (selectedDeviceId && deviceId && deviceId !== selectedDeviceId) {
            upsertFleetFromIngest(ing);
            return;
        }
        const stamp = `${deviceId}|${liveStamp(ing)}`;
        renderWatchFromIngest(ing);
        upsertFleetFromIngest(ing);
        if (stamp && stamp === lastIngestStamp) return;
        lastIngestStamp = stamp;
        const raw = ing.raw_telemetry || {};
        const cleaned = ing.cleaned_telemetry || {};
        const ph = ing.phantom_data || {};
        const hr = Number(cleaned.heart_rate_clean != null ? cleaned.heart_rate_clean : raw.heart_rate_bpm);
        const spo2Val = raw.spo2_percent;
        const frame = {
            step: formatClock(liveStamp(ing)),
            sensor_readings: {
                pixel_watch_raw: Number(raw.heart_rate_bpm != null ? raw.heart_rate_bpm : hr),
                fitbit_band_raw: Number(raw.heart_rate_bpm != null ? raw.heart_rate_bpm : hr),
                fused_estimate: hr,
                clean_estimate: hr
            },
            sensor_weights: { pixel_watch: 1, fitbit_band: 0 },
            phantom_data: {
                systolic_bp: phantomOr(ph.systolic_bp, null),
                diastolic_bp: phantomOr(ph.diastolic_bp, null),
                spo2: phantomOr(ph.spo2, spo2Val == null ? null : Number(spo2Val)),
                glucose: phantomOr(ph.glucose || ph.glucose_mgdl, null)
            },
            hypotheses: ing.hypotheses || ing.diagnostic_hypotheses || [],
            clinical_codes: ing.clinical_codes || {}
        };
        if (!Number.isFinite(hr)) return;
        handleTelemetryFrame(frame);
    }

    function renderWatchFromIngest(ing) {
        const name = document.getElementById("watch-name");
        const sub = document.getElementById("watch-sub");
        const card = document.getElementById("card-watch");
        if (!name || !sub) return;
        const hr = (ing.cleaned_telemetry || {}).heart_rate_clean ?? (ing.raw_telemetry || {}).heart_rate_bpm;
        const spo2 = (ing.raw_telemetry || {}).spo2_percent;
        name.textContent = ing.device_id || "VE30";
        const bits = [];
        if (hr != null) bits.push(`${Math.round(Number(hr))} BPM`);
        if (spo2 != null) bits.push(`SpO₂ ${Number(spo2).toFixed(0)}%`);
        const when = ing.last_seen_local || formatLocal(liveStamp(ing));
        const age = formatAge(liveStamp(ing));
        if (when && when !== "—") bits.push(age ? `${when} · ${age}` : when);
        if (ing.patient_id) bits.push(ing.patient_id);
        sub.textContent = bits.join(" · ") || "Telemetria recebida";
        if (card) card.classList.add("online");
    }

    function deviceToIngest(row) {
        if (row && row.latest) return row.latest;
        return {
            device_id: row.device_id,
            patient_id: row.patient_id,
            timestamp: row.last_seen,
            received_at: row.received_at,
            last_seen_local: row.last_seen_local,
            device_time_local: row.device_time_local,
            raw_telemetry: {
                heart_rate_bpm: row.heart_rate,
                spo2_percent: row.spo2
            },
            cleaned_telemetry: { heart_rate_clean: row.heart_rate }
        };
    }

    function upsertFleetFromIngest(ing) {
        if (!ing || !ing.device_id) return;
        const hr = (ing.cleaned_telemetry || {}).heart_rate_clean ?? (ing.raw_telemetry || {}).heart_rate_bpm;
        const spo2 = (ing.raw_telemetry || {}).spo2_percent;
        const next = {
            device_id: ing.device_id,
            patient_id: ing.patient_id,
            last_seen: ing.received_at || ing.timestamp,
            received_at: ing.received_at || ing.timestamp,
            last_seen_local: ing.last_seen_local || formatLocal(liveStamp(ing)),
            device_time_local: ing.device_time_local,
            online: true,
            heart_rate: hr,
            spo2,
            latest: ing
        };
        const idx = fleetDevices.findIndex((d) => d.device_id === ing.device_id);
        if (idx >= 0) fleetDevices[idx] = { ...fleetDevices[idx], ...next };
        else fleetDevices.unshift(next);
        renderFleetTable();
    }

    function filteredFleet() {
        const q = (document.getElementById("fleet-search")?.value || "").trim().toLowerCase();
        const filter = document.getElementById("fleet-filter")?.value || "all";
        return fleetDevices.filter((d) => {
            if (filter === "online" && !d.online) return false;
            if (filter === "offline" && d.online) return false;
            if (!q) return true;
            return String(d.device_id || "").toLowerCase().includes(q)
                || String(d.patient_id || "").toLowerCase().includes(q);
        });
    }

    function renderFleetTable() {
        const body = document.getElementById("fleet-body");
        const onlineEl = document.getElementById("fleet-online");
        const totalEl = document.getElementById("fleet-total");
        const pageEl = document.getElementById("fleet-page");
        if (!body) return;
        const rows = filteredFleet();
        const online = fleetDevices.filter((d) => d.online).length;
        if (onlineEl) onlineEl.textContent = `${online} online`;
        if (totalEl) totalEl.textContent = `${fleetDevices.length} no total`;
        const pages = Math.max(1, Math.ceil(rows.length / FLEET_PAGE_SIZE));
        if (fleetPage >= pages) fleetPage = pages - 1;
        if (fleetPage < 0) fleetPage = 0;
        if (pageEl) pageEl.textContent = `${fleetPage + 1} / ${pages}`;
        const slice = rows.slice(fleetPage * FLEET_PAGE_SIZE, (fleetPage + 1) * FLEET_PAGE_SIZE);
        if (!slice.length) {
            body.innerHTML = '<tr><td colspan="6" class="fleet-empty">Nenhum relógio nesta página.</td></tr>';
            return;
        }
        const esc = (value) => String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
        body.innerHTML = slice.map((d) => {
            const selected = d.device_id === selectedDeviceId ? " selected" : "";
            const when = d.last_seen_local || formatLocal(d.received_at || d.last_seen);
            const age = formatAge(d.received_at || d.last_seen);
            const hr = d.heart_rate != null ? Math.round(Number(d.heart_rate)) : "—";
            const spo2 = d.spo2 != null ? Number(d.spo2).toFixed(0) + "%" : "—";
            return `<tr data-device="${esc(d.device_id)}" class="${selected}">
                <td><span class="fleet-dot ${d.online ? "on" : "off"}"></span>${d.online ? "Online" : "Offline"}</td>
                <td>${esc(d.device_id)}</td>
                <td>${esc(d.patient_id || "—")}</td>
                <td>${hr}</td>
                <td>${spo2}</td>
                <td>${esc(age ? `${when} · ${age}` : when)}</td>
            </tr>`;
        }).join("");
        body.querySelectorAll("tr[data-device]").forEach((tr) => {
            tr.addEventListener("click", () => {
                selectedDeviceId = tr.getAttribute("data-device") || "";
                const row = fleetDevices.find((d) => d.device_id === selectedDeviceId);
                if (row) applyIngestFrame(deviceToIngest(row));
                renderFleetTable();
            });
        });
    }

    function renderWatchStrip(devices) {
        const incoming = devices || [];
        const byId = {};
        fleetDevices.forEach((d) => {
            if (d && d.device_id) byId[d.device_id] = d;
        });
        incoming.forEach((row) => {
            if (!row || !row.device_id) return;
            const prev = byId[row.device_id] || {};
            byId[row.device_id] = { ...prev, ...row };
        });
        fleetDevices = Object.values(byId);
        renderFleetTable();
        const focused = fleetDevices.find((d) => d.device_id === selectedDeviceId)
            || fleetDevices.find((d) => d.online)
            || fleetDevices[0];
        if (focused) {
            if (!selectedDeviceId) selectedDeviceId = focused.device_id;
            applyIngestFrame(deviceToIngest(focused));
            return;
        }
        const name = document.getElementById("watch-name");
        const sub = document.getElementById("watch-sub");
        const card = document.getElementById("card-watch");
        if (name) name.textContent = "Nenhum relógio no painel";
        if (sub) sub.textContent = "Aguardando ingestão dos apps companion…";
        if (card) card.classList.remove("online");
    }

    async function pollDevices() {
        if (!apiKey) {
            renderWatchStrip([]);
            return;
        }
        try {
            const res = await fetch(`${API_URL}/api/v1/wearables/devices?limit=500`, {
                headers: { "X-API-Key": apiKey },
                cache: "no-store"
            });
            if (!res.ok) return;
            const data = await res.json();
            renderWatchStrip(data.devices || []);
        } catch (err) {
            /* o painel continua com o último estado conhecido */
        }
    }

    function startDevicePoll() {
        if (devicePollTimer) clearInterval(devicePollTimer);
        pollDevices();
        if (!apiKey) return;
        devicePollTimer = setInterval(pollDevices, 2000);
        if (!window.__fleetClock) {
            window.__fleetClock = setInterval(() => renderFleetTable(), 1000);
        }
    }

    async function bootstrapDashboard() {
        try {
            const res = await fetch(`${API_URL}/api/v1/ops/dashboard-bootstrap`, { cache: "no-store" });
            if (res.ok) {
                const cfg = await res.json();
                if (cfg.api_key) {
                    apiKey = cfg.api_key;
                    localStorage.setItem("api_key", apiKey);
                    const display = document.getElementById("api-key-display");
                    if (display) display.value = apiKey;
                }
            }
        } catch (err) {
            /* segue com localStorage se o bootstrap falhar */
        }
        connectWebSocket();
        startDevicePoll();
    }

    function handleTelemetryFrame(frame) {
        if (!frame || !frame.sensor_readings) return;
        const ph = frame.phantom_data || {};
        // A. Atualizar buffers de dados deslizantes (MAX_POINTS)
        const label = String(frame.step ?? "");
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
        const s = phantomOr(ph.systolic_bp, null);
        const d = phantomOr(ph.diastolic_bp, null);
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
        const o = phantomOr(ph.spo2, null);
        const g = phantomOr(ph.glucose || ph.glucose_mgdl, null);
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
        const weights = frame.sensor_weights || {};
        const pwWeight = Math.round((weights.pixel_watch || 0) * 100);
        const fbWeight = Math.round((weights.fitbit_band || 0) * 100);
        subBpm.textContent = pwWeight || fbWeight
            ? `Pesos: Watch (${pwWeight}%) | Band (${fbWeight}%)`
            : "Relógio VE30";

        // Pressão Arterial
        if (s.estimate != null) {
            valBp.textContent = `${Math.round(s.estimate)} / ${Math.round(d.estimate || 0)}`;
            subBp.textContent = `Intervalo PAS: (${Math.round(s.ci_lower)} - ${Math.round(s.ci_upper)})`;
        }

        // SpO2
        if (o.estimate != null) {
            valSpo2.textContent = Number(o.estimate).toFixed(1);
            subSpo2.textContent = o.reliable ? "Sinal Válido ✓" : "Incerteza Alta ⚠️";
            subSpo2.className = o.reliable ? "metric-sub text-green" : "metric-sub text-red";
        }

        // Glicose
        if (g.estimate != null) {
            valGlucose.textContent = Math.round(g.estimate);
            subGlucose.textContent = g.reliable ? "Sinal Válido ✓" : "Incerteza Alta ⚠️";
        }

        // D. Atualizar Probabilidades da Rede Bayesiana (Barras)
        (frame.hypotheses || []).forEach(h => {
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
        const codes = frame.clinical_codes || {};
        if (badgesIcd10) updateBadges(badgesIcd10, codes.icd10);
        if (badgesSnomed) updateBadges(badgesSnomed, codes.snomed);
        if (badgesMesh) updateBadges(badgesMesh, codes.mesh);
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
            if (targetTab === "biophysics" && typeof window.initBiophysicsView === "function") {
                window.initBiophysicsView();
            }
            if (targetTab === "billing" && typeof window.initGcpBilling === "function") {
                window.initGcpBilling();
            }
        });
    });

    // Cópia de API Key
    const btnCopyKey = document.getElementById("btn-copy-key");
    const apiKeyDisplay = document.getElementById("api-key-display");
    const copyFeedback = document.getElementById("copy-feedback");
    if (apiKeyDisplay && apiKey) apiKeyDisplay.value = apiKey;
    const fleetSearch = document.getElementById("fleet-search");
    const fleetFilter = document.getElementById("fleet-filter");
    const fleetPrev = document.getElementById("fleet-prev");
    const fleetNext = document.getElementById("fleet-next");
    if (fleetSearch) fleetSearch.addEventListener("input", () => { fleetPage = 0; renderFleetTable(); });
    if (fleetFilter) fleetFilter.addEventListener("change", () => { fleetPage = 0; renderFleetTable(); });
    if (fleetPrev) fleetPrev.addEventListener("click", () => { fleetPage -= 1; renderFleetTable(); });
    if (fleetNext) fleetNext.addEventListener("click", () => { fleetPage += 1; renderFleetTable(); });

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
     -H "X-API-Key: $INGEST_API_KEY" \\
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
    "X-API-Key": "<SUA_INGEST_API_KEY>",
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
        "X-API-Key": "<SUA_INGEST_API_KEY>",
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
    // 9. BIOFÍSICA WINDKESSEL 4E & TEORIA DOS JOGOS
    // ========================================================================
    let chartWk4 = null;
    let chartPareto = null;

    function initBiophysicsCharts() {
        const ctxWk4 = document.getElementById("chart-wk4");
        if (ctxWk4 && !chartWk4) {
            chartWk4 = new Chart(ctxWk4, {
                type: "line",
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: "Pressão Aórtica P(t) [mmHg]",
                            borderColor: "#38bdf8",
                            backgroundColor: "rgba(56, 189, 248, 0.1)",
                            data: [],
                            borderWidth: 2,
                            pointRadius: 0,
                            fill: true,
                            yAxisID: "yP",
                        },
                        {
                            label: "Fluxo Ejetado Q(t) [mL/s]",
                            borderColor: "#ec4899",
                            backgroundColor: "rgba(236, 72, 153, 0.05)",
                            data: [],
                            borderWidth: 1.5,
                            pointRadius: 0,
                            borderDash: [4, 4],
                            yAxisID: "yQ",
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { display: true, title: { display: true, text: "Tempo (s)", color: "#64748b" } },
                        yP: { position: "left", title: { display: true, text: "P(t) mmHg", color: "#38bdf8" }, min: 40, max: 180 },
                        yQ: { position: "right", title: { display: true, text: "Q(t) mL/s", color: "#ec4899" }, grid: { drawOnChartArea: false }, min: 0, max: 500 }
                    },
                    plugins: {
                        legend: { labels: { color: "#e2e8f0", font: { family: "Outfit", size: 11 } } }
                    }
                }
            });
        }

        const ctxPareto = document.getElementById("chart-pareto");
        if (ctxPareto && !chartPareto) {
            chartPareto = new Chart(ctxPareto, {
                type: "scatter",
                data: {
                    datasets: [
                        {
                            label: "Alocações Viáveis",
                            data: [{ x: 10, y: 35 }, { x: 8, y: 38 }, { x: 12, y: 30 }, { x: 6, y: 40 }],
                            backgroundColor: "#64748b",
                        },
                        {
                            label: "Equilíbrio de Nash / Fronteira de Pareto",
                            data: [{ x: 10, y: 35 }],
                            backgroundColor: "#f59e0b",
                            pointRadius: 8,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { title: { display: true, text: "Leitos UTI Ocupados", color: "#94a3b8" } },
                        y: { title: { display: true, text: "Leitos Enfermaria Ocupados", color: "#94a3b8" } }
                    },
                    plugins: {
                        legend: { labels: { color: "#e2e8f0", font: { family: "Outfit", size: 11 } } }
                    }
                }
            });
        }
    }

    async function runWk4Simulation() {
        const rp = parseFloat(document.getElementById("slider-rp")?.value || "1.0");
        const c = parseFloat(document.getElementById("slider-c")?.value || "1.2");
        const zc = parseFloat(document.getElementById("slider-zc")?.value || "0.05");
        const l = parseFloat(document.getElementById("slider-l")?.value || "0.005");
        const hr = parseFloat(document.getElementById("slider-hr")?.value || "75");
        const sv = parseFloat(document.getElementById("slider-sv")?.value || "70");

        try {
            const headers = { "Content-Type": "application/json" };
            if (apiKey) headers["X-API-Key"] = apiKey;
            const resp = await fetch(`${API_URL}/api/hemodynamics/simulate_wk4`, {
                method: "POST",
                headers,
                body: JSON.stringify({ Rp: rp, C: c, Zc: zc, L: l, hr: hr, sv: sv, duration_s: 2.5, with_baroreflex: true })
            });
            if (!resp.ok) return;
            const data = await resp.json();

            if (chartWk4) {
                chartWk4.data.labels = data.time.map(t => t.toFixed(2));
                chartWk4.data.datasets[0].data = data.pressure;
                chartWk4.data.datasets[1].data = data.flow;
                chartWk4.update();
            }

            const elPas = document.getElementById("wk4-pas");
            const elPad = document.getElementById("wk4-pad");
            const elPam = document.getElementById("wk4-pam");
            const elPwv = document.getElementById("wk4-pwv");
            if (elPas) elPas.innerText = `${data.metrics.systolic_bp} mmHg`;
            if (elPad) elPad.innerText = `${data.metrics.diastolic_bp} mmHg`;
            if (elPam) elPam.innerText = `${data.metrics.mean_arterial_pressure} mmHg`;
            if (elPwv) elPwv.innerText = `${data.metrics.pwv_bramwell_hill} m/s`;
        } catch (err) {
            console.warn("Simulação WK4 offline:", err);
        }
    }

    ["slider-rp", "slider-c", "slider-zc", "slider-l", "slider-hr", "slider-sv"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener("input", () => {
                const lblId = id.replace("slider-", "lbl-");
                const lbl = document.getElementById(lblId);
                if (lbl) lbl.innerText = el.value;
                runWk4Simulation();
            });
        }
    });

    const btnCalcTriage = document.getElementById("btn-calc-triage");
    if (btnCalcTriage) {
        btnCalcTriage.addEventListener("click", async () => {
            const icuCap = parseInt(document.getElementById("inp-icu-cap")?.value || "10");
            const wardCap = parseInt(document.getElementById("inp-ward-cap")?.value || "40");
            const icuDem = parseInt(document.getElementById("inp-icu-dem")?.value || "14");
            const critFrac = parseFloat(document.getElementById("inp-crit-frac")?.value || "40") / 100.0;

            try {
                const headers = { "Content-Type": "application/json" };
                if (apiKey) headers["X-API-Key"] = apiKey;
                const resp = await fetch(`${API_URL}/api/game_theory/solve_triage`, {
                    method: "POST",
                    headers,
                    body: JSON.stringify({ icu_capacity: icuCap, ward_capacity: wardCap, icu_demand: icuDem, ward_demand: 35, high_risk_fraction: critFrac })
                });
                if (!resp.ok) return;
                const data = await resp.json();

                const badge = document.getElementById("triage-nash-badge");
                const rec = document.getElementById("triage-recommendation");
                if (badge) badge.innerText = `Nash: ${data.nash_equilibrium?.strategy || "Alocação Balanceada"}`;
                if (rec) rec.innerText = data.clinical_recommendation || "Equilíbrio calculado com sucesso.";

                if (chartPareto && data.pareto_frontier) {
                    chartPareto.data.datasets[1].data = data.pareto_frontier.map(p => ({ x: p.icu_allocated, y: p.ward_allocated }));
                    chartPareto.update();
                }
            } catch (e) {
                console.warn("Erro ao calcular triagem:", e);
            }
        });
    }

    window.initBiophysicsView = function () {
        initBiophysicsCharts();
        runWk4Simulation();
    };

    const initialTab = urlParams.get("tab");
    if (initialTab) window.switchTab(initialTab);

    bootstrapDashboard();
});

