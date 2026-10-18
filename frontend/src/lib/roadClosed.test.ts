// Closures on the move (lib/roadClosed.ts; the owner, 2026-10-17).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { haversineM } from "./geo.ts";
import { rideModel } from "./navigate.ts";
import { CLOSED_FROM_M, CLOSED_LENGTH_M, CLOSED_MOST, closedAhead, onOtherLine, withClosed } from "./roadClosed.ts";
import { routeRequestBody } from "./api.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}
function route(coordinates: LonLat[]): RouteResponse {
  const entry: DescriptionEntry = { kind: "stretch", from_m: 0, to_m: 2000, from_mi: 0, to_mi: 2000 / 1609.344, street: "A Street", tier: 1, facility: null, turn: null, text: "A Street" };
  return { geometry: { type: "LineString", coordinates }, distance_m: 2000, duration_s: 400, description: [entry] } as unknown as RouteResponse;
}
/** East 1,000 m, then north 1,000 m. */
const MAIN = rideModel(route([at(0, 0), at(500, 0), at(1000, 0), at(1000, 500), at(1000, 1000)]));

test("on the route, the road ahead from just ahead of the rider, through the next turn", () => {
  const found = closedAhead(MAIN, 900, false, at(900, 0), 90);
  assert.ok(found);
  assert.equal(found.untilM, 900 + CLOSED_FROM_M + CLOSED_LENGTH_M);
  assert.equal(found.line.length, 3, "its ends and the corner");
  // It starts 10 m ahead, keeps the corner, and ends on the next street.
  assert.ok(haversineM(found.line[0], at(930, 0)) < 1);
  assert.ok(found.line.some((p) => haversineM(p, at(1000, 0)) < 1));
  assert.ok(haversineM(found.line[2], at(1000, 80)) < 1);
});

test("off the route, straight ahead along the heading; with neither, nothing", () => {
  const north = closedAhead(MAIN, 300, true, at(300, 100), 0);
  assert.ok(north && north.untilM === null);
  assert.ok(north.line[1][1] > north.line[0][1] && Math.abs(north.line[1][0] - north.line[0][0]) < 1e-9);
  assert.equal(closedAhead(MAIN, 300, true, at(300, 100), null), null);
  assert.equal(closedAhead(MAIN, null, false, null, null), null);
  // At the very end there is no road ahead.
  assert.equal(closedAhead(MAIN, MAIN.lengthM - 5, false, at(1000, 995), 0), null);
});

test("a ride keeps its latest stretches, as many as the API takes", () => {
  let lines: LonLat[][] = [];
  for (let i = 0; i < CLOSED_MOST + 3; i += 1) lines = withClosed(lines, [at(i, 0), at(i, 10)]);
  assert.equal(lines.length, CLOSED_MOST);
  assert.deepEqual(lines[lines.length - 1][0], at(CLOSED_MOST + 2, 0));
});

test("on the other line: followed there; off both: not", () => {
  // The standard way: straight east past the corner.
  const standard = rideModel(route([at(0, 0), at(2000, 0)]));
  assert.ok(Math.abs((onOtherLine(standard, at(1400, 5), 5) ?? 0) - 1400) < 1);
  assert.equal(onOtherLine(standard, at(1400, 300), 5), null);
  assert.equal(onOtherLine(null, at(1400, 5), 5), null);
});

test("the ride's closed roads go in its re-plans' requests", () => {
  const body = JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "default", { blocked: [[at(1, 1), at(2, 2)]] }));
  assert.deepEqual(body.blocked_lines, [[at(1, 1), at(2, 2)]]);
  assert.equal(JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "default")).blocked_lines, undefined);
});

test("a re-plan sends the rider's heading, kept in 0-360, and nothing without one", () => {
  const sent = (heading: number | null) => JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "default", { heading })).heading;
  assert.equal(sent(90), 90);
  assert.equal(sent(-90), 270);
  assert.equal(sent(null), undefined);
  assert.equal(sent(Number.NaN), undefined);
});

test("a curvy stretch is sent as a few points, never one per vertex", () => {
  const wiggle: LonLat[] = [];
  for (let i = 0; i <= 200; i += 1) wiggle.push(at(i * 5, i % 2 ? 2 : 0));
  const found = closedAhead(rideModel(route(wiggle)), 100, false, at(500, 0), 90);
  assert.ok(found && found.line.length <= 3);
});

test("on a line that passes the same place twice, the pass near the rider's progress", () => {
  // Out 1,000 m east and back the same way.
  const outAndBack = rideModel(route([at(0, 0), at(1000, 0), at(0, 0)]));
  assert.ok(Math.abs((onOtherLine(outAndBack, at(400, 3), 5, 400) ?? 0) - 400) < 1);
  assert.ok(Math.abs((onOtherLine(outAndBack, at(400, 3), 5, 1600) ?? 0) - 1600) < 1);
});
