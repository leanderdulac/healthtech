/* ==========================================================================
   Gaveta 'Detalhes do relógio' (browser + Node). Sem localização.
   ========================================================================== */
(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.HealthtechDeviceDetails = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
    const CLOSE_ANIMATION_MS = 250;
    const CADASTRO_NOTE = "Região do cadastro do paciente, não é localização em tempo real.";
    const MESSAGES = {
        missingKey: "Informe a chave de leitura já usada no painel para ver os detalhes do relógio. Ela fica salva só neste navegador.",
        rejectedKey: "A chave salva foi recusada. Informe uma chave válida para ver os detalhes do relógio.",
        forbidden: "Sem permissão para ver os detalhes deste relógio.",
        notFound: "Relógio não encontrado.",
        unavailable: "Não foi possível carregar os detalhes do relógio.",
        loading: "Carregando detalhes…",
        openApiAccess: "Abrir Acesso à API",
        keyLabel: "Chave de leitura",
        keyPlaceholder: "Cole a chave de leitura",
        saveKey: "Guardar e ver detalhes",
        missingKeyInput: "Cole a chave de leitura para continuar."
    };
    const OPEN_API_ACCESS_ACTION = "open-api-access";
    const SAVE_API_KEY_ACTION = "save-api-key";

    function shouldCloseOnKey(event) {
        if (!event) return false;
        return event.key === "Escape" || event.key === "Esc";
    }

    function shouldCloseOnBackdropClick(event, backdrop) {
        return !!(event && backdrop && event.target === backdrop);
    }

    function displayValue(value) {
        if (value == null) return "não informado";
        const text = String(value).trim();
        return text ? text : "não informado";
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function unauthorizedMessage(status, hasKey) {
        if (!hasKey) return MESSAGES.missingKey;
        if (status === 401) return MESSAGES.rejectedKey;
        if (status === 403) return MESSAGES.forbidden;
        if (status === 404) return MESSAGES.notFound;
        return MESSAGES.unavailable;
    }

    function needsApiAccessAction(status, hasKey) {
        return !hasKey || status === 401;
    }

    function renderAuthPrompt(message) {
        const text = escapeHtml(message || MESSAGES.missingKey);
        const keyLabel = escapeHtml(MESSAGES.keyLabel);
        const placeholder = escapeHtml(MESSAGES.keyPlaceholder);
        const saveLabel = escapeHtml(MESSAGES.saveKey);
        return `<div class="device-details-auth-prompt">`
            + `<p class="device-details-status">${text}</p>`
            + `<form class="device-details-key-form" data-device-details-action="${SAVE_API_KEY_ACTION}">`
            + `<label for="device-details-api-key">${keyLabel}</label>`
            + `<div class="device-details-key-row">`
            + `<input type="password" id="device-details-api-key" name="api_key" autocomplete="off" placeholder="${placeholder}">`
            + `<button type="submit" class="btn btn-primary">${saveLabel}</button>`
            + `</div>`
            + `</form>`
            + `</div>`;
    }

    function presentDeviceDetails(payload) {
        const data = payload || {};
        const region = data.region || {};
        const vitals = data.vitals || {};
        const online = data.online === true ? "Online" : "Offline";
        const lastSeen = data.last_seen_local || data.last_seen;
        return {
            title: "Detalhes do relógio",
            cadastroNote: CADASTRO_NOTE,
            blocks: [
                {
                    id: "watch",
                    title: "Relógio",
                    rows: [
                        { label: "ID", value: displayValue(data.device_id) },
                        { label: "Modelo", value: displayValue(data.device_model) },
                        { label: "Nome", value: displayValue(data.device_label) },
                        { label: "Paciente", value: displayValue(data.patient_id) },
                        { label: "Origem", value: displayValue(data.ingest_source) }
                    ]
                },
                {
                    id: "region",
                    title: "Região do cadastro",
                    note: CADASTRO_NOTE,
                    rows: [
                        { label: "municipality_id", value: displayValue(region.municipality_id) },
                        { label: "ubs_id", value: displayValue(region.ubs_id) }
                    ]
                },
                {
                    id: "app",
                    title: "Aparelho com o app",
                    rows: [
                        { label: "Versão do app", value: displayValue(data.app_version) }
                    ]
                },
                {
                    id: "reading",
                    title: "Última leitura",
                    rows: [
                        { label: "Quando", value: displayValue(lastSeen) },
                        { label: "Status", value: online },
                        { label: "BPM", value: displayValue(vitals.heart_rate) },
                        { label: "SpO₂", value: displayValue(vitals.spo2) },
                        { label: "Passos", value: displayValue(vitals.steps) },
                        {
                            label: "Pressão",
                            value: formatBloodPressure(vitals.blood_pressure_sys, vitals.blood_pressure_dia)
                        }
                    ]
                }
            ]
        };
    }

    function formatBloodPressure(sys, dia) {
        if (sys == null || dia == null || sys === "" || dia === "") return "não informado";
        const s = Number(sys);
        const d = Number(dia);
        if (!Number.isFinite(s) || !Number.isFinite(d)) return "não informado";
        return Math.round(s) + "/" + Math.round(d);
    }

    function renderPresented(presented) {
        if (!presented || !presented.blocks) {
            return `<p class="device-details-status">${escapeHtml(MESSAGES.unavailable)}</p>`;
        }
        return presented.blocks.map((block) => {
            const note = block.note
                ? `<p class="device-details-note">${escapeHtml(block.note)}</p>`
                : "";
            const rows = (block.rows || []).map((row) => (
                `<div class="device-details-row">`
                + `<dt>${escapeHtml(row.label)}</dt>`
                + `<dd>${escapeHtml(row.value)}</dd>`
                + `</div>`
            )).join("");
            return `<section class="card device-details-block" data-block="${escapeHtml(block.id)}">`
                + `<h3>${escapeHtml(block.title)}</h3>`
                + note
                + `<dl class="device-details-dl">${rows}</dl>`
                + `</section>`;
        }).join("");
    }

    function createDetailsController() {
        let open = false;
        let deviceId = "";
        return {
            isOpen() {
                return open;
            },
            currentDeviceId() {
                return deviceId;
            },
            open(id) {
                open = true;
                deviceId = id || deviceId;
                return { open: true, deviceId };
            },
            close() {
                open = false;
                return { open: false };
            },
            handleKey(event) {
                if (open && shouldCloseOnKey(event)) {
                    open = false;
                    return { closed: true };
                }
                return { closed: false };
            },
            handleBackdropClick(event, backdrop) {
                if (open && shouldCloseOnBackdropClick(event, backdrop)) {
                    open = false;
                    return { closed: true };
                }
                return { closed: false };
            }
        };
    }

    function applyOpenState(elements, open) {
        const panel = elements.panel;
        const backdrop = elements.backdrop;
        const doc = elements.document || (typeof document !== "undefined" ? document : null);
        if (panel) {
            panel.classList.toggle("is-open", open);
            panel.setAttribute("aria-hidden", open ? "false" : "true");
            if (open) panel.removeAttribute("hidden");
        }
        if (backdrop) {
            backdrop.classList.toggle("is-open", open);
            if (open) backdrop.removeAttribute("hidden");
        }
        if (doc && doc.body) {
            doc.body.classList.toggle("device-details-open", open);
        }
        if (!open) {
            const hide = function () {
                if (panel && !panel.classList.contains("is-open")) {
                    panel.setAttribute("hidden", "");
                }
                if (backdrop && !backdrop.classList.contains("is-open")) {
                    backdrop.setAttribute("hidden", "");
                }
            };
            if (typeof setTimeout === "function") {
                setTimeout(hide, CLOSE_ANIMATION_MS);
            } else {
                hide();
            }
        }
    }

    function setBodyHtml(body, html) {
        if (body) body.innerHTML = html;
    }

    function bindDeviceDetailsPanel(root, options) {
        const opts = options || {};
        const doc = root && root.querySelector ? root : (typeof document !== "undefined" ? document : null);
        if (!doc || typeof doc.getElementById !== "function") return null;
        const closeBtn = doc.getElementById("btn-close-device-details");
        const panel = doc.getElementById("device-details-panel");
        const backdrop = doc.getElementById("device-details-backdrop");
        const body = doc.getElementById("device-details-body");
        if (!panel) return null;

        const controller = createDetailsController();
        const elements = {
            panel,
            backdrop,
            document: doc.body ? doc : (doc.ownerDocument || doc)
        };

        function close() {
            controller.close();
            applyOpenState(elements, false);
        }

        function open() {
            if (typeof opts.onOpen === "function") opts.onOpen();
            controller.open();
            applyOpenState(elements, true);
            if (closeBtn && typeof closeBtn.focus === "function") closeBtn.focus();
        }

        function renderStatus(message) {
            setBodyHtml(body, `<p class="device-details-status">${escapeHtml(message)}</p>`);
        }

        function show(deviceId) {
            const id = String(deviceId || "").trim();
            if (!id) return;
            controller.open(id);
            open();
            renderStatus(MESSAGES.loading);
            const fetcher = opts.fetchDetail;
            if (typeof fetcher !== "function") {
                renderStatus(MESSAGES.unavailable);
                return;
            }
            Promise.resolve(fetcher(id)).then((result) => {
                if (controller.currentDeviceId() !== id) return;
                if (!result || result.ok === false) {
                    const status = result && result.status;
                    const hasKey = !!(result && result.hasKey);
                    const message = unauthorizedMessage(status, hasKey);
                    if (needsApiAccessAction(status, hasKey)) {
                        setBodyHtml(body, renderAuthPrompt(message));
                    } else {
                        renderStatus(message);
                    }
                    return;
                }
                setBodyHtml(body, renderPresented(presentDeviceDetails(result)));
            }).catch(() => {
                if (controller.currentDeviceId() !== id) return;
                renderStatus(MESSAGES.unavailable);
            });
        }

        function onCloseClick(event) {
            if (event && typeof event.preventDefault === "function") event.preventDefault();
            close();
        }

        function onBackdropClick(event) {
            if (controller.handleBackdropClick(event, backdrop).closed) {
                applyOpenState(elements, false);
            }
        }

        function onKey(event) {
            if (controller.handleKey(event).closed) {
                applyOpenState(elements, false);
            }
        }

        if (body) {
            body.addEventListener("click", function (event) {
                const target = event && event.target;
                const btn = target && target.closest
                    ? target.closest('[data-device-details-action="' + OPEN_API_ACCESS_ACTION + '"]')
                    : null;
                if (!btn) return;
                if (event && typeof event.preventDefault === "function") event.preventDefault();
                if (typeof opts.onRequestApiAccess === "function") {
                    opts.onRequestApiAccess(controller.currentDeviceId());
                }
            });
            body.addEventListener("submit", function (event) {
                const form = event && event.target;
                const action = form && form.getAttribute
                    ? form.getAttribute("data-device-details-action")
                    : "";
                if (action !== SAVE_API_KEY_ACTION) return;
                if (event && typeof event.preventDefault === "function") event.preventDefault();
                const input = form.querySelector
                    ? form.querySelector("#device-details-api-key")
                    : null;
                const value = input && input.value ? String(input.value).trim() : "";
                if (!value) {
                    setBodyHtml(body, renderAuthPrompt(MESSAGES.missingKeyInput));
                    const again = body.querySelector
                        ? body.querySelector("#device-details-api-key")
                        : null;
                    if (again && typeof again.focus === "function") again.focus();
                    return;
                }
                if (typeof opts.onSaveApiKey === "function") {
                    opts.onSaveApiKey(value);
                }
            });
        }

        if (closeBtn) closeBtn.addEventListener("click", onCloseClick);
        if (backdrop) backdrop.addEventListener("click", onBackdropClick);
        const keyTarget = elements.document;
        if (keyTarget && typeof keyTarget.addEventListener === "function") {
            keyTarget.addEventListener("keydown", onKey);
        }

        applyOpenState(elements, false);
        return {
            open,
            close,
            show,
            isOpen: controller.isOpen,
            currentDeviceId: controller.currentDeviceId
        };
    }

    return {
        CLOSE_ANIMATION_MS,
        CADASTRO_NOTE,
        MESSAGES,
        shouldCloseOnKey,
        shouldCloseOnBackdropClick,
        displayValue,
        unauthorizedMessage,
        needsApiAccessAction,
        renderAuthPrompt,
        presentDeviceDetails,
        renderPresented,
        createDetailsController,
        bindDeviceDetailsPanel,
        OPEN_API_ACCESS_ACTION,
        SAVE_API_KEY_ACTION
    };
}));
