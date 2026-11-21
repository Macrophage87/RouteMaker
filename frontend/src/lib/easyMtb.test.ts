// "Easy MTB trails" (the owner, 2026-11-08: "allow trailmaxxing to use MTB trails too", "But it's opt in there too",
// "And default"): one switch, off by default, on Default and Trailmaxxing only, in the link (`easymtb=1`), the
// request (`easy_mtb`) and a saved route's dials; the answer's `easy_mtb` says a harder trail or the map being down.
import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { EASY_MTB_PRESETS, dialFields, easyMtbOn, fitDials, offersEasyMtb, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { EASY_MTB_LABEL, EASY_MTB_LOCKED_HINT, panelView } from "./dialsPanel.ts";
import { EASY_MTB_HARDER_SHORT, EASY_MTB_NO_MAP, EASY_MTB_NO_MAP_SHORT, easyMtbNote } from "./easyMtb.ts";
import { choose } from "./rideTypeDialog.ts";
import { rideSummary } from "./rideSummary.ts";
import { REACH_DEFAULT, reachBody } from "./reach.ts";
import { ES } from "../i18n/es.ts";

test("offered on every bike of the rider's own on the standard graph, and off by default", () => {
  // Since 2026-11-21 (the Surface setting) every bike of the rider's own on the standard graph but Gravel and Mountain Goat, whose off-road graph has the trails already (core/presets.py's).
  assert.deepEqual([...EASY_MTB_PRESETS], ["default", "trailmaxxing", "group-ride", "fast", "cargo", "novice", "tandem"]);
  for (const preset of PRESETS) {
    const start = startDials(preset.id);
    assert.equal(start.easyMtb, undefined, preset.id);
    assert.equal(dialFields(start).easy_mtb, undefined, preset.id);
    assert.equal(offersEasyMtb(preset.id), EASY_MTB_PRESETS.includes(preset.id), preset.id);
    // Since 2026-11-21 it is the Surface picker's third choice (lib/surface.ts), not a switch of its own.
    const view = panelView(preset.id, start);
    const offered = view.surface?.options.some(([id, label]) => id === "easy-mtb" && label === EASY_MTB_LABEL) ?? false;
    // Mountain Bike's level 1 is the same choice by name.
    assert.equal(offered, offersEasyMtb(preset.id) || preset.id === "mountain-bike", preset.id);
    if (offered) assert.notEqual(view.surface?.value, "easy-mtb");
  }
});

test("on, it travels in the link, the request and back; on another ride type it is dropped", () => {
  for (const preset of ["default", "trailmaxxing"] as const) {
    const dials = fitDials(preset, { ...startDials(preset), easyMtb: true });
    assert.equal(dials.easyMtb, true);
    assert.equal(dialFields(dials).easy_mtb, true);
    const hash = encodePlan([], preset, dials);
    assert.match(hash, /easymtb=1/);
    assert.equal(decodePlan(hash).dials.easyMtb, true);
    assert.equal(easyMtbOn(preset, dials), true);
    assert.match(rideSummary(preset, dials), /easy MTB trails/);
  }
  for (const preset of ["road-bike", "ebike", "mountain-bike", "mass-ride"] as const) {
    assert.equal(fitDials(preset, { ...startDials(preset), easyMtb: true }).easyMtb, undefined, preset);
    assert.equal(decodePlan(`#preset=${preset}&v=2&easymtb=1`).dials.easyMtb, undefined, preset);
  }
  // An older link has none: off.
  assert.equal(decodePlan("#preset=default&v=2&stress=70&hills=0").dials.easyMtb, undefined);
});

test("Keep to roads wins: the choice is not offered and the (i) says why; changing ride type keeps it where it is offered", () => {
  const both = fitDials("default", { ...startDials("default"), easyMtb: true, trailsOff: true });
  const view = panelView("default", both);
  assert.equal(view.surface?.value, "gravel");
  assert.equal(view.surface?.options.some(([id]) => id === "easy-mtb"), false);
  assert.ok(view.surface?.info.some(([label, said]) => label === EASY_MTB_LABEL && said === EASY_MTB_LOCKED_HINT));
  assert.equal(easyMtbOn("default", both), false);
  const on = fitDials("default", { ...startDials("default"), easyMtb: true });
  assert.equal(choose("trailmaxxing", null, on).easyMtb, true);
  assert.equal(choose("ebike", null, on).easyMtb, undefined);
  // Going back to the ride type's settings keeps the rider's switch, as Keep to roads.
  const moved = { ...on, stress: 20 };
  assert.equal(panelView("default", moved).reset?.easyMtb, true);
});

test("Reach does not take it", () => {
  const on = fitDials("default", { ...startDials("default"), easyMtb: true });
  const body = reachBody([[-77.03, 38.9]], "default", on, REACH_DEFAULT);
  assert.equal("easy_mtb" in body, false);
});

test("the notice: a harder trail it found no way round, or the off-road map down; nothing otherwise", () => {
  assert.equal(easyMtbNote(null), null);
  assert.equal(easyMtbNote({ easy_mtb: null }), null);
  assert.equal(easyMtbNote({ easy_mtb: { max_level: 1, harder_m: 0, limited: null } }), null);
  const harder = easyMtbNote({ easy_mtb: { max_level: 1, harder_m: 800, limited: "no_way_round" } });
  assert.ok(harder);
  assert.match(harder.text, /rated 2 or harder/);
  // A harder level held (the Surface setting): the level above it.
  const level3 = easyMtbNote({ easy_mtb: { max_level: 3, harder_m: 800, limited: "no_way_round" } });
  assert.match(level3?.text ?? "", /rated 4 or harder/);
  assert.match(harder.text, /0\.5 mi|800 m/);
  assert.equal(harder.short, EASY_MTB_HARDER_SHORT);
  assert.deepEqual(easyMtbNote({ easy_mtb: { max_level: 1, harder_m: null, limited: "no_offroad_graph" } }), {
    text: EASY_MTB_NO_MAP,
    short: EASY_MTB_NO_MAP_SHORT,
  });
  assert.ok(EASY_MTB_NO_MAP_SHORT.length <= 45);
  assert.ok(EASY_MTB_HARDER_SHORT.length <= 45);
});

test("every Easy MTB phrase is in Spanish with its {places}", () => {
  for (const phrase of [EASY_MTB_LABEL, EASY_MTB_LOCKED_HINT, EASY_MTB_NO_MAP, EASY_MTB_NO_MAP_SHORT, EASY_MTB_HARDER_SHORT]) {
    assert.ok(ES[phrase], phrase);
  }
});
