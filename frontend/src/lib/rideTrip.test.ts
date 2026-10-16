// Riding a Bikeshare or transit plan (Stephen, 2026-10-16: "I can't start a bikeshare and transit ride.
// There's no button"): the rideable rules, the walk to the first dock, the dock and the boarding said at
// the end, and Ride the rest.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { BikesharePlan, DescriptionEntry, RouteResponse, TransitPlan, TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { RIDE_MAX_M, pointAt, rideModel, startState, step, type RideEvent, type RideFix, type RideState } from "./navigate.ts";
import {
  approachReached,
  approachWords,
  restNear,
  restOffered,
  restReadySaid,
  restRequest,
  rideLegOf,
  rideTripOf,
  rideable,
  ridesLine,
  withFinish,
} from "./rideTrip.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}

const DESCRIPTION: DescriptionEntry[] = [
  {
    kind: "stretch",
    from_m: 0,
    to_m: 1000,
    from_mi: 0,
    to_mi: 0.62,
    street: "A Street",
    tier: 1,
    facility: null,
    turn: null,
    text: "0.0 to 0.6 mi (0.0 to 1.0 km): A Street, low stress (LTS 1).",
  },
];

/** The ride leg: 1,000 m east on A Street, from the pickup dock to the drop-off dock. */
function line(extra: Partial<RouteResponse> = {}): RouteResponse {
  return {
    preset: "bikeshare",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0, 0), at(500, 0), at(1000, 0)] },
    distance_m: 1000,
    duration_s: 300,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [2],
    description: DESCRIPTION,
    bikeshare: null,
    transit: null,
    ...extra,
  } as RouteResponse;
}

const SHARE = {
  bike: "classic",
  ending: "dock",
  start: { kind: "dock", name: "4th & E St NW", lon: at(0, 0)[0], lat: at(0, 0)[1], availability: "known", bikes_available: 5, docks_available: 3 },
  end: { kind: "dock", name: "Union Station", lon: at(1000, 0)[0], lat: at(1000, 0)[1], availability: "known", bikes_available: 2, docks_available: 9 },
  walk_start: { geometry: { type: "LineString", coordinates: [at(0, -400), at(0, 0)] }, distance_m: 400, duration_s: 300, to: "4th & E St NW" },
  walk_end: { geometry: { type: "LineString", coordinates: [at(1000, 0), at(1000, 300)] }, distance_m: 300, duration_s: 220, to: "your destination" },
} as unknown as BikesharePlan;

const BIKESHARE = line({ bikeshare: SHARE });
const DESTINATION = at(1000, 300);

let clock = 0;
function fix(point: LonLat): RideFix {
  clock += 3000;
  return { point, accuracyM: 5, speedMs: 1.4, headingDeg: null, at: clock };
}

test("Start ride is offered on a Bikeshare plan and on a transit plan's riding leg, not on a walk; the bike computer rule is the leg's", () => {
  assert.equal(rideable(BIKESHARE), true);
  assert.equal(rideable(line({ bikeshare: SHARE, distance_m: RIDE_MAX_M + 1 })), false);
  assert.equal(ridesLine(BIKESHARE), true);
  assert.equal(rideable(TRANSIT_ROUTE), true);
  const walkLine = { ...PLAN, steps: PLAN.steps.map((s) => (s.route_line ? { ...s, mode: "walk" as const } : s)) };
  assert.equal(rideable(line({ transit: walkLine })), false);
  assert.equal(ridesLine(line({ transit: walkLine })), false);
  // A long first ride goes to a bike computer, whatever the whole trip's length.
  assert.equal(rideable(line({ transit: PLAN, distance_m: RIDE_MAX_M + 1 })), false);
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /const rideable = rideableRoute\(route\);/);
});

test("the ride follows the leg: from the line's start to its end, re-planned on a plain ride type", () => {
  const leg = rideLegOf(BIKESHARE, [at(0, -400), DESTINATION], false);
  assert.deepEqual(leg.points, [at(0, 0), at(1000, 0)]);
  assert.equal(leg.preset, "default");
  assert.equal(rideLegOf(line({ bikeshare: { ...SHARE, bike: "ebike" } }), [], false).preset, "ebike");
  const plain = line({ preset: "standard" as RouteResponse["preset"] });
  assert.deepEqual(rideLegOf(plain, [at(0, 0), at(5, 5)], true), { points: [at(0, 0), at(5, 5)], loop: true, preset: "standard", trip: null });
});

test("the walk to the first dock is said with the dock's count, US units first, and spoken without metric", () => {
  const trip = rideTripOf(BIKESHARE, [at(0, -400), DESTINATION])!;
  const words = approachWords(trip.approach!, null);
  assert.equal(words.shown, "Walk to 4th & E St NW, 0.2 mi (0.4 km). 5 classic bikes available.");
  assert.equal(words.spoken, "Walk to 4th & E St NW, 0.2 miles. 5 classic bikes available.");
  // From a fix, the distance left as the crow flies.
  assert.match(approachWords(trip.approach!, at(0, -100)).shown, /^Walk to 4th & E St NW, 330 ft \(100 m\)\./);
});

test("walking to the first dock is never off route; reaching it starts the cues", () => {
  const model = rideModel(BIKESHARE);
  const approach = rideTripOf(BIKESHARE, [])!.approach!;
  // RideMode's gate (onFix): fixes before the dock move the marker only.
  let state: RideState = startState();
  let walking = true;
  const events: RideEvent[] = [];
  const walk: LonLat[] = [at(0, -400), at(0, -300), at(0, -200), at(0, -100), at(0, -60)];
  for (const point of walk) {
    const f = fix(point);
    if (walking && !approachReached(model, approach, f)) continue;
    walking = false;
    const out = step(model, state, f, "full");
    state = out.state;
    events.push(...out.events);
  }
  assert.equal(walking, true);
  assert.equal(events.length, 0);
  // Without the gate, the same walk is taken as off route.
  let raw = startState();
  const rawEvents: RideEvent[] = [];
  for (const point of walk) {
    const out = step(model, raw, fix(point), "full");
    raw = out.state;
    rawEvents.push(...out.events);
  }
  assert.ok(rawEvents.some((e) => e.kind === "off-route"));
  // At the dock: the walk ends and the ride is placed at the line's start.
  const atDock = fix(at(0, -20));
  assert.equal(approachReached(model, approach, atDock), true);
  const out = step(model, state, atDock, "full");
  assert.equal(out.state.off, false);
  assert.ok(out.state.progressM !== null && out.state.progressM < 30);
  // A poor fix never ends the walk.
  assert.equal(approachReached(model, approach, { point: at(0, -10), accuracyM: 200 }), false);
});

test("at the drop-off dock the ride says 'Dock at' and the walk to the finish", () => {
  const trip = rideTripOf(BIKESHARE, [])!;
  assert.equal(trip.finish!.shown, "Dock at Union Station. Walk 0.2 mi (0.3 km) to the finish.");
  assert.equal(trip.finish!.spoken, "Dock at Union Station. Walk 0.2 miles to the finish.");
  const model = rideModel(BIKESHARE);
  let state = startState();
  const said: RideEvent[] = [];
  for (let m = 0; m <= 1000; m += 10) {
    const out = step(model, state, fix(pointAt(model, m)), "full");
    state = out.state;
    said.push(...withFinish(out.events, trip.finish));
  }
  assert.equal(state.arrived, true);
  assert.equal(said[said.length - 1].spoken, trip.finish!.spoken);
  // An e-bike left at the destination ends as a normal finish.
  assert.equal(rideTripOf(line({ bikeshare: { ...SHARE, end: { ...SHARE.end, kind: "outside_dock" }, walk_end: null } }), [])!.finish, null);
});

// Bikeshare + transit, trimmed: walk to a dock, ride it to Eastern Market, Metro, then a share bike on.
const step_ = (s: Partial<TransitStep>): TransitStep =>
  ({ text: "", seconds: 60, wait_s: 0, to: null, lines: [], with_bike: false, route_line: false, coordinates: [], ...s }) as TransitStep;
const PLAN: TransitPlan = {
  mode: "bikeshare-transit",
  key: "k",
  direct: false,
  options: [],
  total_s: 1800,
  minutes: 30,
  summary: "About 30 min door to door, scheduled.",
  bike_only_s: null,
  comparison: null,
  riding_quicker: false,
  steps: [
    step_({ mode: "take", to: "4th & E St NW", text: "Walk 5 min to the bikeshare dock at 4th & E St NW and take a classic bike.", coordinates: [at(0, -400), at(0, 0)] }),
    step_({ mode: "bikeshare", to: "Eastern Market", text: "Ride the bikeshare bike 4 min and dock it at Eastern Market.", route_line: true }),
    step_({ mode: "enter", text: "About 2 min into the station." }),
    step_({
      mode: "metro",
      to: "Federal Triangle",
      lines: ["Orange Line"],
      text: "Board the Orange Line at 7:42 am scheduled from Eastern Market: you arrive 7:38 am, 4 min spare; the next is 7:54 am. Ride 10 min to Federal Triangle.",
      coordinates: [at(1000, 0), at(3000, 2000), at(5000, 4000)],
    }),
    step_({ mode: "exit", text: "About 2 min out of the station." }),
    step_({ mode: "take", to: "12th & Pennsylvania", text: "Walk 1 min to the bikeshare dock at 12th & Pennsylvania and take a classic bike.", coordinates: [at(5000, 4000), at(5050, 4000)] }),
    step_({ mode: "bikeshare", to: "14th & F", text: "Ride the bikeshare bike 3 min and dock it at 14th & F.", coordinates: [at(5050, 4000), at(5800, 4000)] }),
    step_({ mode: "walk", text: "Walk 2 min to your destination." }),
  ],
  notes: [],
  day_type: "weekday",
  band: null,
  holiday: false,
  bike_blackout: false,
  scheduled: true,
  credits: [],
  departure: { step: 3, departs: "7:42 am" } as TransitPlan["departure"],
};
const TRANSIT_ROUTE = line({ preset: "bikeshare-transit", transit: PLAN });
const TRIP_END = at(5900, 4100);

test("a transit plan's first ride: the walk to its dock, then the dock and the plan's own boarding steps", () => {
  const trip = rideTripOf(TRANSIT_ROUTE, [at(0, -400), TRIP_END])!;
  assert.equal(approachWords(trip.approach!, null).shown, "Walk to 4th & E St NW, 0.2 mi (0.4 km).");
  assert.equal(
    trip.finish!.shown,
    "Dock at Eastern Market. About 2 min into the station. Board the Orange Line at 7:42 am scheduled from Eastern Market: you arrive 7:38 am, 4 min spare; the next is 7:54 am. Ride 10 min to Federal Triangle.",
  );
  // The departure the boarding leads to keeps its countdown (DepartureTimer) on the ride screen.
  assert.equal(trip.departure?.departs, "7:42 am");
});

test("Ride the rest: the last riding leg after the transit, offered near or past the stop, planned from here", () => {
  const trip = rideTripOf(TRANSIT_ROUTE, [at(0, -400), TRIP_END])!;
  assert.ok(restOffered(trip));
  const rest = trip.rest!;
  assert.deepEqual(rest.alight, at(5000, 4000));
  assert.equal(rest.alightName, "Federal Triangle");
  assert.equal(rest.preset, "bikeshare");
  assert.equal(restReadySaid(rest), "Near Federal Triangle. Ride the rest plans the ride to your destination.");
  // Near the stop where the transit ends; past it only once the first ride is done; never at the start.
  assert.equal(restNear(rest, at(5100, 4100), false), true);
  assert.equal(restNear(rest, at(0, -400), true), false);
  assert.equal(restNear(rest, at(5600, 4000), false), false);
  assert.equal(restNear(rest, at(5600, 4000), true), true);
  assert.equal(restNear(rest, null, true), false);
  // The request: from the rider's place, else the leg's own start, to the destination, on the leg's ride type.
  assert.deepEqual(restRequest(rest, at(5100, 4100)), { points: [at(5100, 4100), TRIP_END], preset: "bikeshare" });
  assert.deepEqual(restRequest(rest, null), { points: [at(5050, 4000), TRIP_END], preset: "bikeshare" });
  // Your own bike's last ride is Default's.
  const own = { ...PLAN, mode: "bike-transit" as const, steps: PLAN.steps.map((s) => (s.mode === "bikeshare" ? { ...s, mode: "ride" as const } : s)) };
  assert.equal(rideTripOf(line({ transit: own }), [at(0, 0), TRIP_END])!.rest!.preset, "default");
  // Riding the whole way has nothing after the line.
  assert.equal(rideTripOf(line({ transit: { ...PLAN, steps: [PLAN.steps[1]] } }), [at(0, 0), TRIP_END])!.rest, null);
});

test("the ride screen and the trip panel wire Ride the rest and the walk through the ride's outputs", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /if \(walkingRef\.current && approach\) \{\n\s*if \(!approachReached\(/);
  assert.match(ride, /say\(withFinish\(out\.events, trip\?\.finish \?\? null\)\);/);
  assert.match(ride, /notify\(restReadySaid\(rest\)\);/);
  assert.match(ride, /<button type="button" onClick=\{rideTheRest\} aria-describedby=/);
  const summary = readFileSync(new URL("../TransitSummary.tsx", import.meta.url), "utf8");
  assert.match(summary, /onClick=\{onRideRest\} aria-describedby=\{`\$\{id\}-rest`\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const result = await requestRoute\(asked\.points, asked\.preset,/);
  assert.match(app, /if \(!rideableRoute\(result\.route\)\) return RIDE_TOO_LONG;/);
});
