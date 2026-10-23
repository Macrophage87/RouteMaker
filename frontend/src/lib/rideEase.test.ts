// Ride mode's Calmer and Flatter buttons (the owner, 2026-10-23): lib/rideEase.ts runs here, and RideMode's wiring is
// read as source, as the other ride tests do.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { startDials, stressWords, hillsWords, type Dials } from "./dials.ts";
import { CALMER_STEPS, EASE_AT_END, EASE_NAME, EASE_TEXT, FLATTER_STEPS, easeFinding, eased } from "./rideEase.ts";

const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const dials = (stress: number, hills: number): Dials => ({ ...startDials("default"), stress, hills });

test("calmer: each press is the next step up the traffic slider, until 95, short of the target-distance top", () => {
  const seen: number[] = [];
  let d: Dials | null = dials(70, 0);
  while ((d = eased("default", d, "calmer"))) seen.push(d.stress);
  assert.deepEqual(seen, [80, 90, 95]);
  assert.equal(eased("default", dials(0, 0), "calmer")?.stress, 10);
  // Between steps: the next one up, never the same position again.
  assert.equal(eased("default", dials(72, 0), "calmer")?.stress, 80);
  assert.equal(eased("default", dials(95, 0), "calmer"), null);
  assert.equal(eased("default", dials(100, 0), "calmer"), null);
  // The hills and everything else are left as they were.
  assert.equal(eased("default", dials(70, -30), "calmer")?.hills, -30);
});

test("calmer: never past the ride type's own top (Mass Ride's traffic slider is locked at 0)", () => {
  assert.equal(eased("mass-ride", { ...startDials("mass-ride") }, "calmer"), null);
});

test("flatter: each press is the next step down the hills slider, until Avoids hills at the end", () => {
  const seen: number[] = [];
  let d: Dials | null = dials(70, 100);
  while ((d = eased("mountain-goat", d, "flatter"))) seen.push(d.hills);
  assert.deepEqual(seen, [50, 0, -40, -100]);
  assert.equal(eased("default", dials(70, -100), "flatter"), null);
  assert.equal(eased("default", dials(70, -60), "flatter")?.hills, -100);
  assert.equal(eased("default", dials(40, 0), "flatter")?.stress, 40);
});

test("the steps are where the sliders' words change: every press reads differently from the one before", () => {
  for (let i = 1; i < CALMER_STEPS.length; i += 1) {
    assert.notEqual(stressWords(CALMER_STEPS[i]), stressWords(CALMER_STEPS[i - 1]), String(CALMER_STEPS[i]));
  }
  for (let i = 1; i < FLATTER_STEPS.length; i += 1) {
    assert.notEqual(hillsWords(FLATTER_STEPS[i], true), hillsWords(FLATTER_STEPS[i - 1], true), String(FLATTER_STEPS[i]));
  }
});

test("the words: one on screen, the rest in the name and said", () => {
  assert.deepEqual(EASE_TEXT, { calmer: "Calmer", flatter: "Flatter" });
  assert.match(EASE_NAME.calmer, /^Calmer: less traffic/);
  assert.match(EASE_NAME.flatter, /^Flatter: fewer hills/);
  assert.equal(EASE_AT_END.calmer, "Already the calmest route.");
  assert.equal(easeFinding("default", dials(80, 0), "calmer"), `Finding a calmer route. ${stressWords(80)}.`);
  assert.equal(easeFinding("default", dials(70, -40), "flatter"), "Finding a flatter route. Gentler grades.");
});

test("ride: the buttons re-plan from here with the ride's own dials, kept only when a route was found", () => {
  // Every re-plan and detour asks with the ride's dials, not Plan's.
  assert.doesNotMatch(ride, /\{ \.\.\.dials, loop: false \}/);
  assert.match(ride, /requestRoute\(to, preset, \{ dials: \{ \.\.\.dialsRef\.current, loop: false \}/);
  // The press: a step, then Re-plan from here's own path (the way ahead, the U-turn rules), undone if nothing came.
  assert.match(ride, /dialsRef\.current = next;[\s\S]{0,200}const found = await replan\(here, undefined, true\);\n\s*if \(!found && dialsRef\.current === next\) dialsRef\.current = was;/);
  // Not on a route everyone shares, nor once arrived; named in full, one word shown.
  assert.match(ride, /\{!fixed && !ride\.arrived &&\n\s*\(\["calmer", "flatter"\] as const\)\.map/);
  assert.match(ride, /aria-label=\{EASE_NAME\[which\]\}/);
  assert.match(ride, /<span aria-hidden="true">\{EASE_TEXT\[which\]\}<\/span>/);
  assert.match(css, /\.ride \.ride-ease \{[^}]*font-size: 0\.8rem;/);
});
