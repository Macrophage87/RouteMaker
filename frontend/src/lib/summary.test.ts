import { test } from "node:test";
import assert from "node:assert/strict";
import { announceRoute, detourNotice, paceText } from "./summary.ts";
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";

const GEORGETOWN: LonLat = [-77.0629, 38.905];
const ROSSLYN: LonLat = [-77.0707, 38.8966];

test("the pace is the answer's own distance over time", () => {
  assert.match(paceText({ distance_m: 5000, duration_s: 1200, preset: "default" }) ?? "", /about 15 km\/h \(9 mph\)/);
  assert.match(paceText({ distance_m: 4000, duration_s: 1560, preset: "mass-ride" }) ?? "", /^parade pace, about 9 km\/h/);
  assert.equal(paceText({ distance_m: 0, duration_s: 0, preset: "default" }), null);
});

test("a detour notice gives distances, not a ratio", () => {
  const text = detourNotice({ distance_m: 141_100, preset: "mass-ride" }, [GEORGETOWN, ROSSLYN]) ?? "";
  assert.match(text, /141 km/);
  assert.match(text, /1\.\d km apart/);
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
  assert.match(said, /5\.0 km/);
  assert.match(said, /20 min moving time/);
  assert.match(said, /31 m/);
});
