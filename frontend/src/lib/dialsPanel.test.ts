import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { HILLS_MAX, HILLS_MIN, STRESS_MAX, TRAFFIC_TOLERANT_WARNING, hillsWords, startDials } from "./dials.ts";
import {
  AVOID_NOTE,
  CALM_HOW,
  DESCRIPTION_MAX_CHARS,
  SEEK_CALM_NOTE,
  MASS_RIDE_HILLS_NOTE,
  MASS_RIDE_TRAFFIC_NOTE,
  SEEK_NOTE,
  TOLERATE_CALM_NOTE,
  TOLERATE_NOTE,
  HILLS_NOTE_SHORT,
  RIDE_SIZE_NOTE,
  RIDE_SIZE_NOTE_SHORT,
  calmNote,
  calmNoteShort,
  panelView,
  rideSizeView,
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
  // Trailmaxxing (OWNER-DECISIONS 194) and Novice and Nervous (v0.7.0) start at the top, so their note is the
  // calm detour's; every other ride type starts with none.
  const mass = panelView("mass-ride", startDials("mass-ride")).traffic;
  assert.equal(mass.disabled, true);
  assert.equal(mass.note, MASS_RIDE_TRAFFIC_NOTE);
  assert.equal(mass.max, STRESS_MAX);
  for (const preset of PRESETS) {
    if (preset.id === "mass-ride") continue;
    const traffic = panelView(preset.id, startDials(preset.id)).traffic;
    assert.equal(traffic.disabled, false, preset.id);
    assert.equal(traffic.noteSaid ?? traffic.note, calmNote(startDials(preset.id).stress, preset.id), preset.id);
    assert.equal(traffic.note === undefined, preset.id !== "trailmaxxing" && preset.id !== "novice", preset.id);
    assert.equal(traffic.max, STRESS_MAX, preset.id);
  }
});

test("the hills slider is in grade percent and Mass Ride's stops at 8%; Mountain Goat's seeks", () => {
  // Stephen, 2026-10-23: "Can the slider positions just be percent?"
  const mass = panelView("mass-ride", startDials("mass-ride")).hills;
  assert.deepEqual([mass.min, mass.max, mass.step], [1, 8, 1]);
  assert.equal(mass.note, MASS_RIDE_HILLS_NOTE);
  assert.deepEqual(mass.ends, ["1%", "", "8%"]);
  const dials = startDials("default");
  const hills = panelView("default", dials).hills;
  assert.deepEqual([hills.min, hills.max, hills.step], [1, 15, 1]);
  assert.deepEqual(hills.ends, ["1%", "8%", "15%"]);
  // Each whole percent on the slider is a dial position that reads back as that percent.
  for (let pct = 1; pct <= 15; pct++) {
    const dial = hills.scale!.fromSlider(pct);
    assert.ok(dial >= HILLS_MIN && dial <= HILLS_MAX);
    assert.equal(hills.scale!.toSlider(dial), pct);
    assert.equal(hillsWords(dial, false), `Easy up to ${pct}%`);
  }
  assert.equal(hills.scale!.toSlider(0), 8);
  assert.equal(hills.note, undefined);
  assert.equal(panelView("default", dials, { ...dials, hills: 40 }).hills.noteSaid, TOLERATE_NOTE);
  assert.equal(panelView("default", dials, { ...dials, hills: 40 }).hills.words, "Easy up to 11%");
  assert.equal(panelView("default", dials, { ...dials, hills: -40 }).hills.noteSaid, AVOID_NOTE);
  assert.match(TOLERATE_NOTE, /never a busier one/);
  assert.match(TOLERATE_NOTE, /16 mi \(25 km\)/);
  const goat = startDials("mountain-goat");
  const climbing = panelView("mountain-goat", goat).hills;
  assert.deepEqual(climbing.ends, ["Avoid hills", "Fastest", "Seek hills"]);
  assert.deepEqual([climbing.min, climbing.max, climbing.scale], [HILLS_MIN, HILLS_MAX, undefined]);
  assert.equal(climbing.noteSaid, SEEK_NOTE);
  assert.equal(climbing.words, "Seeks hills");
  for (const preset of PRESETS) {
    if (preset.id === "mass-ride") continue;
    const ends = panelView(preset.id, startDials(preset.id)).hills.ends;
    assert.equal(ends[2], preset.id === "mountain-goat" ? "Seek hills" : "15%", preset.id);
  }
});

test("the E-bike ride type starts fine with hills (242)", () => {
  const ebike = startDials("ebike");
  assert.ok(ebike.hills > 0);
  const view = panelView("ebike", ebike).hills;
  assert.equal(view.noteSaid, TOLERATE_NOTE);
  assert.equal(view.words, hillsWords(ebike.hills, false));
});

test("the words follow the position being dragged", () => {
  const dials = startDials("default");
  const view = panelView("default", dials, { ...dials, stress: 50, hills: -90 });
  assert.equal(view.traffic.words, "Balanced");
  assert.equal(view.hills.words, "Easy up to 2%");
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
  const near = panelView("default", dials, { ...dials, stress: 99 }).traffic.noteSaid ?? "";
  // The score's rate (8.5 at 99) capped by the worth bar every longer route must meet (435, "One rule": 4.4).
  assert.match(near, /^Calm detour: up to about 4\.4 mi \(7\.1 km\) of extra riding for every mile of busy road \(LTS 3\)/);
  const low = panelView("default", dials, { ...dials, stress: 85 }).traffic.noteSaid ?? "";
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
  assert.match(how, /A quiet street counts the same as a trail, except on Trailmaxxing and Cargo with passengers, where low-stress streets \(LTS 2\) count a little extra\./);
  assert.match(how, /Novice and Nervous treats every road as one step busier and goes no further than 1\.4 times the usual route\./);
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
  assert.match(panelView("trailmaxxing", dials).traffic.how ?? "", /A quiet street counts the same as a trail, except on Trailmaxxing and Cargo with passengers, where low-stress streets \(LTS 2\) count a little extra\./);
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
  // Seeking climbs is Mountain Goat's alone since FOLLOWUP-HILLS-TOLERATE (242).
  const dials = { ...startDials("mountain-goat"), stress: STRESS_MAX, hills: 60 };
  const view = panelView("mountain-goat", dials);
  assert.equal(view.hills.noteSaid, SEEK_CALM_NOTE);
  assert.match(SEEK_CALM_NOTE, /only chooses between equally calm routes, preferring the one that climbs more/);
  assert.notEqual(view.target, null, "the Target distance dial is still offered while seeking");
  // Below the top, seeking is the search among alternatives it was.
  assert.equal(panelView("mountain-goat", { ...startDials("mountain-goat"), hills: 60 }).hills.noteSaid, SEEK_NOTE);
});

test("at the top of the traffic slider, fine with hills says the calmest route decides (242)", () => {
  const view = panelView("trailmaxxing", { ...startDials("trailmaxxing"), hills: 60 });
  assert.equal(view.hills.noteSaid, TOLERATE_CALM_NOTE);
  assert.equal(panelView("default", { ...startDials("default"), hills: 60 }).hills.noteSaid, TOLERATE_NOTE);
});

test("each dial shows one short line, and its full note is read and is behind its (i) (P10)", () => {
  const dials = startDials("default");
  const near = panelView("default", dials, { ...dials, stress: 99 }).traffic;
  assert.equal(near.note, "Calm detour: up to 4.4 mi (7.1 km) extra per busy mile avoided.");
  assert.equal(near.note, calmNoteShort(99));
  assert.equal(near.noteSaid, calmNote(99));
  // The top's note is short already: shown and read as it is, with the order behind the (i).
  const top = panelView("default", dials, { ...dials, stress: 100 }).traffic;
  assert.deepEqual([top.note, top.noteSaid], [calmNote(100), undefined]);
  // Mass Ride's locked slider keeps its note as it is.
  assert.equal(panelView("mass-ride", startDials("mass-ride")).traffic.noteSaid, undefined);
  for (const full of [SEEK_NOTE, SEEK_CALM_NOTE, TOLERATE_NOTE, TOLERATE_CALM_NOTE, AVOID_NOTE]) {
    const short = HILLS_NOTE_SHORT.get(full) ?? "";
    assert.ok(short.length > 0 && short.length <= 60, short);
  }
  assert.equal(panelView("default", dials, { ...dials, hills: 40 }).hills.note, "Climbs up to this grade cost only their time.");
  assert.equal(panelView("default", dials, { ...dials, hills: -40 }).hills.note, "Grades past this one cost extra.");
  const size = rideSizeView(500);
  assert.deepEqual([size.note, size.noteSaid], [RIDE_SIZE_NOTE_SHORT, RIDE_SIZE_NOTE]);
  assert.equal(RIDE_SIZE_NOTE_SHORT, "Sets group length; route unchanged.");
});
