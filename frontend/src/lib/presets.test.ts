import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS, DEFAULT_PRESET, TRANSIT_PRESETS, isPreset, isTransit, parsePreset, presetLabel, resolvePreset, presetSaid, twoPointsOnly } from "./presets.ts";

test("the picker offers every ride type in PLAN's table", () => {
  assert.deepEqual(
    PRESETS.map((p) => p.id),
    [
      "default",
      "trailmaxxing",
      "group-ride",
      "mass-ride",
      "mountain-goat",
      "mountain-bike",
      "gravel",
      "fast",
      "cargo",
      "ebike",
      "bikeshare",
      "novice",
      "bike-transit",
      "bikeshare-transit",
      "rebalance",
    ],
  );
});

test("the transit ride types are named as the owner named them, scheduled with live departures, two points only", () => {
  // TRANSIT-ASSIST (Stephen, 2026-10-12 20:35): emoji names, said in words; the ids are unchanged.
  assert.equal(presetLabel("bike-transit"), "Own Bike + 🚆🚌");
  assert.equal(presetLabel("bikeshare-transit"), "Bikeshare + 🚶🚆🚌");
  assert.equal(presetSaid("bike-transit"), "Own bike plus train or bus");
  assert.equal(presetSaid("bikeshare-transit"), "Bikeshare plus walk, train or bus");
  // A name without emoji is said as it shows.
  assert.equal(presetSaid("rebalance"), "Rebalance Ride");
  for (const id of TRANSIT_PRESETS) {
    const description = PRESETS.find((p) => p.id === id)!.description;
    assert.match(description, /[Ss]cheduled times, with WMATA's live departures on a trip leaving now/);
    assert.ok(isTransit(id) && twoPointsOnly(id));
  }
  assert.ok(twoPointsOnly("bikeshare") && !isTransit("bikeshare"));
  assert.ok(!twoPointsOnly("default"));
});

test("Novice and Nervous takes Riding with kids' place, said in plain words (v0.7.0)", () => {
  const novice = PRESETS.find((p) => p.id === "novice");
  assert.ok(novice);
  assert.equal(novice.label, "Novice and Nervous");
  // What the plan says it does: one step busier, short detours, transit or bikeshare where only a busy road connects.
  assert.match(novice.description, /one step busier/);
  assert.match(novice.description, /short detours/);
  assert.match(novice.description, /transit or bikeshare/);
  // Two sentences at most (the simplicity rule).
  assert.ok(novice.description.split(". ").length <= 2);
  assert.equal(PRESETS.some((p) => (p.id as string) === "kids"), false);
  // Old links, saved settings and GPX files that name "kids" open it.
  assert.equal(parsePreset("kids"), "novice");
  assert.equal(resolvePreset("kids"), "novice");
  assert.equal(resolvePreset("novice"), "novice");
  assert.equal(resolvePreset("nope"), null);
  assert.equal(isPreset("kids"), false);
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

test("no card says it favors trails; Trailmaxxing's says it finds the least stressful route (OWNER-DECISIONS 256, 257)", () => {
  for (const preset of PRESETS) {
    assert.doesNotMatch(preset.description, /favou?rs? trails/, preset.id);
    const says = /least stressful route/.test(preset.description);
    assert.equal(says, preset.id === "trailmaxxing", preset.id);
  }
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
