// Ride mode's Calmer and Flatter buttons (the owner, 2026-10-23): lib/rideEase.ts runs here, and RideMode's wiring is
// read as source, as the other ride tests do.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { startDials, stressWords, hillsWords, type Dials } from "./dials.ts";
import { CALMER_STEPS, EASE_AT_END, EASE_NAME, EASE_SAME, EASE_SHOWN, FLATTER_STEPS, easeFinding, eased, sameLine } from "./rideEase.ts";

const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
const dials = (stress: number, hills: number): Dials => ({ ...startDials("default"), stress, hills });

test("calmer: each press is the next step up the traffic slider, until 95, short of the target-distance top", () => {
  const seen: number[] = [];
  let d: Dials | null = dials(70, 0);
  while ((d = eased("default", d, "calmer"))) seen.push(d.stress);
  assert.deepEqual(seen, [80, 90, 95]);
  // 0 and 10 both read "Traffic tolerant".
  assert.equal(eased("default", dials(0, 0), "calmer")?.stress, 20);
  // Between steps: the next one up whose words differ, never the same position or the same words again.
  assert.equal(eased("default", dials(72, 0), "calmer")?.stress, 80);
  assert.equal(eased("default", dials(76, 0), "calmer")?.stress, 90);
  assert.equal(eased("default", dials(95, 0), "calmer"), null);
  assert.equal(eased("default", dials(100, 0), "calmer"), null);
  // The hills and everything else are left as they were.
  assert.equal(eased("default", dials(70, -30), "calmer")?.hills, -30);
});

test("calmer: never past the ride type's own top (Mass Ride's traffic slider is locked at 0)", () => {
  assert.equal(eased("mass-ride", { ...startDials("mass-ride") }, "calmer"), null);
});

test("flatter: each press is the next step down the hills slider, until 1% at the end", () => {
  const seen: number[] = [];
  let d: Dials | null = dials(70, 100);
  while ((d = eased("mountain-goat", d, "flatter"))) seen.push(d.hills);
  assert.deepEqual(seen, [50, 0, -40, -100]);
  assert.equal(eased("default", dials(70, -100), "flatter"), null);
  assert.equal(eased("default", dials(70, -60), "flatter")?.hills, -100);
  // Already "Easy up to 1%" (-95): -100 reads the same, so there is no further step; -85 is 2%.
  assert.equal(eased("default", dials(70, -95), "flatter"), null);
  assert.equal(eased("default", dials(70, -85), "flatter")?.hills, -100);
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

test("same line: a new route made of the old line's own points is the same route", () => {
  const line: [number, number][] = Array.from({ length: 20 }, (_, i) => [-77 + i * 0.001, 38.9]);
  // From the rider's spot (not on the old line's points) onto the rest of the old line.
  assert.equal(sameLine([[-76.99951, 38.90002], ...line.slice(1)], line), true);
  const other: [number, number][] = line.map(([x, y], i) => (i > 5 ? [x, y + 0.002] : [x, y]));
  assert.equal(sameLine(other, line), false);
  assert.equal(sameLine([], line), false);
  assert.equal(EASE_SAME.flatter, "Same route: no less steep way from here.");
});

test("the words: in the name and said, the symbol alone on screen", () => {
  assert.match(EASE_NAME.calmer, /^Calmer: less traffic/);
  assert.match(EASE_NAME.flatter, /^Flatter: fewer hills/);
  assert.equal(EASE_AT_END.calmer, "Already the calmest route.");
  assert.equal(easeFinding("default", dials(80, 0), "calmer"), `Finding a calmer route. ${stressWords(80)}.`);
  assert.equal(easeFinding("default", dials(70, -40), "flatter"), "Finding a flatter route. Easy up to 5%.");
});

test("ride: the buttons re-plan from here with the ride's own dials, kept only when a route was found", () => {
  // Every re-plan and detour asks with the ride's dials, not Plan's.
  assert.doesNotMatch(ride, /\{ \.\.\.dials, loop: false \}/);
  assert.match(ride, /requestRoute\(to, preset, \{ dials: \{ \.\.\.dialsRef\.current, loop: false \}/);
  // The press: a step, then Re-plan from here's own path (the way ahead, the U-turn rules), undone if nothing came.
  assert.match(ride, /dialsRef\.current = next;[\s\S]{0,400}await replan\(here, undefined, true\);/);
  assert.match(ride, /if \(press\.outcome !== "found" && replanTicket\.current === press\.ticket && dialsRef\.current === next\) dialsRef\.current = was;/);
  // Not counted as riding past a U-turn; the same line is said as such.
  assert.match(ride, /stopped: \(heading === null && !turnRound\) \|\| press !== null/);
  assert.match(ride, /sameLine\(found\.geometry\.coordinates, press\.before\.geometry\.coordinates\)\) note = EASE_SAME\[press\.which\];/);
  // In More's panel (Stephen 2026-10-24), not the side buttons; not on a route everyone shares, nor once arrived;
  // named in full, the symbol and short words shown (each within the name, so a voice user can say what they see).
  const panel = ride.slice(ride.indexOf('className="ride-mode-settings"'), ride.indexOf("<RideSettingsFields prefs={prefs}"));
  const rail = ride.slice(ride.indexOf('<div className="ride-rail"'), ride.indexOf("{/* The bottom panel"));
  assert.match(panel, /\{!fixed && !ride\.arrived && \(\s*<div className="ride-change"/);
  assert.match(panel, /\(\["calmer", "flatter"\] as const\)\.map/);
  assert.match(panel, /onClick=\{\(\) => fromMore\(\(\) => void ease\(which\)\)\}\s+aria-label=\{EASE_NAME\[which\]\}/);
  assert.match(panel, /<Icon name=\{which === "calmer" \? "traffic-down" : "hills-down"\} size=\{26\} \/>\s*\{EASE_SHOWN\[which\]\}/);
  assert.doesNotMatch(rail, /ease\(which\)/);
  for (const which of ["calmer", "flatter"] as const) assert.ok(EASE_NAME[which].toLowerCase().includes(EASE_SHOWN[which].toLowerCase()));
});
