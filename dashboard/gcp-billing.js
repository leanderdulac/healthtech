/* Google Cloud Billing console (simulação HealthTech) */
(function () {
    const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
    const NUM = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
    let ledger = null;
    let chart = null;
    let countdownTimer = null;

    function $(id) {
        return document.getElementById(id);
    }

    function fmtUsage(v, unit) {
        if (v >= 1e6) return `${NUM.format(v / 1e6)}M ${unit}`;
        if (v >= 1e3) return `${NUM.format(v / 1e3)}k ${unit}`;
        return `${NUM.format(v)} ${unit}`;
    }

    async function loadLedger() {
        const res = await fetch("billing-ledger.json", { cache: "no-store" });
        if (!res.ok) throw new Error("ledger HTTP " + res.status);
        return res.json();
    }

    function renderKpis(data) {
        const k = data.kpis;
        $("gcp-kpi-spent").textContent = BRL.format(k.spent_last_3_weeks_brl);
        $("gcp-kpi-today").textContent = BRL.format(k.spent_today_brl);
        $("gcp-kpi-balance").textContent = BRL.format(k.balance_brl);
        $("gcp-kpi-balance").className = "value " + (k.balance_brl < 0 ? "neg" : "pos");
        $("gcp-kpi-credit").textContent = BRL.format(k.credits_today_brl || k.credits_scheduled_brl || 0);
        $("gcp-kpi-forecast").textContent = BRL.format(k.forecast_week_brl);
        $("gcp-account-id").textContent = data.meta.billing_account_id;
        $("gcp-project-id").textContent = data.meta.project_id;
        const disc = $("gcp-disclaimer");
        if (disc) disc.textContent = data.meta.disclaimer;
    }

    function startCountdown(iso) {
        const el = $("gcp-countdown");
        if (!el || !ledger) return;
        const cloud = (ledger.credits || [])
            .filter((c) => c.kind === "cloud_budget" || c.payer)
            .map((c) => `${c.date.slice(8, 10)}/${c.date.slice(5, 7)} ${BRL.format(c.amount_brl)}`)
            .join(" · ");
        if (cloud) el.textContent = cloud;
        if (!iso) return;
        const target = new Date(iso).getTime();
        if (Number.isNaN(target) || target <= Date.now()) return;
        const tick = () => {
            const ms = target - Date.now();
            if (ms <= 0) return;
            const h = Math.floor(ms / 3600000);
            const m = Math.floor((ms % 3600000) / 60000);
            const s = Math.floor((ms % 60000) / 1000);
            el.textContent = `${cloud}  ·  próximo em ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
        };
        tick();
        if (countdownTimer) clearInterval(countdownTimer);
        countdownTimer = setInterval(tick, 1000);
    }

    function renderChart(data) {
        const ctx = $("gcp-cost-chart");
        if (!ctx || typeof Chart === "undefined") return;
        const services = data.by_service.map((s) => s.service);
        const colorOf = Object.fromEntries(data.by_service.map((s) => [s.service, s.color]));
        const labels = data.daily.map((d) => d.date.slice(5));
        const datasets = services.map((svc) => ({
            label: svc,
            data: data.daily.map((d) =>
                d.items.filter((i) => i.service === svc).reduce((a, i) => a + i.cost_brl, 0)
            ),
            backgroundColor: colorOf[svc],
            borderWidth: 0,
            stack: "cost",
        }));
        if (chart) chart.destroy();
        chart = new Chart(ctx, {
            type: "bar",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 11, family: "Roboto" } } },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.dataset.label}: ${BRL.format(c.parsed.y || 0)}`,
                        },
                    },
                },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, font: { size: 10 } } },
                    y: {
                        stacked: true,
                        ticks: { callback: (v) => "R$ " + NUM.format(v) },
                        grid: { color: "#eee" },
                    },
                },
            },
        });
    }

    function renderServiceTable(data) {
        const tb = $("gcp-service-body");
        const total = data.kpis.spent_to_date_brl || 1;
        tb.innerHTML = data.by_service
            .map(
                (s) => `<tr>
            <td><span class="gcp-swatch" style="background:${s.color}"></span>${s.service}</td>
            <td class="num">${((s.cost_brl / total) * 100).toFixed(1)}%</td>
            <td class="num">${BRL.format(s.cost_brl)}</td>
        </tr>`
            )
            .join("");
        $("gcp-service-total").textContent = BRL.format(data.kpis.spent_to_date_brl);
    }

    function renderSkuTable(data) {
        const tb = $("gcp-sku-body");
        tb.innerHTML = data.by_sku
            .map(
                (s) => `<tr>
            <td>${s.service}</td>
            <td>${s.sku}</td>
            <td><code>${s.sku_id}</code></td>
            <td class="num">${fmtUsage(s.usage, s.unit)}</td>
            <td class="num">${BRL.format(s.cost_brl)}</td>
        </tr>`
            )
            .join("");
    }

    function renderTransactions(data) {
        const rows = [];
        data.credits.forEach((c) => {
            rows.push({
                date: c.date,
                type: "Payment (Next2U cloud budget)",
                desc: `${c.payer || "NEXT2U SAUDE LTDA"} — ${c.description}`,
                doc: c.document,
                amount: c.amount_brl,
                status: c.status,
            });
        });

        data.daily.forEach((d) => {
            rows.push({
                date: d.date,
                type: "Usage",
                desc: d.events.length
                    ? d.events.map((e) => e.title).join(" · ")
                    : "Uso de SKUs (predição, tokens, Run, storage)",
                doc: "USAGE-" + d.date.replace(/-/g, ""),
                amount: -d.total_brl,
                status: "posted",
            });
        });
        rows.sort((a, b) => (a.date < b.date ? 1 : -1));
        $("gcp-tx-body").innerHTML = rows
            .map(
                (r) => `<tr>
            <td>${r.date}</td>
            <td>${r.type}</td>
            <td>${r.desc}</td>
            <td><code>${r.doc}</code></td>
            <td><span class="gcp-status ${r.status}">${r.status}</span></td>
            <td class="num">${BRL.format(r.amount)}</td>
        </tr>`
            )
            .join("");
    }

    function renderDocuments(data) {
        $("gcp-docs-body").innerHTML = data.invoices
            .map(
                (inv) => `<tr>
            <td>${inv.document_type}</td>
            <td><code>${inv.number}</code></td>
            <td>${inv.period_start} → ${inv.period_end}</td>
            <td>${inv.issue_date || "—"}</td>
            <td><span class="gcp-status ${inv.status}">${inv.status}</span></td>
            <td class="num">${BRL.format(inv.total_brl)}</td>
            <td><button class="gcp-btn" data-invoice="${inv.number}">PDF</button></td>
        </tr>`
            )
            .join("");
        $("gcp-docs-body").querySelectorAll("button[data-invoice]").forEach((btn) => {
            btn.addEventListener("click", () => downloadInvoicePdf(btn.getAttribute("data-invoice")));
        });
    }

    function renderBudget(data) {
        const ultra = data.kpis.gemini_ultra_today_brl || 0;
        const weekSpend = Math.max(0, (data.kpis.spent_today_brl || 0) - ultra);
        const cap = data.kpis.cloud_from_today_credit_brl || data.meta.weekly_credit_brl;
        const pct = Math.min(100, (weekSpend / cap) * 100);
        $("gcp-budget-name").textContent = data.meta.budget_name;
        $("gcp-budget-amount").textContent = `${BRL.format(weekSpend)} de ${BRL.format(cap)} em nuvem/tokens · Gemini Ultra ${BRL.format(ultra)} (pago)`;
        $("gcp-budget-pct").textContent = `${pct.toFixed(1)}% da parcela de nuvem desta semana`;
        const bar = $("gcp-budget-fill");
        bar.style.width = pct + "%";
        $("gcp-budget-bar").classList.toggle("over", pct >= 100);
        const monthCap = data.kpis.credits_posted_brl || cap * 4;
        const monthPct = Math.min(100, (data.kpis.mtd_brl / monthCap) * 100);
        $("gcp-budget-month").textContent = `${BRL.format(data.kpis.mtd_brl)} de ${BRL.format(monthCap)}`;
        $("gcp-budget-month-fill").style.width = monthPct + "%";
    }

    function renderEvents(data) {
        $("gcp-events").innerHTML = data.events
            .slice()
            .reverse()
            .map(
                (e) => `<tr>
            <td>${e.date}</td>
            <td>${e.kind}</td>
            <td>${e.title}</td>
        </tr>`
            )
            .join("");
    }

    function switchGcpPanel(name) {
        document.querySelectorAll(".gcp-subnav button").forEach((b) => {
            b.classList.toggle("active", b.getAttribute("data-gcp") === name);
        });
        document.querySelectorAll(".gcp-panel").forEach((p) => {
            p.classList.toggle("active", p.id === "gcp-panel-" + name);
        });
        if (name === "reports" && chart) chart.resize();
    }

    function ensureJsPdf() {
        return new Promise((resolve, reject) => {
            if (window.jspdf && window.jspdf.jsPDF) return resolve(window.jspdf.jsPDF);
            const s = document.createElement("script");
            s.src = "https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js";
            s.onload = () => resolve(window.jspdf.jsPDF);
            s.onerror = () => reject(new Error("jsPDF"));
            document.head.appendChild(s);
        });
    }

    function drawInvoice(doc, data, invoice) {
        const pageW = 210;
        const margin = 16;
        let y = 16;
        doc.setFillColor(255, 255, 255);
        doc.rect(0, 0, pageW, 297, "F");

        doc.setFillColor(66, 133, 244);
        doc.circle(margin + 4, y + 4, 3.2, "F");
        doc.setFillColor(234, 67, 53);
        doc.circle(margin + 8, y + 3, 3.2, "F");
        doc.setFillColor(251, 188, 4);
        doc.circle(margin + 6, y + 7, 3.2, "F");
        doc.setFillColor(52, 168, 83);
        doc.circle(margin + 3, y + 6.5, 2.2, "F");

        doc.setFont("helvetica", "bold");
        doc.setFontSize(16);
        doc.setTextColor(32, 33, 36);
        doc.text("Google Cloud", margin + 14, y + 6);
        doc.setFont("helvetica", "normal");
        doc.setFontSize(9);
        doc.setTextColor(95, 99, 104);
        doc.text("Cloud Billing  ·  Invoice", margin + 14, y + 11);

        y += 20;
        doc.setFont("helvetica", "bold");
        doc.setFontSize(18);
        doc.setTextColor(32, 33, 36);
        doc.text(invoice.status === "open" ? "Draft invoice" : "Invoice", margin, y);
        y += 8;
        doc.setFont("helvetica", "normal");
        doc.setFontSize(10);
        doc.setTextColor(95, 99, 104);
        doc.text(`Invoice number  ${invoice.number}`, margin, y);
        y += 5;
        doc.text(`Billing account  ${data.meta.billing_account_id}`, margin, y);
        y += 5;
        doc.text(`Project  ${data.meta.project_id}  (${data.meta.project_number})`, margin, y);
        y += 5;
        doc.text(`Invoice period  ${invoice.period_start} – ${invoice.period_end}`, margin, y);
        y += 5;
        doc.text(`Issue date  ${invoice.issue_date || data.meta.as_of}`, margin, y);
        y += 5;
        doc.text(`Location  ${data.meta.location}   ·   FX USD/BRL ${data.meta.fx_usd_brl}`, margin, y);

        y += 12;
        doc.setDrawColor(218, 220, 224);
        doc.line(margin, y, pageW - margin, y);
        y += 8;

        doc.setFont("helvetica", "bold");
        doc.setFontSize(9);
        doc.setTextColor(95, 99, 104);
        doc.text("Service / SKU", margin, y);
        doc.text("SKU ID", 118, y);
        doc.text("Amount (BRL)", pageW - margin, y, { align: "right" });
        y += 3;
        doc.setDrawColor(232, 234, 237);
        doc.line(margin, y, pageW - margin, y);
        y += 6;

        const start = invoice.period_start;
        const end = invoice.period_end;
        const acc = {};
        data.daily
            .filter((d) => d.date >= start && d.date <= end)
            .forEach((d) => {
                d.items.forEach((it) => {
                    const key = it.sku_id;
                    if (!acc[key]) acc[key] = { ...it, cost_brl: 0 };
                    acc[key].cost_brl += it.cost_brl;
                });
            });
        const rows = Object.values(acc).sort((a, b) => b.cost_brl - a.cost_brl);
        doc.setFont("helvetica", "normal");
        doc.setFontSize(8);
        doc.setTextColor(32, 33, 36);
        rows.forEach((r) => {
            if (y > 250) {
                doc.addPage();
                y = 20;
            }
            doc.text(r.service, margin, y);
            doc.text(r.sku.substring(0, 48), margin, y + 3.5);
            doc.setTextColor(95, 99, 104);
            doc.text(r.sku_id, 118, y);
            doc.setTextColor(32, 33, 36);
            doc.text(BRL.format(r.cost_brl), pageW - margin, y, { align: "right" });
            y += 8;
        });

        y += 4;
        doc.line(margin, y, pageW - margin, y);
        y += 8;
        doc.setFontSize(10);
        doc.text("Subtotal", 130, y);
        doc.text(BRL.format(invoice.subtotal_brl), pageW - margin, y, { align: "right" });
        y += 6;
        doc.text("ISS (2%)", 130, y);
        doc.text(BRL.format(invoice.iss_brl), pageW - margin, y, { align: "right" });
        y += 8;
        doc.setFont("helvetica", "bold");
        doc.setFontSize(12);
        doc.text("Total", 130, y);
        doc.text(BRL.format(invoice.total_brl), pageW - margin, y, { align: "right" });

        y += 16;
        doc.setFont("helvetica", "normal");
        doc.setFontSize(7.5);
        doc.setTextColor(95, 99, 104);
        const disc = doc.splitTextToSize(data.meta.disclaimer, pageW - margin * 2);
        doc.text(disc, margin, y);
        y += disc.length * 4 + 6;
        doc.text("Google Cloud  ·  Payments applied as weekly processing & token credits (R$ 4.000,00 every Monday).", margin, y);
    }

    async function downloadInvoicePdf(number) {
        const JsPDF = await ensureJsPdf();
        const inv = ledger.invoices.find((i) => i.number === number) || ledger.invoices[0];
        const doc = new JsPDF({ unit: "mm", format: "a4" });
        drawInvoice(doc, ledger, inv);
        doc.save(`GoogleCloud_Invoice_${inv.number}.pdf`);
    }

    async function downloadReportPdf() {
        const JsPDF = await ensureJsPdf();
        const doc = new JsPDF({ unit: "mm", format: "a4" });
        drawInvoice(doc, ledger, {
            number: "REPORT-" + ledger.meta.as_of.replace(/-/g, ""),
            status: "open",
            period_start: ledger.daily[0].date,
            period_end: ledger.meta.as_of,
            issue_date: ledger.meta.as_of,
            subtotal_brl: ledger.kpis.spent_to_date_brl,
            iss_brl: 0,
            total_brl: ledger.kpis.spent_to_date_brl,
        });
        doc.save(`GoogleCloud_CostReport_${ledger.meta.as_of}.pdf`);
    }

    async function initGcpBilling() {
        const root = $("view-billing");
        if (!root) return;
        try {
            ledger = await loadLedger();
        } catch (err) {
            console.warn("Faturamento GCP indisponível:", err);
            return;
        }
        renderKpis(ledger);
        renderChart(ledger);
        renderServiceTable(ledger);
        renderSkuTable(ledger);
        renderTransactions(ledger);
        renderDocuments(ledger);
        renderBudget(ledger);
        renderEvents(ledger);
        startCountdown(ledger.meta.next_credit_at);
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll(".gcp-subnav button").forEach((btn) => {
            btn.addEventListener("click", () => switchGcpPanel(btn.getAttribute("data-gcp")));
        });
        const reportBtn = $("gcp-download-report");
        if (reportBtn) reportBtn.addEventListener("click", downloadReportPdf);
        const csvBtn = $("gcp-download-csv");
        if (csvBtn) {
            csvBtn.addEventListener("click", () => {
                if (!ledger) return;
                const header = "service,sku,sku_id,unit,usage,cost_brl\n";
                const body = ledger.by_sku
                    .map((s) => [s.service, `"${s.sku}"`, s.sku_id, s.unit, s.usage, s.cost_brl].join(","))
                    .join("\n");
                const blob = new Blob([header + body], { type: "text/csv;charset=utf-8" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = "gcp-cost-table.csv";
                a.click();
            });
        }
    });

    window.initGcpBilling = initGcpBilling;
    window.downloadGcpInvoicePdf = downloadInvoicePdf;
})();
