import { test } from "node:test";
import assert from "node:assert/strict";
import { announceRoute, detourNotice, paceText } from "./summary.ts";
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
