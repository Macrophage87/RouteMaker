import { test } from "node:test";
import assert from "node:assert/strict";
import { announceRoute, calmSearchNote, detourNotice, detourView, paceText } from "./summary.ts";
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";

const GEORGETOWN: LonLat = [-77.0629, 38.905];
const ROSSLYN: LonLat = [-77.0707, 38.8966];

/** The numbers in a sentence, in order: what these tests hold, not the wording. */
const numbers = (text: string | null) => (text ?? "").match(/\d+(?:\.\d+)?/g) ?? [];

test("the pace is the answer's own distance over time, in mph and then km/h", () => {
  // 5 km in 20 min is 9.3 mph, 15 km/h.
  assert.equal(paceText({ distance_m: 5000, duration_s: 1200, preset: "default" }), "about 9 mph (15 km/h)");
  // 4 km in 26 min is 5.7 mph, 9.2 km/h.
  assert.deepEqual(numbers(paceText({ distance_m: 4000, duration_s: 1560, preset: "default" })), ["6", "9"]);
});

test("Mass Ride's pace says what it is on top of the same figures", () => {
  const plain = paceText({ distance_m: 4000, duration_s: 1560, preset: "default" }) ?? "";
  const mass = paceText({ distance_m: 4000, duration_s: 1560, preset: "mass-ride" }) ?? "";
  assert.notEqual(mass, plain);
  assert.ok(mass.endsWith(plain), mass);
});

test("no pace without both a distance and a time", () => {
  for (const [distance_m, duration_s] of [[0, 0], [5000, 0], [0, 1200], [-5, 1200], [5000, -1], [Number.NaN, 1200]]) {
    assert.equal(paceText({ distance_m, duration_s, preset: "default" }), null, `${distance_m} m in ${duration_s} s`);
  }
});

test("a detour notice gives distances, not a ratio", () => {
  const text = detourNotice({ distance_m: 141_100, preset: "mass-ride" }, [GEORGETOWN, ROSSLYN]) ?? "";
  const [routeMi, routeKm, straight] = numbers(text);
  assert.deepEqual([routeMi, routeKm], ["87.7", "141.1"]);
  assert.match(text, /^This route is 87\.7 mi \(141\.1 km\) for points /);
  assert.match(straight, /^0\.\d$/);
  assert.doesNotMatch(text, /×|\dx\b/);
});

test("the Mass Ride cause is the preset's rule, not a finding about a crossing", () => {
  const mass = detourNotice({ distance_m: 141_100, preset: "mass-ride" }, [GEORGETOWN, ROSSLYN]) ?? "";
  assert.match(mass, /roadways/);
  assert.match(mass, /sidepath/);
  assert.doesNotMatch(mass, /no roadway crossing is nearby/);
  const other = detourNotice({ distance_m: 141_100, preset: "default" }, [GEORGETOWN, ROSSLYN]) ?? "";
  assert.doesNotMatch(other, /Mass Ride/);
});

test("no notice when the route is not a detour", () => {
  assert.equal(detourNotice({ distance_m: 1500, preset: "mass-ride" }, [GEORGETOWN, ROSSLYN]), null);
});

test("the announcement carries distance, moving time and climb", () => {
  const route = { distance_m: 5000, duration_s: 1200, climb_m: 31 } as RouteResponse;
  const said = announceRoute(route);
  const figures = numbers(said);
  for (const figure of ["5.0", "20", "31"]) assert.ok(figures.includes(figure), `${figure} missing from ${said}`);
});

// The direct-route notice (OWNER-DECISIONS 164: "just warn people"). The API decides
// the level (src/routemaker/detour.py); these hold what the words say.
const MI = 1609.344;
const direct = (
  extraMi: number,
  directMi: number,
  level: "note" | "warning" | "strong" | null,
  avoidedMi?: number,
  stress = 100,
) => ({
  distance_m: (directMi + extraMi) * MI,
  preset: "default" as const,
  dials: { stress, hills: 0, when: "weekend" as const, carrying: null, assist: false, avoid_gravel: false },
  detour: {
    basis: "direct_route" as const,
    reference_m: directMi * MI,
    ratio: Math.round(((directMi + extraMi) / directMi) * 100) / 100,
    extra_m: extraMi * MI,
    level,
    avoided_m: avoidedMi === undefined ? null : avoidedMi * MI,
  },
});

test("a strong warning reads like the owner's example, miles first", () => {
  const view = detourView(direct(18, 11.25, "strong"), [GEORGETOWN, ROSSLYN]);
  assert.equal(view?.level, "strong");
  assert.match(view?.text ?? "", /^This calm route is 2\.6× the direct distance, \+18\.0 mi \(29\.0 km\)\./);
  assert.match(view?.text ?? "", /more than twice as far/);
});

test("a warning is a level of its own, and a note says what the extra distance buys", () => {
  const warning = detourView(direct(6, 10, "warning"), [GEORGETOWN, ROSSLYN]);
  assert.equal(warning?.level, "warning");
  assert.match(warning?.text ?? "", /^This calm route is 1\.6× the direct distance, \+6\.0 mi \(9\.7 km\)\./);
  assert.match(warning?.text ?? "", /That is more than 1\.5 times the direct route\./);
  const note = detourView(direct(1.2, 4, "note", 0.8), [GEORGETOWN, ROSSLYN]);
  assert.equal(note?.level, "note");
  assert.equal(
    note?.text,
    "This calm route is 1.3× the direct distance, +1.2 mi (1.9 km), to avoid 0.8 mi (1.3 km) of busy roads (LTS 3-4).",
  );
});

test("a ratio that rounds to the threshold it is beyond keeps a second decimal", () => {
  // Review r2: "1.5× ... more than 1.5 times" when the ratio was 1.52.
  const warning = detourView(direct(5.2, 10, "warning"), [GEORGETOWN, ROSSLYN]);
  assert.match(warning?.text ?? "", /^This calm route is 1\.52× the direct distance/);
  assert.match(warning?.text ?? "", /more than 1\.5 times/);
  const strong = detourView(direct(10.4, 10, "strong"), [GEORGETOWN, ROSSLYN]);
  assert.match(strong?.text ?? "", /^This calm route is 2\.04× the direct distance/);
  // Elsewhere, one decimal.
  assert.match(detourView(direct(4.4, 10, "note"), [GEORGETOWN, ROSSLYN])?.text ?? "", /is 1\.4×/);
  assert.match(detourView(direct(5.2, 10, "note"), [GEORGETOWN, ROSSLYN])?.text ?? "", /is 1\.5×/);
});

test("a calmer-route search that stopped short says so in plain words", () => {
  const route = (limited: string | null, stress = 100, preset: "default" | "mass-ride" = "default") => ({
    ...direct(1, 10, null, undefined, stress),
    preset,
    calm_search: { rate: 10, rounds: 1, excluded: 2, limited },
  });
  assert.match(calmSearchNote(route("time")) ?? "", /^The calmer-route search ran out of time/);
  assert.match(calmSearchNote(route("untraceable")) ?? "", /could not read this route/);
  assert.match(calmSearchNote(route("span")) ?? "", /over 19 mi \(30 km\) in a straight line/);
  assert.match(calmSearchNote(route("long_ride")) ?? "", /long rides/);
  assert.match(calmSearchNote(route("seeking")) ?? "", /Hills slider/);
  // Nothing to say: it ran to its end, or ended where the router had no more.
  for (const limited of [null, "no_route", "excludes", "rounds", "points", "mass_ride"]) {
    assert.equal(calmSearchNote(route(limited)), null, String(limited));
  }
  // Not asked for: at the old top or below, or a Mass Ride; or an older API.
  assert.equal(calmSearchNote(route("time", 80)), null);
  assert.equal(calmSearchNote(route("time", 100, "mass-ride")), null);
  assert.equal(calmSearchNote({ preset: "default", dials: direct(1, 10, null).dials }), null);
});

test("at Default or below the route is not called calm", () => {
  // Review r1: the detour probe also runs at Default for a route twice the
  // straight line, and that route was not asked to be calm.
  const view = detourView(direct(6, 5, "strong", undefined, 70), [GEORGETOWN, ROSSLYN]);
  assert.match(view?.text ?? "", /^This route is 2\.2× the direct distance/);
  const top = detourView(direct(6, 5, "strong", undefined, 80), [GEORGETOWN, ROSSLYN]);
  assert.match(top?.text ?? "", /^This route is/);
  const calm = detourView(direct(6, 5, "strong", undefined, 81), [GEORGETOWN, ROSSLYN]);
  assert.match(calm?.text ?? "", /^This calm route is/);
});

test("no notice within the allowance, and none where the API says there is nothing to say", () => {
  assert.equal(detourView(direct(1, 10, null), [GEORGETOWN, ROSSLYN]), null);
  assert.equal(detourView({ distance_m: 141_100, preset: "default", detour: null }, [GEORGETOWN, ROSSLYN]), null);
});

test("without the direct route the old straight-line notice is what is said", () => {
  const fallback = {
    distance_m: 141_100,
    preset: "default" as const,
    detour: { basis: "straight_line" as const, reference_m: 1000, ratio: 141, extra_m: 140_100, level: "warning" as const },
  };
  assert.match(detourNotice(fallback, [GEORGETOWN, ROSSLYN]) ?? "", /^This route is 87\.7 mi \(141\.1 km\) for points /);
  // An API older than the field has none, and gets the same.
  assert.equal(detourNotice({ distance_m: 141_100, preset: "default" }, [GEORGETOWN, ROSSLYN]), detourNotice(fallback, [GEORGETOWN, ROSSLYN]));
  assert.equal(detourView(fallback, [GEORGETOWN, ROSSLYN])?.level, "warning");
});

test("Mass Ride keeps its own words even if a direct-route block were sent", () => {
  const mass = { ...direct(60, 20, "strong"), preset: "mass-ride" as const };
  const text = detourNotice({ ...mass, distance_m: 141_100 }, [GEORGETOWN, ROSSLYN]) ?? "";
  assert.match(text, /roadways/);
});

// The announcement carries the detour's tier and the very high stress junctions
// (a11y review of integrate-2, 4.1.3; OWNER-DECISIONS 220).
const announced = (extra: Partial<RouteResponse>, points: LonLat[] = [GEORGETOWN, ROSSLYN]) =>
  announceRoute({ distance_m: 5000, duration_s: 1200, climb_m: 31, preset: "default", ...extra } as RouteResponse, points);
const junction = (severity: "orange" | "red") => ({
  m: 100, lon: -77, lat: 38.9, severity, reason: "r", crossed_tier: 4, movement: "straight", control: "none", kind: "crossing", cost_ft: 100,
}) as NonNullable<RouteResponse["intersections"]>[number];

test("the announcement says the detour's tier and how much longer, in words a screen reader reads well", () => {
  const strong = announced(direct(18, 11.25, "strong") as Partial<RouteResponse>);
  assert.match(strong, /^Route planned: /);
  assert.match(strong, / Strong warning: 2\.6 times the direct distance, 18\.0 mi \(29\.0 km\) longer\.$/);
  assert.doesNotMatch(strong, /×/, "not 'multiplication sign'");
  const warning = announced(direct(6, 10, "warning") as Partial<RouteResponse>);
  assert.match(warning, / Warning: 1\.6 times the direct distance, 6\.0 mi \(9\.7 km\) longer\.$/);
  const note = announced(direct(1.2, 4, "note", 0.8) as Partial<RouteResponse>);
  assert.match(note, / Note: 1\.3 times the direct distance, 1\.2 mi \(1\.9 km\) longer\.$/);
  // At the threshold the ratio keeps its second decimal, as the notice does.
  assert.match(announced(direct(10, 10, "strong") as Partial<RouteResponse>), /Strong warning: 2\.00 times/);
});

test("the straight-line notice is announced too, by its first sentence", () => {
  const said = announced({ distance_m: 141_100 });
  assert.match(said, / Warning: this route is 87\.7 mi \(141\.1 km\) for points [\d.]+ mi \([\d.]+ km\) apart in straight lines\.$/);
  const mass = announced({ distance_m: 141_100, preset: "mass-ride" });
  assert.match(mass, /Warning: this route is /);
  assert.doesNotMatch(mass, /Mass Ride keeps to roadways/, "the advice stays in the summary");
});

test("the announcement counts the very high stress junctions, and only those", () => {
  assert.match(announced({ intersections: [junction("red"), junction("orange"), junction("red")] }), / 2 very high stress junctions\.$/);
  assert.match(announced({ intersections: [junction("red")] }), / 1 very high stress junction\.$/);
  assert.doesNotMatch(announced({ intersections: [junction("orange")] }), /junction/);
  assert.doesNotMatch(announced({ intersections: null }), /junction/);
  assert.doesNotMatch(announced({}), /junction/);
});

test("a plain route is still one sentence, and the warnings come in order: figures, detour, junctions", () => {
  const plain = announced({ distance_m: 5000, detour: null });
  assert.equal(plain.split(". ").length, 1, plain);
  const both = announced({ ...(direct(6, 10, "warning") as Partial<RouteResponse>), intersections: [junction("red")] });
  assert.ok(both.indexOf("Warning:") > both.indexOf("climb"));
  assert.ok(both.indexOf("very high stress") > both.indexOf("Warning:"));
  // Concise: nothing else of the notice (its advice) is said.
  assert.doesNotMatch(both, /Move the Traffic slider/);
});
