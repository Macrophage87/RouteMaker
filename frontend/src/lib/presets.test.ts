import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS, DEFAULT_PRESET, isPreset, parsePreset } from "./presets.ts";

test("the picker offers every ride type in PLAN's table", () => {
  assert.deepEqual(
    PRESETS.map((p) => p.id),
    [
      "default",
      "trailmaxxing",
      "group-ride",
      "mass-ride",
      "mountain-goat",
      "gravel",
      "fast",
      "cargo",
      "ebike",
    ],
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
  for (const junk of ["", "Mass Ride", "beginner", "recovery", "cargo-bike", null, undefined, 3, "__proto__", "toString"]) {
    assert.equal(parsePreset(junk), DEFAULT_PRESET, String(junk));
    assert.equal(isPreset(junk), false, String(junk));
  }
  for (const preset of PRESETS) assert.equal(parsePreset(preset.id), preset.id);
});

test("no ride type is described by a headcount", () => {
  // PLAN.md, Routing model: pace and posture distinguish Group Ride from Mass
  // Ride, not rider count, so the picker does not name one.
  const count = /\d|\b(two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|forty|fifty|dozen|hundred|thousand)\b/i;
  for (const preset of PRESETS) assert.doesNotMatch(preset.description, count, preset.id);
});
