import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { startDials } from "./dials.ts";
import { choose, closesDialog, initialCard, isCustom, nextFocus } from "./rideTypeDialog.ts";

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
  const current = { stress: 12, hills: 70, when: "weekday_rush" as const, carrying: null };
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
