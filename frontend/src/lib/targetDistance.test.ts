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
  DESCRIPTION_MAX_CHARS,
  TARGET_HOW,
  TARGET_LABEL,
  targetText,
  panelView,
  parseTarget,
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

test("a system weight is taken between 25 and 700 kg, to a tenth, and outside it as the nearer limit (OWNER-DECISIONS 337, 338)", () => {
  assert.equal(fitWeight(90), 90);
  assert.equal(fitWeight(90.72), 90.7, "kept to a tenth, so typed pounds come back as typed");
  assert.equal(fitWeight(48), 48);
  assert.equal(fitWeight(SYSTEM_WEIGHT_MIN_KG), 25);
  assert.equal(fitWeight(SYSTEM_WEIGHT_MAX_KG), 700);
  assert.equal(fitWeight(10), 25);
  assert.equal(fitWeight(500), 500);
  assert.equal(fitWeight(900), 700, "the top raised for pedicabs (352)");
  assert.equal(fitWeight(0), undefined);
  assert.equal(fitWeight(-5), undefined);
  assert.equal(fitWeight(Number.POSITIVE_INFINITY), undefined);
});

test("the request carries them when set and not otherwise", () => {
  const start = startDials("trailmaxxing");
  assert.equal("target_distance_m" in dialFields(start), false);
  assert.equal("system_weight_kg" in dialFields(start), false);
  const fields = dialFields({ ...start, targetDistanceM: SIXTY, systemWeightKg: 110 });
  assert.equal(fields.target_distance_m, SIXTY);
  assert.equal(fields.system_weight_kg, 110);
  // The API takes whole kilograms (core.api StrictInt): a tenth is rounded off when sent.
  assert.equal(dialFields({ ...start, systemWeightKg: 90.7 }).system_weight_kg, 91);
  assert.equal(dialFields({ ...start, systemWeightKg: 90.4 }).system_weight_kg, 90);
  assert.equal("target_distance_m" in dialFields({ ...start, targetDistanceM: 5 }), false, "out of range is not sent");
});

test("fitDials keeps a good one and drops a bad one", () => {
  assert.equal(fitDials("trailmaxxing", { targetDistanceM: SIXTY }).targetDistanceM, SIXTY);
  assert.equal("targetDistanceM" in fitDials("trailmaxxing", { targetDistanceM: 3 }), false);
  // The weight is never taken from a link (OWNER-DECISIONS 313).
  assert.equal("systemWeightKg" in fitDials("trailmaxxing", { systemWeightKg: 120 }), false);
});

test("the link carries the target distance in miles and never the weight; an old link's weight is ignored (OWNER-DECISIONS 313)", () => {
  const dials = { ...startDials("trailmaxxing"), targetDistanceM: SIXTY, systemWeightKg: 110 };
  const hash = encodePlan(POINTS, "trailmaxxing", dials);
  assert.match(hash, /targetmi=60\.0/);
  assert.doesNotMatch(hash, /sysweight|weight|110/);
  const plan = decodePlan(hash);
  assert.equal(plan.dials.targetDistanceM, SIXTY);
  assert.equal(plan.dials.systemWeightKg, undefined);
  assert.equal(decodePlan(`${hash}&sysweight=110`).dials.systemWeightKg, undefined, "an old link carrying it");
  // An older link has neither: the defaults, and the traffic position it had.
  const old = decodePlan(encodePlan(POINTS, "trailmaxxing", startDials("trailmaxxing")));
  assert.equal(old.dials.targetDistanceM, undefined);
  assert.equal(old.dials.systemWeightKg, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&v=2&stress=100&hills=0&p=-77.0,38.9;-76.9,39.0").dials.stress, 100);
  // Nothing in the link when they are not set; and a nonsense value is dropped.
  assert.doesNotMatch(encodePlan(POINTS, "trailmaxxing", startDials("trailmaxxing")), /targetmi|sysweight/);
  assert.equal(decodePlan("#preset=trailmaxxing&targetmi=0").dials.targetDistanceM, undefined);
  assert.equal(decodePlan("#preset=trailmaxxing&targetmi=abc").dials.targetDistanceM, undefined);

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

  assert.match(TARGET_LABEL, /miles/);
  const below = panelView("trailmaxxing", { ...top, stress: 90 });
  assert.equal(below.target, null);
  assert.equal(below.weight, false);
  assert.equal(panelView("default", startDials("default")).target, null);
});

test("the target distance's words say what it does, with miles first and kilometres in brackets", () => {
  const empty = panelView("trailmaxxing", startDials("trailmaxxing")).target!;
  assert.equal(empty.value, "");
  assert.match(empty.hint, /^Optional: the calmest route at or under this\./);
  assert.match(empty.hint, /Left empty, it may be up to 1\.6 times the usual route\./);
  // The description is read on every focus (the a11y review's N1): short, the detail under "How this works".
  assert.ok(empty.hint.length < DESCRIPTION_MAX_CHARS, `${empty.hint.length} characters`);
  assert.equal(empty.how, TARGET_HOW);
  assert.match(TARGET_HOW, /fewest heavy-traffic roads and very high stress junctions first/);
  assert.match(TARGET_HOW, /goes past your target only where the extra miles avoid enough busy road/);
  // OWNER-DECISIONS 435, "One rule": the miles up to the target are no longer free.
  assert.match(TARGET_HOW, /Up to your target, each extra mile must still avoid a tenth of a mile of busy road\./);
  assert.match(TARGET_HOW, /never past 1\.25 times it/);
  // OWNER-DECISIONS 287(3): a target below the calm route gives the calm route, flagged (the spec review's NIT1).
  assert.match(TARGET_HOW, /If the calmest route is longer than your target, it is still the one chosen, and the route summary says how far over your target it is\./);
  assert.doesNotMatch(TARGET_HOW, /makes it use busier roads/);
  const set = panelView("trailmaxxing", { ...startDials("trailmaxxing"), targetDistanceM: SIXTY }).target!;
  assert.equal(set.value, "60");
  assert.match(set.hint, /Set to 60\.0 mi \(96\.6 km\)/);
  // OWNER-DECISIONS 271: soft, with a hard ceiling of 1.25 times it.
  assert.match(set.hint, /never past 75\.0 mi \(120\.7 km\)\./);
  assert.ok(set.hint.length < DESCRIPTION_MAX_CHARS, `${set.hint.length} characters`);
  assert.doesNotMatch(set.hint, /no longer than/);
  // Metric in brackets in the rule too (the a11y review's N3).
  assert.match(set.rule, /^Enter 0\.7 to 621 miles \(1 to 1,000 km\), or leave it empty\.$/);
});

test("the label is the target distance, not a maximum", () => {
  assert.equal(TARGET_LABEL, "Target distance (miles)");
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
  assert.equal(targetText(undefined), "");
  assert.equal(targetText(SIXTY), "60");
  assert.equal(targetText(Math.round(12.34 * METRES_PER_MILE)), "12.3");
});

test("back to the ride type's settings clears both", () => {
  const dials = { ...startDials("trailmaxxing"), targetDistanceM: SIXTY };
  assert.deepEqual(panelView("trailmaxxing", dials).reset, startDials("trailmaxxing"));
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
  // OWNER-DECISIONS 267, 298(2): the least stressful route found, flagged, keyed on no_fit.
  const found = route({
    limited: "target_distance",
    no_fit: true,
    fits: false,
    target_distance_m: 80_467,
    target_distance_set: true,
    ceiling_m: 100_584,
    over_target_m: 12_325,
  });
  const note = calmSearchNote(found) ?? "";
  // No brackets in brackets (the spec review's NIT1).
  assert.match(note, /^No route within your target distance of 50\.0 mi \(80\.5 km\) was found\./);
  assert.doesNotMatch(note, /1\.25 times/, "within the ceiling: the ceiling is not mentioned");
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
  assert.match(note, /Your target distance of 50\.0 mi \(80\.5 km\) is shorter than the calmest route, so this one uses some busier roads to fit\./);
});

test("no route within the target or the ceiling: said truthfully, with the 1.25 times (OWNER-DECISIONS 298(2))", () => {
  const past = route(
    { limited: "target_distance", no_fit: true, fits: false, target_distance_m: 80_467, ceiling_m: 100_584, over_target_m: 30_000 },
    110_467,
  );
  assert.equal(
    calmSearchNote(past),
    "No route within your target distance of 50.0 mi (80.5 km), or within 1.25 times it, was found. This is the least stressful one found. It is 18.6 mi (30.0 km) over your target.",
  );
  // Without the route's own length, the target and the overage say it.
  assert.match(calmSearchNote({ ...past, distance_m: undefined } as never) ?? "", /or within 1\.25 times it/);
  // Exactly at the ceiling is within it.
  assert.doesNotMatch(calmSearchNote({ ...past, distance_m: 100_584 }) ?? "", /1\.25 times/);
});

test("the no-fit sentence is said only when no_fit is true, whatever limited and fits say", () => {
  for (const no_fit of [false, null, undefined]) {
    const r = route({ limited: "target_distance", no_fit, fits: false, target_distance_m: 80_467, over_target_m: 4_828 });
    const note = calmSearchNote(r) ?? "";
    assert.doesNotMatch(note, /No route within/, String(no_fit));
    assert.doesNotMatch(note, /least stressful one found/, String(no_fit));
    // An older API's "target_distance" says how far, and claims no reason it may not have.
    assert.equal(note, "It is 3.0 mi (4.8 km) over your target.", String(no_fit));
  }
  const fits = route({ limited: null, no_fit: false, fits: true, target_distance_m: 80_467, over_target_m: 0 });
  assert.equal(calmSearchNote(fits), null);
});

test("a search stopped at the ceiling says a calmer, longer route may exist, with the ceiling miles first", () => {
  const stopped = route({ limited: "ceiling", no_fit: false, fits: false, target_distance_m: 80_467, ceiling_m: 100_584, over_target_m: 4_828 });
  assert.equal(
    calmSearchNote(stopped),
    "The calmer-route search stopped at the longest distance it allows, 62.5 mi (100.6 km), so a calmer, longer route may exist. It is 3.0 mi (4.8 km) over your target, to avoid busier roads.",
  );
  assert.equal(
    calmSearchNote(route({ limited: "ceiling", ceiling_m: null })),
    "The calmer-route search stopped at the longest distance it allows, so a calmer, longer route may exist.",
  );
  assert.doesNotMatch(calmSearchNote(stopped) ?? "", /No route within/);
});

test("hills seeking at the top no longer stops the calmer-route search, and says nothing of it (OWNER-DECISIONS 298(3))", () => {
  assert.equal(calmSearchNote(route({ limited: "seeking" })), null);
  const over = route({ limited: null, fits: false, target_distance_m: 80_467, over_target_m: 4_828 });
  assert.equal(calmSearchNote(over), "It is 3.0 mi (4.8 km) over your target, to avoid busier roads.");
});

test("a long trip that could not be cut into legs says so; the span note is not said for Trailmaxxing's long trips", () => {
  assert.match(calmSearchNote(route({ limited: "split" })) ?? "", /could not cut this long trip into legs/);
  assert.match(calmSearchNote(route({ limited: "time" })) ?? "", /ran out of time/);
});
