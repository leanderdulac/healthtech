"use strict";

const assert = require("assert");
const path = require("path");
const panel = require(path.join(__dirname, "..", "..", "dashboard", "settings_panel.js"));

assert.strictEqual(panel.shouldCloseOnKey({ key: "Escape" }), true);
assert.strictEqual(panel.shouldCloseOnKey({ key: "Esc" }), true);
assert.strictEqual(panel.shouldCloseOnKey({ key: "Enter" }), false);
assert.strictEqual(panel.shouldCloseOnKey(null), false);

const backdrop = { id: "settings-backdrop" };
assert.strictEqual(panel.shouldCloseOnBackdropClick({ target: backdrop }, backdrop), true);
assert.strictEqual(panel.shouldCloseOnBackdropClick({ target: { id: "other" } }, backdrop), false);
assert.strictEqual(panel.shouldCloseOnBackdropClick({ target: backdrop }, null), false);

const ctrl = panel.createSettingsController();
assert.strictEqual(ctrl.isOpen(), false);
assert.deepStrictEqual(ctrl.open(), { open: true });
assert.strictEqual(ctrl.isOpen(), true);
assert.deepStrictEqual(ctrl.handleKey({ key: "Enter" }), { closed: false });
assert.strictEqual(ctrl.isOpen(), true);
assert.deepStrictEqual(ctrl.handleKey({ key: "Escape" }), { closed: true });
assert.strictEqual(ctrl.isOpen(), false);

ctrl.open();
assert.deepStrictEqual(ctrl.handleBackdropClick({ target: backdrop }, backdrop), { closed: true });
assert.strictEqual(ctrl.isOpen(), false);

ctrl.open();
assert.deepStrictEqual(ctrl.close(), { open: false });
assert.strictEqual(ctrl.isOpen(), false);

console.log("ok settings_panel.js");
