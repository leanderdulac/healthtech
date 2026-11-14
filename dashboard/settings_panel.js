/* ==========================================================================
   Painel de configurações do dashboard (browser + Node).
   ========================================================================== */
(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.HealthtechSettingsPanel = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
    const CLOSE_ANIMATION_MS = 250;

    function shouldCloseOnKey(event) {
        if (!event) return false;
        return event.key === "Escape" || event.key === "Esc";
    }

    function shouldCloseOnBackdropClick(event, backdrop) {
        return !!(event && backdrop && event.target === backdrop);
    }

    function createSettingsController() {
        let open = false;
        return {
            isOpen() {
                return open;
            },
            open() {
                open = true;
                return { open: true };
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
        const openBtn = elements.openBtn;
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
        if (openBtn) {
            openBtn.setAttribute("aria-expanded", open ? "true" : "false");
        }
        if (doc && doc.body) {
            doc.body.classList.toggle("settings-open", open);
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

    function bindSettingsPanel(root) {
        const doc = root && root.querySelector ? root : (typeof document !== "undefined" ? document : null);
        if (!doc || typeof doc.getElementById !== "function") return null;
        const openBtn = doc.getElementById("btn-open-settings");
        const closeBtn = doc.getElementById("btn-close-settings");
        const panel = doc.getElementById("settings-panel");
        const backdrop = doc.getElementById("settings-backdrop");
        if (!openBtn || !panel) return null;

        const controller = createSettingsController();
        const elements = {
            panel,
            backdrop,
            openBtn,
            document: doc.body ? doc : (doc.ownerDocument || doc)
        };

        function open() {
            controller.open();
            applyOpenState(elements, true);
            if (closeBtn && typeof closeBtn.focus === "function") {
                closeBtn.focus();
            }
        }

        function close() {
            controller.close();
            applyOpenState(elements, false);
            if (openBtn && typeof openBtn.focus === "function") {
                openBtn.focus();
            }
        }

        function onOpenClick(event) {
            if (event && typeof event.preventDefault === "function") event.preventDefault();
            if (controller.isOpen()) close();
            else open();
        }

        function onCloseClick(event) {
            if (event && typeof event.preventDefault === "function") event.preventDefault();
            close();
        }

        function onBackdropClick(event) {
            if (controller.handleBackdropClick(event, backdrop).closed) {
                applyOpenState(elements, false);
                if (openBtn && typeof openBtn.focus === "function") openBtn.focus();
            }
        }

        function onKey(event) {
            if (controller.handleKey(event).closed) {
                applyOpenState(elements, false);
                if (openBtn && typeof openBtn.focus === "function") openBtn.focus();
            }
        }

        openBtn.addEventListener("click", onOpenClick);
        if (closeBtn) closeBtn.addEventListener("click", onCloseClick);
        if (backdrop) backdrop.addEventListener("click", onBackdropClick);
        const keyTarget = elements.document;
        if (keyTarget && typeof keyTarget.addEventListener === "function") {
            keyTarget.addEventListener("keydown", onKey);
        }

        applyOpenState(elements, false);
        return { open, close, isOpen: controller.isOpen };
    }

    return {
        CLOSE_ANIMATION_MS,
        shouldCloseOnKey,
        shouldCloseOnBackdropClick,
        createSettingsController,
        bindSettingsPanel
    };
}));
