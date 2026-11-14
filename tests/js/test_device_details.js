"use strict";

const assert = require("assert");
const path = require("path");
const details = require(path.join(__dirname, "..", "..", "dashboard", "device_details.js"));

assert.strictEqual(details.shouldCloseOnKey({ key: "Escape" }), true);
assert.strictEqual(details.shouldCloseOnKey({ key: "Esc" }), true);
assert.strictEqual(details.shouldCloseOnKey({ key: "Enter" }), false);
assert.strictEqual(details.shouldCloseOnKey(null), false);

const backdrop = { id: "device-details-backdrop" };
assert.strictEqual(details.shouldCloseOnBackdropClick({ target: backdrop }, backdrop), true);
assert.strictEqual(details.shouldCloseOnBackdropClick({ target: { id: "other" } }, backdrop), false);

assert.strictEqual(details.displayValue(null), "não informado");
assert.strictEqual(details.displayValue(""), "não informado");
assert.strictEqual(details.displayValue("3118007"), "3118007");

assert.strictEqual(details.unauthorizedMessage(401, false), details.MESSAGES.missingKey);
assert.strictEqual(details.unauthorizedMessage(403, true), details.MESSAGES.forbidden);

const presented = details.presentDeviceDetails({
    device_id: "VE30-AA:BB:CC:DD:EE:FF",
    device_model: "Galaxy Watch8 (4WHN)",
    device_label: null,
    patient_id: "PAT-KEEP",
    ingest_source: "ble_hband",
    app_version: "1.4.2",
    online: true,
    last_seen_local: "14/11/2026, 19:40:00",
    vitals: { heart_rate: 86, spo2: 97, steps: 1678, blood_pressure_sys: 118, blood_pressure_dia: 76 },
    region: { municipality_id: "3118007", ubs_id: "ubs-1", source: "cadastro", municipality_name: "Congonhas" }
});
assert.strictEqual(presented.title, "Detalhes do relógio");
assert.ok(presented.cadastroNote.indexOf("não é localização em tempo real") >= 0);
const watch = presented.blocks.find((b) => b.id === "watch");
assert.strictEqual(watch.rows.find((row) => row.label === "Paciente").value, "PAT-KEEP");
assert.strictEqual(watch.rows.find((row) => row.label === "Origem").value, "ble_hband");
const region = presented.blocks.find((b) => b.id === "region");
assert.strictEqual(region.rows[0].label, "municipality_id");
assert.strictEqual(region.rows[1].label, "ubs_id");
assert.strictEqual(region.rows[0].value, "3118007");
assert.strictEqual(region.rows[1].value, "ubs-1");
assert.strictEqual(region.rows.some((row) => /Congonhas|Mariana|Magé|Rio Claro/i.test(row.value + row.label)), false);

const emptyRegion = details.presentDeviceDetails({ region: {} });
const emptyBlock = emptyRegion.blocks.find((b) => b.id === "region");
assert.strictEqual(emptyBlock.rows[0].value, "não informado");
assert.strictEqual(emptyBlock.rows[1].value, "não informado");

const html = details.renderPresented(presented);
assert.ok(html.indexOf("Galaxy Watch8") >= 0);
assert.ok(html.indexOf("municipality_id") >= 0);
assert.ok(html.indexOf("Congonhas") < 0);
assert.ok(html.indexOf("<script") < 0);

const ctrl = details.createDetailsController();
assert.strictEqual(ctrl.isOpen(), false);
ctrl.open("VE30-1");
assert.strictEqual(ctrl.isOpen(), true);
assert.deepStrictEqual(ctrl.handleKey({ key: "Escape" }), { closed: true });
assert.strictEqual(ctrl.isOpen(), false);

console.log("ok device_details.js");
