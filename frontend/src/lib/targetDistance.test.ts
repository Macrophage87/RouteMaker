/**
 * The target distance and the system weight (OWNER-DECISIONS 256, 264, 271): the dials,
 * the link, the panel's inputs and the notes the planner's answer gets.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  TARGET_MAX_M,
  TARGET_MIN_M,
  SYSTEM_WEIGHT_MAX_KG,
  SYSTEM_WEIGHT_MIN_KG,
  dialFields,
  fitDials,
  fitTarget,
  fitWeight,
  offersTargetDistance,
  startDials,
} from "./dials.ts";
import {
  TARGET_LABEL,
  WEIGHT_LABEL,
  formatWeight,
  targetText,
  panelView,
  parseTarget,
  parseWeight,
  weightText,
} from "./dialsPanel.ts";
import { METRES_PER_MILE } from "./format.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { announceRoute, calmSearchNote, overTarget, targetSaid } from "./summary.ts";
import type { RouteResponse } from "./api.ts";

const POINTS: [number, number][] = [
  [-77.0063, 38.8973],
  [-76.6158, 39.3074],
];
const SIXTY = Math.round(60 * METRES_PER_MILE);

test("the dial offers itself at the top of the traffic slider only, and not on a locked slider", () => {
  assert.ok(offersTargetDistance("trailmaxxing", 100));
  assert.ok(offersTargetDistance("default", 100));
  assert.ok(!offersTargetDistance("default", 99));
  assert.ok(!offersTargetDistance("trailmaxxing", 90));
  assert.ok(!offersTargetDistance("mass-ride", 100), "Mass Ride's slider is locked at its lowest");
});

test("a target distance is taken in the API's range, whole metres, and nothing else", () => {
  assert.equal(fitTarget(SIXTY), SIXTY);
  assert.equal(fitTarget(96561.4), 96561);
  assert.equal(fitTarget(TARGET_MIN_M), TARGET_MIN_M);
  assert.equal(fitTarget(TARGET_MIN_M - 1), undefined);
  assert.equal(fitTarget(TARGET_MAX_M + 1), undefined);
  assert.equal(fitTarget(Number.NaN), undefined);
  assert.equal(fitTarget("60"), undefined);
});

test("a system weight is taken between 68 and 140 kg", () => {
  assert.equal(fitWeight(90), 90);
  assert.equal(fitWeight(SYSTEM_WEIGHT_MIN_KG), 68);
  assert.equal(fitWeight(SYSTEM_WEIGHT_MAX_KG), 140);
  assert.equal(fitWeight(67), undefined);
  assert.equal(fitWeight(141), undefined);
  assert.equal(fitWeight(Number.POSITIVE_INFINITY), undefined);
});

test("the request carries them when set and not otherwise", () => {
  const start = startDials("trailmaxxing");
  assert.equal("target_distance_m" in dialFields(start), false);
  assert.equal("system_weight_kg" in dialFields(start), false);
  const fields = dialFields({ ...start, targetDistanceM: SIXTY, systemWeightKg: 110 });
  assert.equal(fields.target_distance_m, SIXTY);
  assert.equal(fields.system_weight_kg, 110);
  assert.equal("target_distance_m" in dialFields({ ...start, targetDistanceM: 5 }), false, "out of range is not sent");
});

test("fitDials keeps a good one and drops a bad one", () => {
  assert.equal(fitDials("trailmaxxing", { targetDistanceM: SIXTY }).targetDistanceM, SIXTY);
  assert.equal("targetDistanceM" in fitDials("trailmaxxing", { targetDistanceM: 3 }), false);
  assert.equal(fitDials("trailmaxxing", { systemWeightKg: 120 }).systemWeightKg, 120);
  assert.equal("systemWeightKg" in fitDials("trailmaxxing", { systemWeightKg: 10 }), false);
});

test("the link carries the target distance in miles and the weight in kilograms, and old links have neither", () => {
  const dials = { ...startDials("trailmaxxing"), targetDistanceM: SIXTY, systemWeightKg: 110 };
  const hash = encodePlan(POINTS, "trailmaxxing", dials);
  assert.match(hash, /targetmi=60\.0/);
  assert.match(hash, /sysweight=110/);
  const plan = decodePlan(hash);
  assert.equal(plan.dials.targetDistanceM, SIXTY);
  assert.equal(plan.dials.systemWeightKg, 110);
  // An older link has neither: the defaults, and the traffic position it had.
  const old = decodePlan(encodePlan(POINTS, "trailmaxxing", startDials("trailmaxxing")));
  assert.equal(old.dials.targetDistanceM, undefined);
  assert.equal(old.dials.systemWeightKg, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&v=2&stress=100&hills=0&p=-77.0,38.9;-76.9,39.0").dials.stress, 100);
  // Nothing in the link when they are not set; and a nonsense value is dropped.
  assert.doesNotMatch(encodePlan(POINTS, "trailmaxxing", startDials("trailmaxxing")), /targetmi|sysweight/);
  assert.equal(decodePlan("#preset=trailmaxxing&targetmi=0").dials.targetDistanceM, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&targetmi=abc").dials.targetDistanceM, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&sysweight=900").dials.systemWeightKg, undefined);
});

test("the link's version is unchanged, and a version 2 link keeps its stress", () => {
  assert.match(encodePlan(POINTS, "default", startDials("default")), /v=2/);
  assert.equal(decodePlan("#preset=default&v=2&stress=70&hills=0").dials.stress, 70);
});

test("the panel shows the two inputs at the top of the slider and not below it", () => {
  const top = startDials("trailmaxxing");
  const view = panelView("trailmaxxing", top);
  assert.ok(view.target && view.weight);
  assert.equal(view.target.label, TARGET_LABEL);
  assert.equal(view.weight.label, WEIGHT_LABEL);
  assert.match(TARGET_LABEL, /miles/);
  assert.match(WEIGHT_LABEL, /pounds/);
  const below = panelView("trailmaxxing", { ...top, stress: 90 });
  assert.equal(below.target, null);
  assert.equal(below.weight, null);
  assert.equal(panelView("default", startDials("default")).target, null);
});

test("the target distance's words say what it does, with miles first and kilometres in brackets", () => {
  const empty = panelView("trailmaxxing", startDials("trailmaxxing")).target!;
  assert.equal(empty.value, "");
  assert.match(empty.hint, /^Optional\. The route aims at or under this/);
  assert.match(empty.hint, /up to 1\.6 times the router's own route, where the extra miles avoid enough busy road/);
  assert.match(empty.hint, /fewest heavy-traffic roads and very high stress junctions first/);
  const set = panelView("trailmaxxing", { ...startDials("trailmaxxing"), targetDistanceM: SIXTY }).target!;
  assert.equal(set.value, "60");
  assert.match(set.hint, /Set to 60\.0 mi \(96\.6 km\)/);
  // OWNER-DECISIONS 271: soft, with a hard ceiling of 1.25 times it, and the overage said.
  assert.match(set.hint, /goes past it only where the extra miles avoid enough busy road/);
  assert.match(set.hint, /never past 75\.0 mi \(120\.7 km\), and says how far over it is/);
  assert.match(set.hint, /shorter than the calmest route makes it use busier roads/);
  assert.doesNotMatch(set.hint, /no longer than/);
  assert.match(set.rule, /^Enter 0\.7 to 621 miles, or leave it empty\.$/);
});

test("the label is the target distance, not a maximum", () => {
  assert.equal(TARGET_LABEL, "Target distance (miles)");
});

test("the weight's words give pounds first and say the default", () => {
  const empty = panelView("trailmaxxing", startDials("trailmaxxing")).weight!;
  assert.match(empty.hint, /Left empty, it is 198 lb \(90 kg\)/);
  const passengers = panelView("cargo", { ...startDials("cargo", "people"), stress: 100 }).weight!;
  assert.match(passengers.hint, /265 lb \(120 kg\)/);
  const set = panelView("trailmaxxing", { ...startDials("trailmaxxing"), systemWeightKg: 140 }).weight!;
  assert.equal(set.value, "309");
  assert.match(set.hint, /Set to 309 lb \(140 kg\)/);
  assert.equal(formatWeight(68), "150 lb (68 kg)");
  assert.match(empty.rule, /^Enter 150 to 309 pounds, or leave it empty\.$/);
});

test("what is typed is read in miles and pounds, and a bad entry is refused", () => {
  assert.equal(parseTarget(""), undefined);
  assert.equal(parseTarget("  "), undefined);
  assert.equal(parseTarget("60"), SIXTY);
  assert.equal(parseTarget("60 mi"), SIXTY);
  assert.equal(parseTarget("60.0 miles"), SIXTY);
  assert.equal(parseTarget("0.1"), null);
  assert.equal(parseTarget("700"), null);
  assert.equal(parseTarget("-5"), null);
  assert.equal(parseTarget("sixty"), null);
  assert.equal(parseTarget("1e2"), null);
  assert.equal(parseWeight(""), undefined);
  assert.equal(parseWeight("198"), 90);
  assert.equal(parseWeight("198 lb"), 90);
  assert.equal(parseWeight("100"), null);
  assert.equal(parseWeight("400"), null);
  assert.equal(parseWeight("heavy"), null);
  assert.equal(targetText(undefined), "");
  assert.equal(targetText(SIXTY), "60");
  assert.equal(targetText(Math.round(12.34 * METRES_PER_MILE)), "12.3");
  assert.equal(weightText(undefined), "");
  assert.equal(weightText(90), "198");
});

test("back to the ride type's settings clears both", () => {
  const dials = { ...startDials("trailmaxxing"), targetDistanceM: SIXTY };
  assert.deepEqual(panelView("trailmaxxing", dials).reset, startDials("trailmaxxing"));
  const heavy = { ...startDials("trailmaxxing"), systemWeightKg: 120 };
  assert.deepEqual(panelView("trailmaxxing", heavy).reset, startDials("trailmaxxing"));
  assert.equal(panelView("trailmaxxing", startDials("trailmaxxing")).reset, null);
});

function route(search: Partial<NonNullable<RouteResponse["calm_search"]>>, distance = 92_792): RouteResponse {
  return {
    preset: "trailmaxxing",
    distance_m: distance,
    duration_s: 20_000,
    climb_m: 100,
    dials: { stress: 100, hills: 0, when: "weekend", carrying: null },
    calm_search: { rate: 10, rounds: 1, excluded: 1, limited: null, ...search },
  } as RouteResponse;
}

test("a route where none fits the target says so, and how far over it is, in words", () => {
  // OWNER-DECISIONS 267: the least stressful route found, flagged.
  const found = route({
    limited: "target_distance",
    fits: false,
    target_distance_m: 80_467,
    target_distance_set: true,
    over_target_m: 12_325,
  });
  const note = calmSearchNote(found) ?? "";
  assert.match(note, /^No route within your target distance \(50\.0 mi \(80\.5 km\)\) was found\./);
  assert.match(note, /This is the least stressful one found\. It is 7\.7 mi \(12\.3 km\) over your target\./);
  assert.doesNotMatch(note, /shortest/);
  assert.match(announceRoute(found), /7\.7 mi \(12\.3 km\) over your target of 50\.0 mi \(80\.5 km\)\./);
  assert.equal(targetSaid(found), "7.7 mi (12.3 km) over your target of 50.0 mi (80.5 km).");
});

test("a route past the target to avoid busier roads always says how far over it is", () => {
  // OWNER-DECISIONS 271: "always flags the overage", miles first.
  const over = route({ fits: false, target_distance_m: 80_467, target_distance_set: true, over_target_m: 4_828 });
  assert.equal(calmSearchNote(over), "It is 3.0 mi (4.8 km) over your target, to avoid busier roads.");
  assert.match(announceRoute(over), /3\.0 mi \(4\.8 km\) over your target of 50\.0 mi \(80\.5 km\)\./);
  // Never when it is within it, or with no target.
  const within = route({ fits: true, target_distance_m: 96_561, target_distance_set: true, over_target_m: 0 });
  assert.equal(targetSaid(within), null);
  assert.equal(calmSearchNote(within), null);
  assert.doesNotMatch(announceRoute(within), /target/);
  const none = route({ fits: null, target_distance_m: null, target_distance_set: false, over_target_m: null });
  assert.equal(targetSaid(none), null);
  assert.equal(calmSearchNote(none), null);
});

test("how far over is read from the answer's search or from a candidate's own field", () => {
  assert.equal(overTarget(route({ over_target_m: 500 })), 500);
  assert.equal(overTarget(route({ over_target_m: 0 })), null);
  assert.equal(overTarget({ calm_search: null, over_target_m: 300 }), 300);
  assert.equal(overTarget({ calm_search: null, over_target_m: null }), null);
});

test("a route found by a busier first route says why", () => {
  const note = calmSearchNote(route({ fits: true, fitted_at: 40, target_distance_m: 80_467, target_distance_set: true }, 78_000)) ?? "";
  assert.match(note, /Your target distance \(50\.0 mi \(80\.5 km\)\) is shorter than the calmest route, so this one uses some busier roads to fit\./);
});

test("a long trip that could not be cut into legs says so; the span note is not said for Trailmaxxing's long trips", () => {
  assert.match(calmSearchNote(route({ limited: "split" })) ?? "", /could not cut this long trip into legs/);
  assert.match(calmSearchNote(route({ limited: "time" })) ?? "", /ran out of time/);
});
