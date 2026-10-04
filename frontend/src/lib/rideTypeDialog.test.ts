import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { startDials } from "./dials.ts";
import { choose, closesDialog, initialCard, isCustom, nextFocus } from "./rideTypeDialog.ts";
import { loopStops } from "./loop.ts";
import { loopChangeSaid, loopToggledSaid } from "./pointText.ts";

test("Tab and Shift+Tab wrap inside the dialog", () => {
  assert.equal(nextFocus(0, 4, false), 1);
  assert.equal(nextFocus(3, 4, false), 0);
  assert.equal(nextFocus(0, 4, true), 3);
  assert.equal(nextFocus(2, 4, true), 1);
  // Focus outside the dialog (index -1) comes back to its first or last item.
  assert.equal(nextFocus(-1, 4, false), 0);
  assert.equal(nextFocus(-1, 4, true), 3);
  assert.equal(nextFocus(0, 0, false), -1);
});

test("Escape closes the dialog; other keys do not", () => {
  assert.ok(closesDialog("Escape"));
  for (const key of ["Enter", " ", "Tab", "q"]) assert.equal(closesDialog(key), false, key);
});

test("the dialog opens on the ride type in use", () => {
  PRESETS.forEach((preset, index) => assert.equal(initialCard(preset.id), index));
});

test("choosing a ride type moves the sliders to its start and keeps the ride time", () => {
  const current = { stress: 12, hills: 70, when: "weekday_rush" as const, carrying: null, assist: false };
  for (const preset of PRESETS) {
    const next = choose(preset.id, null, current);
    const start = startDials(preset.id);
    assert.equal(next.stress, start.stress, preset.id);
    assert.equal(next.hills, start.hills, preset.id);
    assert.equal(next.when, "weekday_rush", preset.id);
  }
  assert.equal(choose("cargo", "people", current).stress, startDials("cargo", "people").stress);
});

test("a moved slider is custom; the ride type's own start is not", () => {
  for (const preset of PRESETS) {
    const start = startDials(preset.id);
    assert.equal(isCustom(preset.id, start), false, preset.id);
    assert.equal(isCustom(preset.id, { ...start, stress: start.stress === 0 ? 5 : 0 }), true, preset.id);
    assert.equal(isCustom(preset.id, { ...start, hills: start.hills - 5 }), true, preset.id);
  }
  // Switching the load is not a custom setting.
  assert.equal(isCustom("cargo", startDials("cargo", "people")), false);
});

test("choosing Cargo Bike keeps electric assist; assist is not a custom setting", () => {
  const assisted = { ...startDials("cargo", "cargo", null, true) };
  assert.equal(choose("cargo", "people", assisted).assist, true);
  assert.equal(choose("default", null, assisted).assist, false);
  assert.equal(isCustom("cargo", assisted), false);
});

test("the old browsers' Esc closes the dialog too, and an unknown ride type opens on the first card", () => {
  // Mutation review r1, FE19 and FE20.
  assert.ok(closesDialog("Esc"));
  assert.equal(initialCard("no-such-ride" as (typeof PRESETS)[number]["id"]), 0);
});

test("choosing another ride type keeps avoid gravel", () => {
  const current = { ...startDials("default"), avoidGravel: true };
  assert.equal(choose("cargo", "cargo", current).avoidGravel, true);
  assert.equal(choose("cargo", "cargo", startDials("default")).avoidGravel, undefined);
});

test("choosing another ride type keeps Make it a loop, through a Mass Ride and back (OWNER-DECISIONS 374)", () => {
  const looped = { ...startDials("default"), loop: true };
  for (const preset of PRESETS) assert.equal(choose(preset.id, null, looped).loop, true, preset.id);
  assert.equal("loop" in choose("cargo", "cargo", startDials("default")), false, "off stays absent");
  assert.equal("loop" in choose("cargo", "cargo", { ...startDials("default"), loop: false }), false);
  // Between two ride types with a loop nothing is renamed, so nothing is said.
  const fast = choose("fast", null, looped);
  assert.equal(loopStops("fast", fast.loop), true);
  assert.equal(loopChangeSaid({ preset: "default", dials: looped }, { preset: "fast", dials: fast }, 3), null);
  // Into Mass Ride, which has no loop, the points are renamed: loop off.
  const mass = choose("mass-ride", null, fast);
  assert.equal(mass.loop, true, "kept, unused");
  assert.equal(loopStops("mass-ride", mass.loop), false);
  assert.equal(
    loopChangeSaid({ preset: "fast", dials: fast }, { preset: "mass-ride", dials: mass }, 3),
    loopToggledSaid(false, 3),
  );
  // Out of it again the loop comes back: loop on.
  const back = choose("default", null, mass);
  assert.equal(loopStops("default", back.loop), true);
  assert.equal(
    loopChangeSaid({ preset: "mass-ride", dials: mass }, { preset: "default", dials: back }, 3),
    loopToggledSaid(true, 3),
  );
  // Without the loop, no ride type change says anything.
  const plain = startDials("default");
  assert.equal(
    loopChangeSaid({ preset: "default", dials: plain }, { preset: "mass-ride", dials: choose("mass-ride", null, plain) }, 3),
    null,
  );
});
