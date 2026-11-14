"use strict";

const assert = require("assert");
const path = require("path");
const logic = require(path.join(__dirname, "..", "..", "dashboard", "fleet_logic.js"));

const stale = {
    device_id: "ve30-smoke",
    online: false,
    timestamp: "2026-09-16T12:00:00Z",
    received_at: "2026-09-16T12:00:00Z",
};
assert.strictEqual(logic.resolveFleetOnline({ online: false }, stale, false), false);
assert.strictEqual(
    logic.resolveFleetOnline({ online: false }, { ...stale, timestamp: new Date().toISOString() }, false),
    false
);
assert.strictEqual(logic.resolveFleetOnline({}, { timestamp: new Date().toISOString() }, false), false);
assert.strictEqual(logic.resolveFleetOnline({}, { timestamp: new Date().toISOString() }, true), true);
assert.strictEqual(logic.resolveFleetOnline({}, stale, true), false);
assert.strictEqual(logic.resolveFleetOnline({}, { online: true }, false), true);

assert.strictEqual(logic.isSyntheticDevice({ device_id: "ve30-smoke" }), true);
assert.strictEqual(logic.isSyntheticDevice({ device_id: "VE30-PROBE-001" }), true);
assert.strictEqual(logic.isSyntheticDevice({ device_id: "VE30-TIMECHECK" }), true);
assert.strictEqual(logic.isSyntheticDevice({ patient_id: "smoke-pr14" }), true);
assert.strictEqual(logic.isSyntheticDevice({ device_id: "VE30-AA:BB:CC:DD:EE:FF", patient_id: "PAT-KEEP" }), false);

assert.strictEqual(logic.formatSteps(null), "—");
assert.strictEqual(logic.formatSteps(undefined), "—");
assert.strictEqual(logic.formatSteps(1678), Number(1678).toLocaleString("pt-BR"));
assert.strictEqual(logic.formatBloodPressure(null, 76), "—");
assert.strictEqual(logic.formatBloodPressure(118, 76), "118/76");

const kept = logic.carryLastActivity(
    { steps: 1678, blood_pressure_sys: 118, blood_pressure_dia: 76, last_steps_at: "t1", last_bp_at: "t1" },
    { heart_rate: 90, steps: null, blood_pressure_sys: null, blood_pressure_dia: null }
);
assert.strictEqual(kept.steps, 1678);
assert.strictEqual(kept.blood_pressure_sys, 118);
assert.strictEqual(kept.blood_pressure_dia, 76);
assert.strictEqual(kept.last_steps_at, "t1");
assert.strictEqual(kept.last_bp_at, "t1");

const empty = logic.carryLastActivity(null, { heart_rate: 72 });
assert.strictEqual(empty.steps, null);
assert.strictEqual(empty.blood_pressure_sys, null);

console.log("ok fleet_logic.js");
