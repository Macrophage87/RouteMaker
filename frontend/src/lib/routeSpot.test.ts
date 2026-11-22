// What a tap on Go's map says about the route on it (Stephen, 2026-11-22).
import { test } from "node:test";
import assert from "node:assert/strict";
import { ON_ROUTE_M, routeSpotAt, routeSpotLines, routeSpotToleranceM, spotSectionText } from "./routeSpot.ts";
import type { LonLat } from "./geo.ts";

// A straight line east along a parallel, about 2 km, in two pieces.
const line: LonLat[] = [
  [-77.03, 38.9],
  [-77.02, 38.9],
  [-77.007, 38.9],
];
const route = {
  geometry: { type: "LineString" as const, coordinates: line },
  distance_m: 2000,
  duration_s: 600,
  stress_spans: [
    { from_m: 0, to_m: 1000, tier: 2, facility: "lane" as const },
    { from_m: 1000, to_m: 2000, tier: 3, facility: "none" as const, half: true },
  ],
  description: [
    { kind: "stretch" as const, from_m: 0, to_m: 1000, street: "R Street Northwest" },
    { kind: "stretch" as const, from_m: 1000, to_m: 2000, street: "Florida Avenue Northwest" },
  ] as never,
};

test("a tap on the line is on the route, with how far along, the street and its stress there", () => {
  const spot = routeSpotAt(route, [-77.0185, 38.9001])!;
  assert.ok(spot.on);
  assert.ok(spot.offM < 20, `${spot.offM}`);
  assert.ok(Math.abs(spot.atM - 1000) < 30, `${spot.atM}`);
  assert.ok(Math.abs((spot.seconds ?? 0) - 300) < 10, `${spot.seconds}`);
  assert.equal(spot.street, "Florida Avenue Northwest");
  assert.equal(spot.span?.tier, 3);
  const early = routeSpotAt(route, [-77.028, 38.9])!;
  assert.equal(early.street, "R Street Northwest");
  assert.deepEqual(routeSpotLines(early).slice(2), ["R Street Northwest · LTS 2 · Painted bike lane"]);
  assert.match(routeSpotLines(early)[0], /^0\.1 mi \(0\.\d km\) from the start, about 1 min$/);
  assert.match(routeSpotLines(early)[1], /^1\.1 mi .* to the end$/);
});

test("a tap away from the line says only how far off the route it is", () => {
  const spot = routeSpotAt(route, [-77.02, 38.905])!;
  assert.equal(spot.on, false);
  assert.deepEqual(routeSpotLines(spot), ["0.3 mi (0.6 km) from your route"]);
});

test("the time comes from the route's time marks where it has them", () => {
  const spot = routeSpotAt({ ...route, time_marks: [[0, 0], [0.5, 100], [1, 600]] }, [-77.0185, 38.9])!;
  assert.ok(Math.abs((spot.seconds ?? 0) - 100) < 10, `${spot.seconds}`);
});

test("the tolerance is a fingertip on screen, never under ON_ROUTE_M", () => {
  assert.equal(routeSpotToleranceM(18, 38.9), ON_ROUTE_M);
  assert.ok(routeSpotToleranceM(12, 38.9) > 300);
  assert.equal(routeSpotAt(route, [-77.02, 38.905], routeSpotToleranceM(11, 38.9))?.on, true);
});

test("no line, no spot; a half step, Avoid and unpaved are said as the map draws them", () => {
  assert.equal(routeSpotAt(null, [-77, 38.9]), null);
  assert.equal(spotSectionText({ from_m: 0, to_m: 1, tier: 3, facility: "none", half: true }), "LTS 3.5");
  assert.equal(spotSectionText({ from_m: 0, to_m: 1, tier: 5, facility: "path" }), "Avoid · Trail");
  assert.equal(spotSectionText({ from_m: 0, to_m: 1, tier: 1, facility: "path", unpaved: true, rough: false }), "LTS 1 · Trail · Gravel");
  assert.equal(spotSectionText({ from_m: 0, to_m: 1, tier: null, facility: null }), null);
});
