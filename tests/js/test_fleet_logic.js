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

console.log("ok fleet_logic.js");
