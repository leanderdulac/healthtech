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
    // 30 min de medição + 15 min de reconexão lenta + folga. 2 h sem pacote fica offline.
    const ONLINE_WITHIN_MS = 50 * 60 * 1000;
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

    function asPositive(value) {
        if (value == null || value === "") return null;
        const n = Number(value);
        if (!Number.isFinite(n) || n <= 0) return null;
        return n;
    }

    function formatSteps(value) {
        if (value == null || value === "") return "—";
        const n = Number(value);
        if (!Number.isFinite(n) || n < 0) return "—";
        return Math.round(n).toLocaleString("pt-BR");
    }

    function formatBloodPressure(sys, dia) {
        const s = asPositive(sys);
        const d = asPositive(dia);
        if (s == null || d == null) return "—";
        return Math.round(s) + "/" + Math.round(d);
    }

    function activityStamp(row) {
        if (!row) return null;
        return row.received_at || row.last_seen || row.timestamp || null;
    }

    function validSpo2(value) {
        const n = Number(value);
        if (!Number.isFinite(n) || n < 50 || n > 100) return null;
        return n;
    }

    function carryLastActivity(previous, incoming) {
        const row = Object.assign({}, incoming || {});
        const prev = previous || {};
        const incomingSteps = asPositive(row.steps);
        if (incomingSteps != null) {
            row.steps = Math.round(incomingSteps);
            row.last_steps_at = row.last_steps_at || activityStamp(row);
        } else if (asPositive(prev.steps) != null) {
            row.steps = prev.steps;
            row.last_steps_at = prev.last_steps_at || activityStamp(prev);
        } else {
            row.steps = null;
            row.last_steps_at = null;
        }
        const incomingSys = asPositive(row.blood_pressure_sys);
        const incomingDia = asPositive(row.blood_pressure_dia);
        if (incomingSys != null && incomingDia != null) {
            row.blood_pressure_sys = incomingSys;
            row.blood_pressure_dia = incomingDia;
            row.last_bp_at = row.last_bp_at || activityStamp(row);
        } else if (asPositive(prev.blood_pressure_sys) != null && asPositive(prev.blood_pressure_dia) != null) {
            row.blood_pressure_sys = prev.blood_pressure_sys;
            row.blood_pressure_dia = prev.blood_pressure_dia;
            row.last_bp_at = prev.last_bp_at || activityStamp(prev);
        } else {
            row.blood_pressure_sys = null;
            row.blood_pressure_dia = null;
            row.last_bp_at = null;
        }
        const incomingSpo2 = validSpo2(row.spo2);
        if (incomingSpo2 != null) {
            row.spo2 = incomingSpo2;
            row.last_spo2_at = row.last_spo2_at || activityStamp(row);
        } else if (validSpo2(prev.spo2) != null) {
            row.spo2 = prev.spo2;
            row.last_spo2_at = prev.last_spo2_at || activityStamp(prev);
        } else {
            row.spo2 = null;
            row.last_spo2_at = null;
        }
        const model = typeof row.device_model === "string" ? row.device_model.trim() : "";
        if (!model) {
            const prevModel = typeof prev.device_model === "string" ? prev.device_model.trim() : "";
            if (prevModel) row.device_model = prev.device_model;
        }
        return row;
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
        isSyntheticDevice,
        asPositive,
        formatSteps,
        formatBloodPressure,
        carryLastActivity
    };
}));
