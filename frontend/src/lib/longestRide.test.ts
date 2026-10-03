/**
 * The longest ride and the system weight (OWNER-DECISIONS 256, 264): the dials, the
 * link, the panel's inputs and the notes the planner's answer gets.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  LONGEST_MAX_M,
  LONGEST_MIN_M,
  SYSTEM_WEIGHT_MAX_KG,
  SYSTEM_WEIGHT_MIN_KG,
  dialFields,
  fitDials,
  fitLongest,
  fitWeight,
  offersLongestRide,
  startDials,
} from "./dials.ts";
import {
  LONGEST_LABEL,
  WEIGHT_LABEL,
  formatWeight,
  longestText,
  panelView,
  parseLongest,
  parseWeight,
  weightText,
} from "./dialsPanel.ts";
import { METRES_PER_MILE } from "./format.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { announceRoute, calmSearchNote, longestSaid } from "./summary.ts";
import type { RouteResponse } from "./api.ts";

const POINTS: [number, number][] = [
  [-77.0063, 38.8973],
  [-76.6158, 39.3074],
];
const SIXTY = Math.round(60 * METRES_PER_MILE);

test("the dial offers itself at the top of the traffic slider only, and not on a locked slider", () => {
  assert.ok(offersLongestRide("trailmaxxing", 100));
  assert.ok(offersLongestRide("default", 100));
  assert.ok(!offersLongestRide("default", 99));
  assert.ok(!offersLongestRide("trailmaxxing", 90));
  assert.ok(!offersLongestRide("mass-ride", 100), "Mass Ride's slider is locked at its lowest");
});

test("a longest ride is taken in the API's range, whole metres, and nothing else", () => {
  assert.equal(fitLongest(SIXTY), SIXTY);
  assert.equal(fitLongest(96561.4), 96561);
  assert.equal(fitLongest(LONGEST_MIN_M), LONGEST_MIN_M);
  assert.equal(fitLongest(LONGEST_MIN_M - 1), undefined);
  assert.equal(fitLongest(LONGEST_MAX_M + 1), undefined);
  assert.equal(fitLongest(Number.NaN), undefined);
  assert.equal(fitLongest("60"), undefined);
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
  assert.equal("max_distance_m" in dialFields(start), false);
  assert.equal("system_weight_kg" in dialFields(start), false);
  const fields = dialFields({ ...start, maxDistanceM: SIXTY, systemWeightKg: 110 });
  assert.equal(fields.max_distance_m, SIXTY);
  assert.equal(fields.system_weight_kg, 110);
  assert.equal("max_distance_m" in dialFields({ ...start, maxDistanceM: 5 }), false, "out of range is not sent");
});

test("fitDials keeps a good one and drops a bad one", () => {
  assert.equal(fitDials("trailmaxxing", { maxDistanceM: SIXTY }).maxDistanceM, SIXTY);
  assert.equal("maxDistanceM" in fitDials("trailmaxxing", { maxDistanceM: 3 }), false);
  assert.equal(fitDials("trailmaxxing", { systemWeightKg: 120 }).systemWeightKg, 120);
  assert.equal("systemWeightKg" in fitDials("trailmaxxing", { systemWeightKg: 10 }), false);
});

test("the link carries the longest ride in miles and the weight in kilograms, and old links have neither", () => {
  const dials = { ...startDials("trailmaxxing"), maxDistanceM: SIXTY, systemWeightKg: 110 };
  const hash = encodePlan(POINTS, "trailmaxxing", dials);
  assert.match(hash, /maxmi=60\.0/);
  assert.match(hash, /sysweight=110/);
  const plan = decodePlan(hash);
  assert.equal(plan.dials.maxDistanceM, SIXTY);
  assert.equal(plan.dials.systemWeightKg, 110);
  // An older link has neither: the defaults, and the traffic position it had.
  const old = decodePlan(encodePlan(POINTS, "trailmaxxing", startDials("trailmaxxing")));
  assert.equal(old.dials.maxDistanceM, undefined);
  assert.equal(old.dials.systemWeightKg, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&v=2&stress=100&hills=0&p=-77.0,38.9;-76.9,39.0").dials.stress, 100);
  // Nothing in the link when they are not set; and a nonsense value is dropped.
  assert.doesNotMatch(encodePlan(POINTS, "trailmaxxing", startDials("trailmaxxing")), /maxmi|sysweight/);
  assert.equal(decodePlan("#preset=trailmaxxing&maxmi=0").dials.maxDistanceM, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&maxmi=abc").dials.maxDistanceM, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&sysweight=900").dials.systemWeightKg, undefined);
});

test("the link's version is unchanged, and a version 2 link keeps its stress", () => {
  assert.match(encodePlan(POINTS, "default", startDials("default")), /v=2/);
  assert.equal(decodePlan("#preset=default&v=2&stress=70&hills=0").dials.stress, 70);
});

test("the panel shows the two inputs at the top of the slider and not below it", () => {
  const top = startDials("trailmaxxing");
  const view = panelView("trailmaxxing", top);
  assert.ok(view.longest && view.weight);
  assert.equal(view.longest.label, LONGEST_LABEL);
  assert.equal(view.weight.label, WEIGHT_LABEL);
  assert.match(LONGEST_LABEL, /miles/);
  assert.match(WEIGHT_LABEL, /pounds/);
  const below = panelView("trailmaxxing", { ...top, stress: 90 });
  assert.equal(below.longest, null);
  assert.equal(below.weight, null);
  assert.equal(panelView("default", startDials("default")).longest, null);
});

test("the longest ride's words say what it does, with miles first and kilometres in brackets", () => {
  const empty = panelView("trailmaxxing", startDials("trailmaxxing")).longest!;
  assert.equal(empty.value, "");
  assert.match(empty.hint, /Optional/);
  assert.match(empty.hint, /up to 1\.6 times the router's own route/);
  assert.match(empty.hint, /fewest heavy-traffic roads and very high stress junctions first/);
  const set = panelView("trailmaxxing", { ...startDials("trailmaxxing"), maxDistanceM: SIXTY }).longest!;
  assert.equal(set.value, "60");
  assert.match(set.hint, /Set to 60\.0 mi \(96\.6 km\)/);
  assert.match(set.hint, /shorter than the calmest route makes it use busier roads/);
  assert.match(set.rule, /^Enter 0\.7 to 621 miles, or leave it empty\.$/);
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
  assert.equal(parseLongest(""), undefined);
  assert.equal(parseLongest("  "), undefined);
  assert.equal(parseLongest("60"), SIXTY);
  assert.equal(parseLongest("60 mi"), SIXTY);
  assert.equal(parseLongest("60.0 miles"), SIXTY);
  assert.equal(parseLongest("0.1"), null);
  assert.equal(parseLongest("700"), null);
  assert.equal(parseLongest("-5"), null);
  assert.equal(parseLongest("sixty"), null);
  assert.equal(parseLongest("1e2"), null);
  assert.equal(parseWeight(""), undefined);
  assert.equal(parseWeight("198"), 90);
  assert.equal(parseWeight("198 lb"), 90);
  assert.equal(parseWeight("100"), null);
  assert.equal(parseWeight("400"), null);
  assert.equal(parseWeight("heavy"), null);
  assert.equal(longestText(undefined), "");
  assert.equal(longestText(SIXTY), "60");
  assert.equal(longestText(Math.round(12.34 * METRES_PER_MILE)), "12.3");
  assert.equal(weightText(undefined), "");
  assert.equal(weightText(90), "198");
});

test("back to the ride type's settings clears both", () => {
  const dials = { ...startDials("trailmaxxing"), maxDistanceM: SIXTY };
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

test("a route that could not be kept within the longest ride says so, in words", () => {
  const found = route({ limited: "max_distance", fits: false, max_distance_m: 80_467, max_distance_set: true });
  const note = calmSearchNote(found) ?? "";
  assert.match(note, /^No route within your longest ride \(50\.0 mi \(80\.5 km\)\) was found\./);
  assert.match(note, /The shortest found is 57\.7 mi \(92\.8 km\)\./);
  assert.match(announceRoute(found), /Longer than your longest ride of 50\.0 mi \(80\.5 km\): the shortest found\./);
  assert.equal(longestSaid(found), "Longer than your longest ride of 50.0 mi (80.5 km): the shortest found.");
  // Said for the default too, and never when it fits.
  assert.match(calmSearchNote(route({ limited: "max_distance", fits: false, max_distance_m: 80_467, max_distance_set: false })) ?? "", /^No route within the longest ride/);
  assert.equal(longestSaid(route({ fits: true, max_distance_m: 96_561 })), null);
  assert.equal(calmSearchNote(route({ fits: true, max_distance_m: 96_561, max_distance_set: true })), null);
  assert.doesNotMatch(announceRoute(route({ fits: true, max_distance_m: 96_561 })), /longest ride/);
});

test("a route found by a busier first route says why", () => {
  const note = calmSearchNote(route({ fits: true, fitted_at: 40, max_distance_m: 80_467, max_distance_set: true }, 78_000)) ?? "";
  assert.match(note, /Your longest ride \(50\.0 mi \(80\.5 km\)\) is shorter than the calmest route, so this one uses some busier roads to fit\./);
});

test("a long trip that could not be cut into legs says so; the span note is not said for Trailmaxxing's long trips", () => {
  assert.match(calmSearchNote(route({ limited: "split" })) ?? "", /could not cut this long trip into legs/);
  assert.match(calmSearchNote(route({ limited: "time" })) ?? "", /ran out of time/);
});
