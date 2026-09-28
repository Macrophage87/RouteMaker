import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { HILLS_MAX, HILLS_MIN, STRESS_MAX, TRAFFIC_TOLERANT_WARNING, startDials } from "./dials.ts";
import { AVOID_NOTE, MASS_RIDE_HILLS_NOTE, MASS_RIDE_TRAFFIC_NOTE, SEEK_NOTE, panelView, routeWarning } from "./dialsPanel.ts";

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
  const mass = panelView("mass-ride", startDials("mass-ride")).traffic;
  assert.equal(mass.disabled, true);
  assert.equal(mass.note, MASS_RIDE_TRAFFIC_NOTE);
  assert.equal(mass.max, STRESS_MAX);
  for (const preset of PRESETS) {
    if (preset.id === "mass-ride") continue;
    const traffic = panelView(preset.id, startDials(preset.id)).traffic;
    assert.equal(traffic.disabled, false, preset.id);
    assert.equal(traffic.note, undefined, preset.id);
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
