import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { HILLS_MAX, HILLS_MIN, STRESS_MAX, TRAFFIC_TOLERANT_WARNING, startDials } from "./dials.ts";
import {
  AVOID_NOTE,
  CALM_HOW,
  DESCRIPTION_MAX_CHARS,
  SEEK_CALM_NOTE,
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
  // Trailmaxxing (OWNER-DECISIONS 194) and Riding with kids (240 (B)) start at the top, so their note is the
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
    assert.equal(traffic.note === undefined, preset.id !== "trailmaxxing" && preset.id !== "kids", preset.id);
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
  const near = panelView("default", dials, { ...dials, stress: 99 }).traffic.note ?? "";
  // The score's rate (8.5 at 99) capped by the worth bar every longer route must meet (435, "One rule": 4.4).
  assert.match(near, /^Calm detour: up to about 4\.4 mi \(7\.1 km\) of extra riding for every mile of busy road \(LTS 3\)/);
  const low = panelView("default", dials, { ...dials, stress: 85 }).traffic.note ?? "";
  assert.match(low, /^Calm detour: up to about 0\.6 mi/, "below the cap the rate decides");
  assert.match(near, /Twice that for a heavy-traffic road \(LTS 4\)\. Three times that for a road best avoided\./);
  assert.match(near, /many times the straight-line distance/);
  // The very top has no rate (OWNER-DECISIONS 256, 257, 271): the least stressful route towards the target distance.
  const topView = panelView("default", dials, { ...dials, stress: 100 }).traffic;
  const top = topView.note ?? "";
  assert.match(top, /^Calmest: finds the least stressful route towards your target distance, within a set limit\./);
  assert.doesNotMatch(top, /however far/, "the search has a ceiling (the spec review's NIT1)");
  // The description is read at every step: short, and the order is under "How this works" (the a11y review's N1).
  assert.ok(top.length < DESCRIPTION_MAX_CHARS, `${top.length} characters`);
  const how = topView.how ?? "";
  assert.equal(how, CALM_HOW);
  assert.match(how, /heavy-traffic roads \(LTS 4\) and very high stress junctions/);
  assert.match(how, /busy roads \(LTS 3\) and higher stress junctions/);
  assert.match(how, /Hills slider\. Then it takes the shorter way\./);
  assert.match(how, /A quiet street counts the same as a trail, except on Trailmaxxing, Cargo with passengers and Riding with kids, where low-stress streets \(LTS 2\) count a little extra\./);
  assert.match(how, /no further than 1\.25 times your target distance, or 1\.6 times the usual route/);
  assert.equal(panelView("default", dials, { ...dials, stress: 99 }).traffic.how, undefined, "only the top has it");
  assert.equal(panelView("mass-ride", startDials("mass-ride")).traffic.how, undefined);
  // Miles first, to a tenth below ten miles, and a rate that rises with the position.
  assert.match(calmNote(90) ?? "", /about 1\.7 mi \(2\.7 km\)/);
  assert.match(calmNote(85) ?? "", /about 0\.6 mi \(1\.0 km\)/);
  // Mass Ride's slider is locked and keeps its own note.
  assert.equal(panelView("mass-ride", startDials("mass-ride")).traffic.note, MASS_RIDE_TRAFFIC_NOTE);
});

test("no note says the planner favors trails (OWNER-DECISIONS 257 supersedes 202)", () => {
  // A quiet street counts the same as a trail: Trailmaxxing's note is the top's, as every ride type's.
  const dials = startDials("trailmaxxing");
  const note = panelView("trailmaxxing", dials).traffic.note ?? "";
  assert.match(note, /^Calmest: finds the least stressful route towards your target distance/);
  assert.match(panelView("trailmaxxing", dials).traffic.how ?? "", /A quiet street counts the same as a trail, except on Trailmaxxing, Cargo with passengers and Riding with kids, where low-stress streets \(LTS 2\) count a little extra\./);
  assert.doesNotMatch(CALM_HOW, /favou?rs? trails/);
  assert.equal(panelView("trailmaxxing", dials, { ...dials, stress: 80 }).traffic.note, undefined);
  for (const preset of PRESETS) {
    for (const stress of [85, 90, 95, 99, 100]) {
      const text = calmNote(stress, preset.id) ?? "";
      assert.doesNotMatch(text, /favou?rs? trails/, `${preset.id} ${stress}`);
    }
  }
  assert.equal(calmNote(100, "trailmaxxing"), calmNote(100, "default"));
});

test("the slider's right-hand label is the calm end", () => {
  assert.deepEqual(panelView("default", startDials("default")).traffic.ends, ["Traffic tolerant", "Balanced", "Calm at any cost"]);
});

test("the calm note is short sentences, since a screen reader hears it as the slider's description at every step", () => {
  for (const stress of [85, 90, 95, 100]) {
    for (const preset of ["default", "trailmaxxing"] as const) {
      const note = calmNote(stress, preset) ?? "";
      assert.ok(note.length > 0, `${preset} ${stress}`);
      for (const sentence of note.split(/(?<=\.)\s+/)) {
        assert.ok(sentence.split(/\s+/).length <= 25, `${preset} ${stress}: "${sentence}"`);
      }
    }
  }
});

test("at the top of the traffic slider, seeking climbs says it only breaks ties, and the target stays offered (OWNER-DECISIONS 298(3))", () => {
  const dials = { ...startDials("trailmaxxing"), hills: 60 };
  const view = panelView("trailmaxxing", dials);
  assert.equal(view.hills.note, SEEK_CALM_NOTE);
  assert.match(SEEK_CALM_NOTE, /only chooses between equally calm routes, preferring the one that climbs more/);
  assert.notEqual(view.target, null, "the Target distance dial is still offered while seeking");
  assert.notEqual(view.weight, null);
  // Below the top, seeking is the search among alternatives it was.
  assert.equal(panelView("default", { ...startDials("default"), hills: 60 }).hills.note, SEEK_NOTE);
});
