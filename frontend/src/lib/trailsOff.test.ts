// "Trails off" (OWNER-DECISIONS 463; the 2026-09-26 "Every type, roadways ok"): one switch on every ride type.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PRESETS } from "./presets.ts";
import { dialFields, fitDials, startDials, trailsAreOff, trailsOffLocked } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { panelView, TRAILS_OFF_HINT, TRAILS_OFF_HOW, TRAILS_OFF_LABEL } from "./dialsPanel.ts";
import { choose } from "./rideTypeDialog.ts";
import { rideSummary } from "./rideSummary.ts";

test("trails off is off by default on every ride type except Mass Ride, which is always off-trail", () => {
  for (const preset of PRESETS) {
    const start = startDials(preset.id);
    assert.equal(start.trailsOff, undefined, preset.id);
    assert.equal(dialFields(start).trails_off, undefined, preset.id);
    assert.equal(trailsAreOff(preset.id, start), preset.id === "mass-ride", preset.id);
    assert.equal(trailsOffLocked(preset.id), preset.id === "mass-ride", preset.id);
  }
});

test("trails off travels in the link and the request on every ride type, and an old link means trails on", () => {
  for (const preset of PRESETS) {
    const dials = { ...startDials(preset.id), trailsOff: true };
    assert.equal(dialFields(dials).trails_off, true, preset.id);
    const hash = encodePlan([], preset.id, dials);
    assert.match(hash, /trailsoff=1/, preset.id);
    assert.equal(decodePlan(hash).dials.trailsOff, true, preset.id);
    // Off is not written; a link without it (every older link) is trails on.
    assert.doesNotMatch(encodePlan([], preset.id, startDials(preset.id)), /trailsoff/, preset.id);
    assert.equal(decodePlan(`#preset=${preset.id}&stress=40&hills=0`).dials.trailsOff, undefined, preset.id);
  }
  assert.equal(decodePlan("#preset=default&trailsoff=0").dials.trailsOff, undefined);
  assert.equal(fitDials("gravel", { trailsOff: true }).trailsOff, true);
});

test("a Mass Ride link without the flag is still trails off, and the flag stays for the next ride type", () => {
  const mass = decodePlan("#preset=mass-ride");
  assert.equal(trailsAreOff(mass.preset, mass.dials), true);
  const kept = choose("default", null, { ...startDials("default"), trailsOff: true });
  assert.equal(kept.trailsOff, true);
  assert.equal(choose("default", null, startDials("default")).trailsOff, undefined);
  assert.equal(choose("mass-ride", null, { ...startDials("default"), trailsOff: true }).trailsOff, true);
});

test("the panel offers the switch on every ride type, locked on and said so on Mass Ride", () => {
  for (const preset of PRESETS) {
    const view = panelView(preset.id, startDials(preset.id)).trailsOff;
    assert.equal(view.label, TRAILS_OFF_LABEL, preset.id);
    assert.equal(view.locked, preset.id === "mass-ride", preset.id);
    assert.equal(view.checked, preset.id === "mass-ride", preset.id);
    assert.ok(view.hint.includes(TRAILS_OFF_HINT), preset.id);
    assert.equal(view.how, TRAILS_OFF_HOW);
    const on = panelView(preset.id, { ...startDials(preset.id), trailsOff: true }).trailsOff;
    assert.equal(on.checked, true, preset.id);
  }
  assert.match(panelView("mass-ride", startDials("mass-ride")).trailsOff.hint, /always trails off/);
  assert.ok(TRAILS_OFF_HINT.length <= 150, "a description is read on every focus");
});

test("the hint says in plain words what is left out", () => {
  assert.match(TRAILS_OFF_HINT, /no bike paths, trails or stairs/);
  assert.match(TRAILS_OFF_HOW, /footway/);
  assert.match(TRAILS_OFF_HOW, /Chain Bridge/);
  assert.match(TRAILS_OFF_HOW, /one-way/);
  assert.match(TRAILS_OFF_HOW, /no route/);
});

test("turning it on does not make the ride type look custom, and the reset keeps it", () => {
  const dials = { ...startDials("default"), trailsOff: true };
  assert.equal(panelView("default", dials).reset, null);
  assert.equal(panelView("default", { ...dials, stress: 20 }).reset?.trailsOff, true);
});

test("the ride line names a trails-off ride, but not Mass Ride, which is always so", () => {
  assert.match(rideSummary("default", { ...startDials("default"), trailsOff: true }), /trails off/);
  assert.doesNotMatch(rideSummary("mass-ride", { ...startDials("mass-ride"), trailsOff: true }), /trails off/);
});

test("the switch is a real checkbox, labelled, and described by its hint; Mass Ride's stays in the Tab order", () => {
  const src = readFileSync(new URL("../DialsPanel.tsx", import.meta.url), "utf8");
  const block = src.slice(src.indexOf('<div className="dial trails-off">'), src.indexOf("Avoid gravel"));
  assert.match(block, /<label className="toggle">[\s\S]*<input\s+type="checkbox"/);
  assert.match(block, /aria-describedby=\{trailsOffHintId\}/);
  assert.match(block, /id=\{trailsOffHintId\}/);
  assert.match(block, /aria-disabled=\{view\.trailsOff\.locked \|\| undefined\}/);
  assert.doesNotMatch(block, /\sdisabled=/, "a disabled box leaves the Tab order");
});
