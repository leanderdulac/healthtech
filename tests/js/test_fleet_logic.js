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

assert.strictEqual(logic.ONLINE_WITHIN_MS, 2 * 60 * 60 * 1000);
const nowMs = Date.parse("2026-11-14T21:00:00Z");
const fiftyMinAgo = new Date(nowMs - 50 * 60 * 1000).toISOString();
const twoHoursAgo = new Date(nowMs - 2 * 60 * 60 * 1000).toISOString();
const overTwoHours = new Date(nowMs - 2 * 60 * 60 * 1000 - 1000).toISOString();
assert.strictEqual(logic.isRecentLiveStamp(fiftyMinAgo, nowMs), true);
assert.strictEqual(logic.isRecentLiveStamp(twoHoursAgo, nowMs), true);
assert.strictEqual(logic.isRecentLiveStamp(overTwoHours, nowMs), false);
assert.strictEqual(logic.resolveFleetOnline({}, { received_at: fiftyMinAgo }, true, nowMs), true);
assert.strictEqual(logic.resolveFleetOnline({}, { received_at: overTwoHours }, true, nowMs), false);

assert.strictEqual(logic.isSyntheticDevice({ device_id: "ve30-smoke" }), true);
assert.strictEqual(logic.isSyntheticDevice({ device_id: "VE30-PROBE-001" }), true);
assert.strictEqual(logic.isSyntheticDevice({ device_id: "VE30-TIMECHECK" }), true);
assert.strictEqual(logic.isSyntheticDevice({ patient_id: "smoke-pr14" }), true);
assert.strictEqual(logic.isSyntheticDevice({ device_id: "VE30-AA:BB:CC:DD:EE:FF", patient_id: "PAT-KEEP" }), false);

console.log("ok fleet_logic.js");
