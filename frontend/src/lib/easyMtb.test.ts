// "Easy MTB trails" (the owner, 2026-11-08: "allow trailmaxxing to use MTB trails too", "But it's opt in there too",
// "And default"): one switch, off by default, on Default and Trailmaxxing only, in the link (`easymtb=1`), the
// request (`easy_mtb`) and a saved route's dials; the answer's `easy_mtb` says a harder trail or the map being down.
import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { EASY_MTB_PRESETS, dialFields, easyMtbOn, fitDials, offersEasyMtb, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { EASY_MTB_HINT, EASY_MTB_LABEL, EASY_MTB_LOCKED_HINT, panelView } from "./dialsPanel.ts";
import { EASY_MTB_HARDER_SHORT, EASY_MTB_NO_MAP, EASY_MTB_NO_MAP_SHORT, easyMtbNote } from "./easyMtb.ts";
import { choose } from "./rideTypeDialog.ts";
import { rideSummary } from "./rideSummary.ts";
import { REACH_DEFAULT, reachBody } from "./reach.ts";
import { ES } from "../i18n/es.ts";

test("offered on Default and Trailmaxxing alone, and off by default", () => {
  assert.deepEqual([...EASY_MTB_PRESETS], ["default", "trailmaxxing"]);
  for (const preset of PRESETS) {
    const start = startDials(preset.id);
    assert.equal(start.easyMtb, undefined, preset.id);
    assert.equal(dialFields(start).easy_mtb, undefined, preset.id);
    assert.equal(offersEasyMtb(preset.id), preset.id === "default" || preset.id === "trailmaxxing", preset.id);
    const view = panelView(preset.id, start);
    assert.equal(view.easyMtb === null, !offersEasyMtb(preset.id), preset.id);
    if (view.easyMtb) {
      assert.equal(view.easyMtb.label, EASY_MTB_LABEL);
      assert.equal(view.easyMtb.checked, false);
      assert.equal(view.easyMtb.hint, EASY_MTB_HINT);
    }
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
  for (const preset of ["fast", "gravel", "mountain-bike", "mass-ride"] as const) {
    assert.equal(fitDials(preset, { ...startDials(preset), easyMtb: true }).easyMtb, undefined, preset);
    assert.equal(decodePlan(`#preset=${preset}&v=2&easymtb=1`).dials.easyMtb, undefined, preset);
  }
  // An older link has none: off.
  assert.equal(decodePlan("#preset=default&v=2&stress=70&hills=0").dials.easyMtb, undefined);
});

test("Keep to roads wins: the switch shows off and says why; changing ride type keeps it where it is offered", () => {
  const both = fitDials("default", { ...startDials("default"), easyMtb: true, trailsOff: true });
  const view = panelView("default", both);
  assert.equal(view.easyMtb?.checked, false);
  assert.equal(view.easyMtb?.locked, true);
  assert.equal(view.easyMtb?.hint, EASY_MTB_LOCKED_HINT);
  assert.equal(easyMtbOn("default", both), false);
  const on = fitDials("default", { ...startDials("default"), easyMtb: true });
  assert.equal(choose("trailmaxxing", null, on).easyMtb, true);
  assert.equal(choose("gravel", null, on).easyMtb, undefined);
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
  for (const phrase of [EASY_MTB_LABEL, EASY_MTB_HINT, EASY_MTB_LOCKED_HINT, EASY_MTB_NO_MAP, EASY_MTB_NO_MAP_SHORT, EASY_MTB_HARDER_SHORT]) {
    assert.ok(ES[phrase], phrase);
  }
});
