// A station's quickest way in with a bike (Stephen 2026-10-20, Shady Grove from the west).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { NearestResult } from "./nearest.ts";
import type { Station } from "./railStations.ts";
import { QUICKER_BY_S, lonLatKey, quickerWayIn, wayInChecks, wayInPlaces, wayInSaid } from "./stationWayIn.ts";

const EAST: LonLat = [-77.165, 39.12];
const WEST: LonLat = [-77.1665, 39.12];
const station: Station = {
  id: "metro-sg",
  name: "Shady Grove",
  point: [-77.1657, 39.12],
  metro: ["red"],
  penn: false,
  elevators: [EAST, WEST],
  osmElevators: [],
  entrances: [[-77.1651, 39.1201]],
};
const oneElevator: Station = { ...station, id: "metro-one", point: [-77.0, 38.9], elevators: [[-77.0, 38.9001]], entrances: [[-77.0, 38.9002]] };
const start: LonLat = [-77.17, 39.13];

const riding = (...times: Array<number | null>): NearestResult => ({
  ok: true,
  answer: { by: "riding", places: times.map((t) => ({ time_s: t, distance_m: t === null ? null : t * 5 })) },
});

test("a point at one of a station's bike ways in is checked from the point before it, a start from the point after", () => {
  const end = wayInChecks([start, EAST], [station]);
  assert.equal(end.length, 1);
  assert.equal(end[0].index, 1);
  assert.deepEqual(end[0].from, start);
  assert.equal(end[0].kind, "elevator");
  assert.deepEqual(end[0].ways, [EAST, WEST]);
  const first = wayInChecks([WEST, start], [station]);
  assert.deepEqual(first[0].from, start);
});

test("nothing to check: one point, a station with one way in for a bike, a point off the ways in, stairs with a bike", () => {
  assert.deepEqual(wayInChecks([EAST], [station]), []);
  assert.deepEqual(wayInChecks([start, [-77.0, 38.9001]], [oneElevator]), []);
  assert.deepEqual(wayInChecks([start, [-77.1657, 39.12]], [station]), []);
  // The entrance (stairs) is not a bike way in while the station has elevators.
  assert.deepEqual(wayInChecks([start, [-77.1651, 39.1201]], [station]), []);
});

test("the quickest by bike wins when it saves enough, and an unreachable way in gives way", () => {
  const [check] = wayInChecks([start, EAST], [station]);
  assert.deepEqual(quickerWayIn(EAST, check, riding(600, 120)), WEST);
  assert.equal(quickerWayIn(EAST, check, riding(130, 120)), null, `under ${QUICKER_BY_S} s is no move`);
  assert.equal(quickerWayIn(EAST, check, riding(120, 600)), null, "its own is the quickest");
  assert.deepEqual(quickerWayIn(EAST, check, riding(null, 300)), WEST);
  assert.equal(quickerWayIn(EAST, check, riding(null, null)), null);
});

test("no move without riding times: a straight-line answer or a failed request", () => {
  const [check] = wayInChecks([start, EAST], [station]);
  assert.equal(quickerWayIn(EAST, check, { ok: true, answer: { by: "straight_line", places: [{ distance_m: 900, time_s: null }, { distance_m: 10, time_s: null }] } }), null);
  assert.equal(quickerWayIn(EAST, check, { ok: false, message: "down" }), null);
});

test("the request's places and the words said", () => {
  const [check] = wayInChecks([start, EAST], [station]);
  assert.deepEqual(wayInPlaces(check).map((p) => p.point), [EAST, WEST]);
  assert.equal(wayInSaid("End", "Shady Grove Metro station", "elevator"), "End moved to Shady Grove Metro station's elevator that is quicker to reach by bike. Undo puts it back.");
  assert.equal(lonLatKey([-77.123456, 39.000004]), "-77.12346,39.00000");
});
