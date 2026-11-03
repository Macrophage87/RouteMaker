// Stops on Walk and the transit types (Stephen, 2026-11-03: "Each stop starts a new trip"): the API joins each leg's
// trip (`stop_steps`), and the ride follows one trip at a time, with "Start the next leg" at each stop.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse, TransitPlan, TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { NEXT_LEG, firstTripOf, hasStops, nextLegPoints, stopsAsTrips, stopsLeftOf } from "./tripStops.ts";

const step = (mode: TransitStep["mode"], seconds: number, waitS = 0, to: string | null = null): TransitStep =>
  ({ mode, text: `${mode} to ${to}`, seconds, wait_s: waitS, to, lines: [], with_bike: false, route_line: false, coordinates: [] }) as unknown as TransitStep;

const plan = (steps: TransitStep[], stopSteps: number[], key = "a>b+c>d"): TransitPlan =>
  ({
    mode: "walk-transit",
    key,
    stop_steps: stopSteps,
    direct: false,
    options: [{ key, label: "Walk, Metro, walk, then walk", total_s: 9999, minutes: 167, direct: false, chosen: true }],
    total_s: 9999,
    minutes: 167,
    steps,
    departure: { step: 1 },
  }) as unknown as TransitPlan;

const route = (transit: TransitPlan | null): RouteResponse => ({ geometry: { coordinates: [[0, 0], [1, 1]] }, transit }) as unknown as RouteResponse;

const A: LonLat = [-77.0, 38.9];
const STOP: LonLat = [-77.01, 38.9];
const STOP2: LonLat = [-77.02, 38.9];
const END: LonLat = [-77.03, 38.9];

test("Walk and the transit types take stops as trips of their own; Bikeshare and the riding types do not here", () => {
  for (const preset of ["walk", "walk-transit", "bike-transit", "bikeshare-transit"] as const) assert.equal(stopsAsTrips(preset), true);
  for (const preset of ["bikeshare", "rebalance", "default"] as const) assert.equal(stopsAsTrips(preset), false);
});

test("the first trip is its steps to the first stop, its own key and its own time", () => {
  const steps = [step("walk", 300, 0), step("metro", 600, 120), step("walk", 200, 0, "stop 1"), step("walk", 400)];
  const joined = route(plan(steps, [3]));
  assert.equal(hasStops(joined), true);
  const first = firstTripOf(joined);
  assert.equal(first.transit?.steps.length, 3);
  assert.equal(first.transit?.key, "a>b");
  assert.equal(first.transit?.total_s, 300 + 600 + 120 + 200);
  assert.deepEqual(first.transit?.stop_steps, []);
  assert.equal(first.transit?.options.length, 1);
  assert.equal(first.transit?.options[0].key, "a>b");
  assert.equal(hasStops(first), false);
  // A departure in a later trip is not this one's.
  assert.equal(firstTripOf(route(plan(steps, [1]))).transit?.departure, null);
  // No stops: itself.
  const plain = route(plan(steps, []));
  assert.equal(firstTripOf(plain), plain);
});

test("the stops left are the first stop on to the end; the next leg leaves from where the rider is", () => {
  const joined = route(plan([step("walk", 300), step("walk", 300)], [1]));
  const left = stopsLeftOf(joined, [A, STOP, STOP2, END], "walk");
  assert.deepEqual(left, { preset: "walk", points: [STOP, STOP2, END] });
  assert.deepEqual(nextLegPoints(left!, [-77.011, 38.9]), [[-77.011, 38.9], STOP2, END]);
  // No fix: from the stop itself.
  assert.deepEqual(nextLegPoints(left!, null), [STOP, STOP2, END]);
  // A trip with no stops, or a ride type that does not take them: none.
  assert.equal(stopsLeftOf(route(plan([step("walk", 300)], [])), [A, END], "walk"), null);
  assert.equal(stopsLeftOf(joined, [A, STOP, END], "bikeshare"), null);
});

// The wiring (App.tsx, RideMode.tsx), read as source.
const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");

test("a ride on a trip with stops rides its first trip, to the first stop, and keeps the stops left", () => {
  assert.match(app, /const left = asked\.transit \? stopsLeftOf\(asked, askedPoints, asked\.transit\.mode as PresetId\) : null;/);
  assert.match(app, /const route = left \? firstTripOf\(asked\) : asked;\s*const ridePoints = left \? askedPoints\.slice\(0, 2\) : askedPoints;/);
  // A trip check's change or Ride the rest keeps them; a new ride (or Roam's detour) drops them.
  assert.match(app, /if \(left\) tripStopsLeft\.current = left;\s*else if \(!rest \|\| rest\.roam\) tripStopsLeft\.current = null;/);
});

test("at the stop, one press plans the rest from where the rider is and rides it", () => {
  assert.equal(NEXT_LEG, "Start the next leg");
  assert.match(app, /onNextLeg=\{tripStopsLeft\.current \? nextLeg : undefined\}/);
  assert.match(app, /const points = nextLegPoints\(left, riderAt\);/);
  assert.match(app, /tripStopsLeft\.current = null;\s*beginRide\(ridePrefs, false, \{ route: result\.route, points \}\);/);
  // Shown once the trip to the stop is done: arrived, and every walk and train after the line followed.
  assert.match(ride, /\{onNextLeg && \(onwardParts\.length === 0 \|\| onwardDone\) && \(/);
});

test("Go's Add a stop takes stops on Walk and the transit types, not Bikeshare", () => {
  assert.match(app, /if \(current\.length < 2 \|\| \(twoPointsOnly\(ride\.preset\) && !stopsAsTrips\(ride\.preset\)\)\) \{/);
  assert.match(app, /\(!twoPointsOnly\(preset\) \|\| stopsAsTrips\(preset\)\) && !isMassRide\(preset\)/);
});
