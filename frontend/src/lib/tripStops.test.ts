// Stops on Walk and the transit types (Stephen, 2026-11-03: "Each stop starts a new trip"): the API joins each leg's
// trip (`stop_steps`), and the ride follows one trip at a time, with "Start the next leg" at each stop.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse, TransitPlan, TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { MAX_TRIP_STOPS, NEXT_LEG, firstTripOf, hasStops, maxPointsFor, nextLegPoints, stopsAsTrips, stopsLeftOf } from "./tripStops.ts";
import { MAX_POINTS } from "./geo.ts";

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

test("Walk, the transit types, Bikeshare and Rebalance Ride take stops as trips of their own; the riding types do not here", () => {
  for (const preset of ["walk", "walk-transit", "bike-transit", "bikeshare-transit", "bikeshare", "rebalance"] as const) assert.equal(stopsAsTrips(preset), true);
  for (const preset of ["default", "mass-ride"] as const) assert.equal(stopsAsTrips(preset), false);
});

test("a Bikeshare trip with stops is its first trip already: only the later ones go (v0.22.0)", () => {
  const later = [{ stop: 1, start: {}, end: {}, ride_m: 900, walk_m: 200, total_s: 600, steps: [], summary: "" }];
  const share = { geometry: { coordinates: [[0, 0], [1, 1]] }, transit: null, bikeshare: { total_s: 500, later, trip_total_s: 1100 } } as unknown as RouteResponse;
  assert.equal(hasStops(share), true);
  const first = firstTripOf(share);
  assert.equal(hasStops(first), false);
  assert.equal(first.geometry, share.geometry);
  assert.equal(first.bikeshare?.total_s, 500);
  assert.equal(first.bikeshare?.trip_total_s, null);
  assert.deepEqual(stopsLeftOf(share, [A, STOP, END], "bikeshare"), { preset: "bikeshare", points: [STOP, END] });
  // No stops: itself.
  const plain = { ...share, bikeshare: { total_s: 500, later: [] } } as unknown as RouteResponse;
  assert.equal(firstTripOf(plain), plain);
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
  assert.equal(stopsLeftOf(joined, [A, STOP, END], "default"), null);
});

// The wiring (App.tsx, RideMode.tsx), read as source.
const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");

test("a ride on a trip with stops rides its first trip, to the first stop, and keeps the stops left", () => {
  assert.match(app, /const left = asked\.transit \|\| asked\.bikeshare \? stopsLeftOf\(asked, askedPoints, \(asked\.transit\?\.mode \?\? asked\.preset\) as PresetId\) : null;/);
  assert.match(app, /const route = left \? firstTripOf\(asked\) : asked;\s*const ridePoints = left \? askedPoints\.slice\(0, 2\) : askedPoints;/);
  // A trip check's change or Ride the rest keeps them; a new ride (or Roam's detour) drops them.
  assert.match(app, /if \(left\) tripStopsLeft\.current = left;\s*else if \(!rest \|\| rest\.roam\) tripStopsLeft\.current = null;/);
});

test("at the stop, one press plans the rest from where the rider is and rides it", () => {
  assert.equal(NEXT_LEG, "Start the next leg");
  assert.match(app, /onNextLeg=\{tripStopsLeft\.current \? nextLeg : undefined\}/);
  assert.match(app, /const points = nextLegPoints\(left, riderAt\);/);
  // Bikeshare: the start's chosen pick-up is not the stop's; the end's chosen drop-off stays (v0.22.0).
  assert.match(app, /const legDials = withStations\(planDials, \{ dropoff: stationChoice\.dropoff \}\);\s*const result = await requestRoute\(points, left\.preset, \{ dials: \{ \.\.\.legDials, loop: false, closuresNow: true \} \}\);/);
  assert.match(app, /tripStopsLeft\.current = null;\s*beginRide\(ridePrefs, false, \{ route: result\.route, points \}\);/);
  // Shown once the trip to the stop is done: arrived, and every walk and train after the line followed.
  // Not beside the ride after a train (Ride the rest's, started by itself), still to go to the stop.
  assert.match(ride, /\{onNextLeg && !rest && \(onwardParts\.length === 0 \|\| onwardDone\) && \(/);
});

test("Go's Add a stop takes stops on Walk, the transit types, Bikeshare and Rebalance Ride", () => {
  assert.match(app, /if \(current\.length < 2 \|\| \(twoPointsOnly\(ride\.preset\) && !stopsAsTrips\(ride\.preset\)\)\) \{/);
  assert.match(app, /\(!twoPointsOnly\(preset\) \|\| stopsAsTrips\(preset\)\) && !isMassRide\(preset\)/);
});

test("the stops left go with the ride, and the panel's Ride the rest on a trip with stops rides to the first stop", () => {
  assert.match(app, /forgetLeftRide\(\);\s*\/\/ A trip's stops left go with the ride[^\n]*\n\s*const stopsLeft = tripStopsLeft\.current;\s*tripStopsLeft\.current = null;/);
  // Kept with the ride left going, so Resume still offers "Start the next leg"; Undo puts them back.
  assert.match(app, /leads: ledLink, stopsLeft: tripStopsLeft\.current \}, VIA_MARKS/);
  assert.match(app, /tripStopsLeft\.current = left\.stopsLeft \?\? null;/);
  assert.match(app, /tripStopsLeft\.current = ended\.stopsLeft;/);
  assert.match(app, /rideTripOf\(panelLeft \? firstTripOf\(shown\) : shown, panelLeft \? routedPoints\.slice\(0, 2\) : routedPoints\)/);
  assert.match(app, /if \(!fromRide\) tripStopsLeft\.current = panelLeft;/);
});

test("a trip of stops takes the server's most stops; adding one more is refused here, not by a failed plan", () => {
  const api = readFileSync(new URL("../../../src/core/api.py", import.meta.url), "utf8");
  assert.equal(Number(/^MAX_TRIP_STOPS = (\d+)$/m.exec(api)?.[1]), MAX_TRIP_STOPS);
  assert.equal(maxPointsFor("walk"), MAX_TRIP_STOPS + 2);
  assert.equal(maxPointsFor("default"), MAX_POINTS);
  assert.equal(maxPointsFor("bikeshare"), MAX_TRIP_STOPS + 2);
  assert.equal(maxPointsFor("rebalance"), MAX_TRIP_STOPS + 2);
});
