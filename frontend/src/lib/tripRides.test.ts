import assert from "node:assert/strict";
import { test } from "node:test";
import type { RouteProfile, RouteResponse, TransitStep } from "./api.ts";
import { tripPointAt, tripRoute } from "./tripRides.ts";

const profile = (m: number[], e: number[]): RouteProfile => ({ interval_m: 30, m, elevation_m: e, grade_pct: e.map(() => 0), climbs: [{ from_m: m[0], to_m: m[m.length - 1], gain_m: 5, avg_grade_pct: 1, max_grade_pct: 2, tier: 2 }] });
const step = (mode: string, extra: Partial<TransitStep> = {}): TransitStep => ({ mode, text: "", seconds: 60, wait_s: 0, to: null, lines: [], with_bike: true, route_line: false, coordinates: [], ...extra }) as TransitStep;

const route = {
  distance_m: 1000,
  climb_m: 10,
  descent_m: 4,
  profile: profile([0, 500, 1000], [10, 15, 20]),
  stress_spans: [{ from_m: 0, to_m: 1000, tier: 2, facility: "lane" }],
  geometry: { type: "LineString", coordinates: [[-77.0, 38.9], [-77.01, 38.9]] },
  transit: {
    steps: [
      step("ride", { route_line: true }),
      step("metro", { coordinates: [[-77.01, 38.9], [-77.05, 38.92]] }),
      step("ride", {
        coordinates: [[-77.05, 38.92], [-77.06, 38.93]],
        distance_m: 2000,
        climb_m: 30,
        descent_m: 1,
        profile: profile([0, 2000], [40, 70]),
        stress_spans: [{ from_m: 0, to_m: 2000, tier: 3, facility: "none" }],
      }),
    ],
  },
} as unknown as RouteResponse;

test("a transit trip's totals and chart are every ride's, end to end (Stephen, 2026-10-21)", () => {
  const trip = tripRoute(route);
  assert.equal(trip.distance_m, 3000);
  assert.equal(trip.climb_m, 40);
  assert.equal(trip.descent_m, 5);
  // The second ride's samples follow the first's, a null height between them where the train runs.
  assert.deepEqual(trip.profile?.m, [0, 500, 1000, 1000, 1000, 3000]);
  assert.deepEqual(trip.profile?.elevation_m, [10, 15, 20, null, 40, 70]);
  assert.deepEqual(trip.profile?.climbs.map((c) => [c.from_m, c.to_m]), [[0, 1000], [1000, 3000]]);
  assert.deepEqual(trip.stress_spans?.map((s) => [s.from_m, s.to_m, s.tier]), [[0, 1000, 2], [1000, 3000, 3]]);
  // The chart's scrub lands on the ride it falls in.
  assert.deepEqual(tripPointAt(trip, 3000, 3000), [-77.06, 38.93]);
  assert.deepEqual(tripPointAt(trip, 0, 3000), [-77.0, 38.9]);
});

test("a later ride not routed in time, or a plain route, leaves the route as it is", () => {
  const unrouted = { ...route, transit: { steps: [step("ride", { route_line: true }), step("ride", { coordinates: [[-77.05, 38.92], [-77.06, 38.93]] })] } } as unknown as RouteResponse;
  assert.equal(tripRoute(unrouted), unrouted);
  const plain = { ...route, transit: null } as unknown as RouteResponse;
  assert.equal(tripRoute(plain), plain);
});
