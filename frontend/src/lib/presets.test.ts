import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS, DEFAULT_PRESET, isPreset, parsePreset } from "./presets.ts";

test("the picker offers exactly the contract's three presets", () => {
  assert.deepEqual(
    PRESETS.map((p) => p.id),
    ["default", "group-ride", "mass-ride"],
  );
});

test("each preset explains itself in a sentence", () => {
  // PLAN, First run: the modality picker explains each preset in a sentence
  // rather than assuming the vocabulary.
  for (const preset of PRESETS) {
    assert.ok(preset.label.length > 0, preset.id);
    assert.ok(preset.description.split(" ").length >= 5, preset.id);
  }
  assert.equal(new Set(PRESETS.map((p) => p.label)).size, PRESETS.length);
});

test("the default is one of the offered presets", () => {
  assert.ok(isPreset(DEFAULT_PRESET));
  assert.equal(DEFAULT_PRESET, "default");
});

test("anything unknown falls back to the default rather than reaching the API", () => {
  for (const junk of ["", "Mass Ride", "beginner", null, undefined, 3, "__proto__", "toString"]) {
    assert.equal(parsePreset(junk), DEFAULT_PRESET, String(junk));
    assert.equal(isPreset(junk), false, String(junk));
  }
  for (const preset of PRESETS) assert.equal(parsePreset(preset.id), preset.id);
});
