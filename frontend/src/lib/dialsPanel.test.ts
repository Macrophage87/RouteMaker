import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { HILLS_MAX, HILLS_MIN, STRESS_MAX, TRAFFIC_TOLERANT_WARNING, startDials } from "./dials.ts";
import {
  AVOID_NOTE,
  MASS_RIDE_HILLS_NOTE,
  MASS_RIDE_TRAFFIC_NOTE,
  SEEK_NOTE,
  calmNote,
  panelView,
  routeWarning,
} from "./dialsPanel.ts";

// Mutation review r1, UI1-UI5: these decisions lived in the components, which
// have no DOM harness, and each could be broken with every test green.

test("the traffic-tolerant warning shows at the bottom of the slider, following the drag", () => {
  const dials = startDials("default");
  assert.equal(panelView("default", dials).warning, null);
  assert.equal(panelView("default", dials, { ...dials, stress: 10 }).warning, TRAFFIC_TOLERANT_WARNING);
  assert.equal(panelView("default", { ...dials, stress: 0 }, { ...dials, stress: 50 }).warning, null);
  assert.equal(panelView("fast", startDials("fast")).warning, TRAFFIC_TOLERANT_WARNING);
  // Mass Ride's slider is locked at 0 and says why instead.
  assert.equal(panelView("mass-ride", startDials("mass-ride")).warning, null);
});

test("Mass Ride's traffic slider is locked, and says why; no other ride type's is", () => {
  // Trailmaxxing starts at the top (OWNER-DECISIONS 194), so its note is the
  // calm detour's; every other ride type starts with none.
  const mass = panelView("mass-ride", startDials("mass-ride")).traffic;
  assert.equal(mass.disabled, true);
  assert.equal(mass.note, MASS_RIDE_TRAFFIC_NOTE);
  assert.equal(mass.max, STRESS_MAX);
  for (const preset of PRESETS) {
    if (preset.id === "mass-ride") continue;
    const traffic = panelView(preset.id, startDials(preset.id)).traffic;
    assert.equal(traffic.disabled, false, preset.id);
    assert.equal(traffic.note, calmNote(startDials(preset.id).stress, preset.id), preset.id);
    assert.equal(traffic.note === undefined, preset.id !== "trailmaxxing", preset.id);
    assert.equal(traffic.max, STRESS_MAX, preset.id);
  }
});

test("Mass Ride's hills slider stops at Fastest and says why; the others seek", () => {
  const mass = panelView("mass-ride", startDials("mass-ride")).hills;
  assert.deepEqual([mass.min, mass.max], [HILLS_MIN, 0]);
  assert.equal(mass.note, MASS_RIDE_HILLS_NOTE);
  assert.deepEqual(mass.ends, ["Avoid hills", "", "Fastest"]);
  const dials = startDials("default");
  const hills = panelView("default", dials).hills;
  assert.deepEqual([hills.min, hills.max], [HILLS_MIN, HILLS_MAX]);
  assert.deepEqual(hills.ends, ["Avoid hills", "Fastest", "Seek hills"]);
  assert.equal(hills.note, undefined);
  assert.equal(panelView("default", dials, { ...dials, hills: 40 }).hills.note, SEEK_NOTE);
  assert.equal(panelView("default", dials, { ...dials, hills: -40 }).hills.note, AVOID_NOTE);
});

test("the words follow the position being dragged", () => {
  const dials = startDials("default");
  const view = panelView("default", dials, { ...dials, stress: 50, hills: -90 });
  assert.equal(view.traffic.words, "Balanced");
  assert.equal(view.hills.words, "Avoids hills");
});

test("electric assist is offered on Cargo Bike alone, with its note while it is on", () => {
  for (const preset of PRESETS) {
    const view = panelView(preset.id, startDials(preset.id));
    assert.equal(view.assistToggle, preset.id === "cargo", preset.id);
    assert.equal(view.assistNote, false, preset.id);
  }
  assert.equal(panelView("cargo", startDials("cargo", "cargo", null, true)).assistNote, true);
});

test("going back to the ride type's settings resets the sliders and keeps the rest", () => {
  const start = startDials("cargo", "people", "weekend", true);
  assert.equal(panelView("cargo", start).reset, null);
  const moved = { ...start, stress: 40, hills: 20 };
  assert.deepEqual(panelView("cargo", moved).reset, start);
});

test("the route summary warns for a traffic-tolerant plan, and only then", () => {
  assert.equal(routeWarning("default", { stress: 0 }), TRAFFIC_TOLERANT_WARNING);
  assert.equal(routeWarning("default", { stress: 50 }), null);
  assert.equal(routeWarning("mass-ride", { stress: 0 }), null);
  assert.equal(routeWarning("default", undefined), null);
});

test("the top of the traffic slider says what it does, before it plans anything", () => {
  // OWNER-DECISIONS 163 and 164: a long calm detour is chosen with its cost in view.
  const dials = startDials("default");
  assert.equal(calmNote(80), undefined);
  assert.equal(panelView("default", dials, { ...dials, stress: 80 }).traffic.note, undefined);
  const top = panelView("default", dials, { ...dials, stress: 100 }).traffic.note ?? "";
  assert.match(top, /^Calm detour: up to about 10 mi \(16 km\) of extra riding for every mile of busy road \(LTS 3\)/);
  assert.match(top, /twice that for a heavy-traffic road \(LTS 4\) and three times for a road best avoided/);
  assert.match(top, /many times the straight line/);
  // Miles first, to a tenth below ten miles, and a rate that rises with the position.
  assert.match(calmNote(90) ?? "", /about 1\.8 mi \(2\.9 km\)/);
  assert.match(calmNote(85) ?? "", /about 0\.6 mi \(1\.0 km\)/);
  // Mass Ride's slider is locked and keeps its own note.
  assert.equal(panelView("mass-ride", startDials("mass-ride")).traffic.note, MASS_RIDE_TRAFFIC_NOTE);
});

test("Trailmaxxing's note says in plain words that it favours trails and may add miles", () => {
  // OWNER-DECISIONS 202: only Trailmaxxing rewards each mile of trail.
  const dials = startDials("trailmaxxing");
  const note = panelView("trailmaxxing", dials).traffic.note ?? "";
  assert.match(note, /^Calm detour: up to about 10 mi \(16 km\)/);
  assert.match(note, /Trailmaxxing also favours trails, so it may add miles to ride one/);
  // It fades with the slider, and is gone where there is no calm detour.
  assert.match(panelView("trailmaxxing", dials, { ...dials, stress: 90 }).traffic.note ?? "", /favours trails/);
  assert.equal(panelView("trailmaxxing", dials, { ...dials, stress: 80 }).traffic.note, undefined);
  // No other ride type says it, even at the top of the slider.
  for (const preset of PRESETS) {
    if (preset.id === "trailmaxxing" || preset.id === "mass-ride") continue;
    const top = panelView(preset.id, startDials(preset.id), { ...startDials(preset.id), stress: 100 }).traffic.note ?? "";
    assert.doesNotMatch(top, /favours trails/, preset.id);
  }
  assert.doesNotMatch(calmNote(100) ?? "", /favours trails/);
});

test("the slider's right-hand label is the calm end", () => {
  assert.deepEqual(panelView("default", startDials("default")).traffic.ends, ["Traffic tolerant", "Balanced", "Calm at any cost"]);
});
