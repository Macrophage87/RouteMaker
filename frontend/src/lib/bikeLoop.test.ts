/** A bike loop from a start and a distance (lib/bikeLoop.ts; backlog 2026-11-12 item 5). */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  LOOP_DEFAULT_M,
  LOOP_MAX_M,
  LOOP_MIN_M,
  headingWord,
  isShapeOf,
  keepLoopM,
  keptLoopM,
  loopShapesBody,
  offersBikeLoop,
  requestLoopShapes,
  shapeLine,
  shapeName,
  shapePoints,
  showsBikeLoop,
  type LoopShape,
} from "./bikeLoop.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";

const START: LonLat = [-77.0365, 38.8977];

function shape(over: Partial<LoopShape> = {}): LoopShape {
  return {
    points: [START, [-77.0, 38.95], [-76.95, 38.9], START],
    via_points: [1, 2],
    heading_deg: 40,
    distance_m: 32_900,
    climb_m: 350,
    quiet_pct: 78,
    busy_m: 1200,
    near_target: true,
    spur_pct: 2,
    geometry: { type: "LineString", coordinates: [START, [-77.0, 38.95]] },
    ...over,
  };
}

test("the bike ride types that loop offer it; Run, Mass Ride and the two-point types do not", () => {
  for (const id of ["default", "trailmaxxing", "gravel", "road-bike", "mountain-bike", "cargo", "novice"] as const) {
    assert.equal(offersBikeLoop(id), true, id);
  }
  for (const id of ["run", "mass-ride", "bikeshare", "rebalance", "bike-transit", "walk"] as const) {
    assert.equal(offersBikeLoop(id), false, id);
  }
});

test("the box shows with the loop on and the start alone", () => {
  assert.equal(showsBikeLoop("default", [START], true), true);
  assert.equal(showsBikeLoop("default", [START], false), false);
  assert.equal(showsBikeLoop("default", [], true), false);
  assert.equal(showsBikeLoop("default", [START, [-77, 38.9]], true), false);
  assert.equal(showsBikeLoop("run", [START], true), false);
});

test("the range is the API's: 3 mi to 100 mi, 20 mi to start with (our default)", () => {
  const api = readFileSync(new URL("../../../src/core/bike_loop.py", import.meta.url), "utf8");
  assert.match(api, /TARGET_MIN_M = round\(3 \* METRES_PER_MILE\)/);
  assert.match(api, /TARGET_MAX_M = round\(100 \* METRES_PER_MILE\)/);
  assert.equal(LOOP_MIN_M, Math.round(3 * 1609.344));
  assert.equal(LOOP_MAX_M, Math.round(100 * 1609.344));
  assert.equal(LOOP_DEFAULT_M, Math.round(20 * 1609.344));
});

test("a shape is named by the way it heads and says about its miles, climb and quiet", () => {
  assert.equal(headingWord(0), "north");
  assert.equal(headingWord(44), "northeast");
  assert.equal(headingWord(181), "south");
  assert.equal(headingWord(350), "north");
  assert.equal(shapeName(shape()), "Heads northeast");
  const line = shapeLine(shape());
  assert.match(line, /^About 20\.4 mi/);
  assert.match(line, /1,148 ft \(350 m\) climb/);
  assert.match(line, /78% quiet/);
  assert.doesNotMatch(shapeLine(shape({ quiet_pct: null })), /quiet/);
  assert.match(shapeLine(shape({ near_target: false })), /nearest to your distance/);
});

test("a picked shape is the start, its corners as via points, and the start again", () => {
  const vias: LonLat[] = [];
  const points = shapePoints(START, shape(), (p) => {
    vias.push(p);
    return p;
  });
  assert.equal(points.length, 4);
  assert.equal(points[0], START);
  assert.deepEqual(points[3], START);
  assert.notEqual(points[3], START, "a pair of its own, so the end is not the start's pair");
  assert.deepEqual(vias, [
    [-77.0, 38.95],
    [-76.95, 38.9],
  ]);
  assert.equal(isShapeOf(points, START, shape()), true);
  assert.equal(isShapeOf([START, [-77.0, 38.95], [-76.9, 38.9], START], START, shape()), false);
  assert.equal(isShapeOf([START], START, shape()), false);
});

test("the request carries the start, the distance, the ride type and the dials", () => {
  const dials = { ...startDials("gravel"), trailsOff: true, when: "weekend" as const };
  const body = JSON.parse(loopShapesBody(START, "gravel", dials, 32_186.9));
  assert.deepEqual(body.start, START);
  assert.equal(body.target_distance_m, 32_187);
  assert.equal(body.preset, "gravel");
  assert.equal(body.stress, dials.stress);
  assert.equal(body.trails_off, true);
  assert.equal(body.when, "weekend");
  assert.equal("loop" in body, false);
});

test("the answer's shapes, or the error as a route's", async () => {
  const ok = await requestLoopShapes(START, "default", startDials("default"), 32_000, {
    fetchImpl: async () => new Response(JSON.stringify({ shapes: [shape(), { bad: true }] }), { status: 200 }),
  });
  assert.equal(ok.ok, true);
  if (ok.ok) assert.equal(ok.shapes.length, 1);
  const refused = await requestLoopShapes(START, "default", startDials("default"), 32_000, {
    fetchImpl: async () => new Response(JSON.stringify({ error: "No loop could be found from this start.", code: "no_loop" }), { status: 422 }),
  });
  assert.equal(refused.ok, false);
  const offline = await requestLoopShapes(START, "default", startDials("default"), 32_000, {
    fetchImpl: async () => {
      throw new Error("offline");
    },
  });
  assert.equal(offline.ok, false);
});

test("the distance is kept on this device, and storage that throws gives our default", () => {
  const kept = new Map<string, string>();
  const storage = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(keptLoopM(storage), LOOP_DEFAULT_M);
  keepLoopM(48_280, storage);
  assert.equal(keptLoopM(storage), 48_280);
  const broken = {
    getItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(keptLoopM(broken), LOOP_DEFAULT_M);
  kept.set("routemaker.bikeLoopM", "999999999");
  assert.equal(keptLoopM(storage), LOOP_DEFAULT_M);
});
