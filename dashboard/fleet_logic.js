/* ==========================================================================
   Regras puras da frota (browser + Node). Espelha src/ops/fleet_online.py
   e src/ops/device_registry.is_synthetic_device.
   ========================================================================== */
(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    }
    root.HealthtechFleetLogic = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
    const ONLINE_WITHIN_MS = 120000;
    const SYNTHETIC_TOKENS = ["smoke", "probe", "timecheck"];

    function parseStamp(value) {
        if (!value) return null;
        if (/^\d{2}\/\d{2}\/\d{4}/.test(String(value))) return null;
        const d = new Date(value);
        return Number.isNaN(d.getTime()) ? null : d;
    }

    function isRecentLiveStamp(value, nowMs) {
        const d = parseStamp(value);
        if (!d) return false;
        const now = typeof nowMs === "number" ? nowMs : Date.now();
        const age = now - d.getTime();
        return age >= 0 && age <= ONLINE_WITHIN_MS;
    }

    function resolveFleetOnline(existing, incoming, fromLiveIngest, nowMs) {
        const row = incoming || {};
        if (fromLiveIngest) {
            return isRecentLiveStamp(row.received_at || row.last_seen || row.timestamp, nowMs);
        }
        if (typeof row.online === "boolean") return row.online;
        if (existing && typeof existing.online === "boolean") return existing.online;
        return false;
    }

    function isSyntheticDevice(row) {
        if (!row || typeof row !== "object") return false;
        const flag = row.synthetic;
        if (flag === true) return true;
        if (typeof flag === "string" && ["1", "true", "yes", "sim"].indexOf(flag.trim().toLowerCase()) >= 0) {
            return true;
        }
        const deviceId = String(row.device_id || "").trim().toLowerCase();
        const patientId = String(row.patient_id || "").trim().toLowerCase();
        if (patientId.indexOf("smoke-") === 0) return true;
        const haystack = deviceId + " " + patientId;
        for (let i = 0; i < SYNTHETIC_TOKENS.length; i += 1) {
            if (haystack.indexOf(SYNTHETIC_TOKENS[i]) >= 0) return true;
        }
        return false;
    }

    return {
        ONLINE_WITHIN_MS,
        parseStamp,
        isRecentLiveStamp,
        resolveFleetOnline,
        isSyntheticDevice
    };
}));
