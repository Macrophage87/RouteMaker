// Riding a Bikeshare or transit plan (Stephen, 2026-10-16: "I can't start a bikeshare and transit ride.
// There's no button"): the rideable rules, the walk to the first dock, the dock and the boarding said at
// the end, and Ride the rest.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { BikesharePlan, DescriptionEntry, RouteResponse, TransitOption, TransitPlan, TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";
import { RIDE_MAX_M, pointAt, rideModel, startState, step, type RideEvent, type RideFix, type RideState } from "./navigate.ts";
import {
  REST_ANYWAY_MS,
  REST_FIX_MAX_AGE_MS,
  approachReached,
  approachStartSaid,
  approachWords,
  fixedRide,
  restClosedSaid,
  restFrom,
  tripRideStart,
  tripStep,
  restNear,
  restOffered,
  rideMaxM,
  restReadySaid,
  restRequest,
  rideLegOf,
  rideTripOf,
  rideable,
  ridesLine,
  noBikeLine,
  optionRides,
  withFinish,
  withoutSpare,
  type RideTrip,
} from "./rideTrip.ts";

// Spanish's catalog is fetched on choosing it (lib/i18n.ts loadLanguage), as the app does before it starts.
await loadLanguage("es");

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
  // No line step at all: nothing to ride, so no "too long" note either, unless riding your own bike the whole way.
  const noLine = { ...PLAN, steps: PLAN.steps.map((s) => ({ ...s, route_line: false })) };
  assert.equal(rideable(line({ transit: noLine })), false);
  assert.equal(ridesLine(line({ transit: noLine })), false);
  assert.equal(ridesLine(line({ transit: { ...noLine, direct: true, mode: "bike-transit" } })), true);
  // A long first ride goes to a bike computer, whatever the whole trip's length.
  assert.equal(rideable(line({ transit: PLAN, distance_m: RIDE_MAX_M + 1 })), false);
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /const rideable = rideableRoute\(route\);/);
});

test("an option with no ride says which option rides, in Start's place, with no stress bar (P10)", () => {
  const option = (o: Partial<TransitOption>): TransitOption => ({ key: "k", label: "", total_s: 0, minutes: 30, direct: false, chosen: false, ...o });
  const walkLeg = { mode: "walk", minutes: 4 };
  const metro = { mode: "metro", minutes: 25, system: "Metro", lines: ["Red Line"] };
  assert.equal(optionRides(option({ legs: [walkLeg, metro, walkLeg] })), false);
  assert.equal(optionRides(option({ legs: [{ mode: "bikeshare", minutes: 8 }, metro] })), true);
  assert.equal(optionRides(option({ direct: true })), true);
  assert.equal(optionRides(option({ direct: true, walk: true })), false);
  const walkLine = { ...PLAN, steps: PLAN.steps.map((s) => (s.route_line ? { ...s, mode: "walk" as const } : s)) };
  const options = [option({ legs: [walkLeg, metro, walkLeg] }), option({ legs: [walkLeg, metro] }), option({ legs: [walkLeg] , walk: true }), option({ direct: true })];
  assert.equal(noBikeLine(line({ transit: { ...walkLine, options } })), "No bike on this option. Pick D to ride.");
  assert.equal(noBikeLine(line({ transit: { ...walkLine, options: options.slice(0, 2) } })), "No bike on this option.");
  // An option that rides, and a route that is not a transit trip, have no such line.
  assert.equal(noBikeLine(line({ transit: { ...PLAN, options } })), null);
  assert.equal(noBikeLine(BIKESHARE), null);
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /const segments = capacity \|\| noBike \? \[\] : stressSegments\(route\.stress_m\);/);
  assert.match(panel, /\) : noBike \? \(\s*<p className="hint no-bike-line">\{noBike\}<\/p>/);
});

test("the phone app offers Start ride at any length; a browser stops at RIDE_MAX_M (Stephen, 2026-10-18: a 37 mi saved route)", () => {
  assert.equal(rideMaxM(false), RIDE_MAX_M);
  assert.equal(rideMaxM(true), Infinity);
  const long = line({ distance_m: 37 * 1609.344 });
  assert.equal(rideable(long, rideMaxM(false)), false);
  assert.equal(rideable(long, rideMaxM(true)), true);
  // In node there is no shell, so the default is the browser's limit.
  assert.equal(rideable(long), false);
  assert.equal(rideable(line({ bikeshare: SHARE, distance_m: RIDE_MAX_M * 3 }), rideMaxM(true)), true);
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
  // The early "across" sentence (D26) is said as itself, not as the finish: only the arrival takes the dock words.
  const far = rideModel(BIKESHARE);
  const end = far.cues[far.cues.length - 1];
  assert.equal(end.kind, "end");
  far.cues[far.cues.length - 1] = { ...end, farSide: "Florida Avenue" };
  let farState = startState();
  const farSaid: RideEvent[] = [];
  for (let m = 0; m <= 1000; m += 10) {
    const out = step(far, farState, fix(pointAt(far, m)), "full");
    farState = out.state;
    farSaid.push(...withFinish(out.events, trip.finish));
  }
  const ends = farSaid.filter((e) => e.cue?.kind === "end");
  assert.deepEqual(ends.map((e) => e.phase), ["advance", "arrive"]);
  assert.match(ends[0].spoken, /the destination is across Florida Avenue, on your left\.$/);
  assert.equal(ends[1].spoken, trip.finish!.spoken);
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
    // The planned "you arrive …, N min spare" is stale by then: the countdown says the time left instead.
    "Dock at Eastern Market. About 2 min into the station. Board the Orange Line at 7:42 am scheduled from Eastern Market. The next is 7:54 am. Ride 10 min to Federal Triangle.",
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
  assert.match(ride, /const stepped = tripStep\(modelRef\.current, trip, \{ \.\.\.tripRef\.current, ride: rideRef\.current \}, fix,/);
  assert.match(ride, /for \(const note of stepped\.notes\) notify\(note\);/);
  assert.match(ride, /void onRideRest\(restFrom\(tripRef\.current\.lastGood, Date\.now\(\)\)\)/);
  // Re-plan from here while walking repeats the walk.
  assert.match(ride, /if \(tripRef\.current\.walking && approach\) \{\n\s*answer\(approachWords\(/);
  assert.match(ride, /notify\(restReadySaid\(rest\)\);/);
  assert.match(ride, /<button type="button" onClick=\{rideTheRest\} aria-describedby=/);
  const summary = readFileSync(new URL("../TransitSummary.tsx", import.meta.url), "utf8");
  assert.match(summary, /onClick=\{onRideRest\} aria-describedby=\{`\$\{id\}-rest`\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const result = await requestRoute\(asked\.points, asked\.preset,/);
  assert.match(app, /if \(!rideableRoute\(result\.route\)\) return RIDE_TOO_LONG;/);
  // End ride (or another ride) while the request runs: nothing starts.
  assert.match(app, /const stillOn = \(\) => \(fromRide \? ridingNow\.current && rideNow\.current\.start\?\.n === n : !ridingNow\.current\);/);
  assert.match(app, /const result = await requestRoute\(asked\.points, asked\.preset, [^\n]*routeOnly: true \}\);\n\s*if \(!stillOn\(\)\) return null;/);
  assert.match(app, /if \(stillOn\(\)\) beginRide\(ridePrefs, false,/);
  // Closures on the ride screen: said, the route held, a second press within the minute rides it anyway.
  assert.match(app, /return restClosedSaid\(found\.closures\.map/);
  assert.match(app, /if \(fromRide && held && held\.n === n && Date\.now\(\) - held\.at < REST_ANYWAY_MS\) \{\n\s*closureLetGo\.current = lineKey/);
  // The panel's button ignores a second press while the first runs.
  assert.match(app, /if \(restPanelBusy\.current\) return;/);
});

test("closures on Ride the rest's line are said by name, once each", () => {
  assert.equal(restClosedSaid(["K Street", "K Street", "a closure"]), "Closed on the way: K Street, a closure. Press Ride the rest again to ride anyway.");
  assert.equal(REST_ANYWAY_MS, 60_000);
});

test("tripStep: walking to the dock is never off route; the walk is said at the first good fix; the dock hands over to the line", () => {
  const model = rideModel(BIKESHARE);
  const trip = rideTripOf(BIKESHARE, [])!;
  let s = tripRideStart(trip);
  assert.equal(s.walking, true);
  const notes: string[] = [];
  const events: RideEvent[] = [];
  const feed = (point: LonLat, accuracyM = 5) => {
    const out = tripStep(model, trip, s, { ...fix(point), accuracyM }, "full");
    s = out.state;
    notes.push(...out.notes);
    events.push(...out.events);
  };
  feed(at(0, -400), 200); // a poor fix: nothing said yet
  assert.deepEqual(notes, []);
  for (const north of [-400, -300, -200, -100, -60]) feed(at(0, north));
  assert.equal(s.walking, true);
  assert.deepEqual(notes, ["Walk to 4th & E St NW, 0.2 miles. 5 classic bikes available."]);
  assert.deepEqual(events, [], "no off route while walking");
  assert.equal(s.ride.progressM, null);
  assert.deepEqual(s.ride.fix?.point, at(0, -60), "the marker moves");
  feed(at(0, -20));
  assert.equal(s.walking, false);
  assert.equal(notes[notes.length - 1], "At 4th & E St NW. Take a bike and ride.");
  assert.ok(s.ride.progressM !== null && s.ride.progressM < 30);
  for (let m = 10; m <= 1000; m += 10) feed(pointAt(model, m));
  assert.equal(s.ride.arrived, true);
  assert.equal(events[events.length - 1].spoken, "Dock at Union Station. Walk 0.2 miles to the finish.");
  assert.ok(!events.some((e) => e.kind === "off-route"));
});

test("tripStep: a first good fix already at the dock skips the walk line", () => {
  const model = rideModel(BIKESHARE);
  const trip = rideTripOf(BIKESHARE, [])!;
  const out = tripStep(model, trip, tripRideStart(trip), fix(at(0, -10)), "full");
  assert.deepEqual(out.notes, ["At 4th & E St NW. Take a bike and ride."]);
  assert.equal(out.state.walking, false);
});

test("with a later first ride, only the first step is said at the start; Where am I? has them all", () => {
  const later = { ...PLAN, steps: [step_({ mode: "walk", text: "Walk 4 min to Eastern Market." }), ...PLAN.steps.slice(2, 5), step_({ ...PLAN.steps[6], route_line: true, coordinates: [] })] };
  const trip = rideTripOf(line({ transit: later }), [at(0, 0), TRIP_END])!;
  assert.equal(approachStartSaid(trip.approach!), "Walk 4 min to Eastern Market.");
  assert.match(approachWords(trip.approach!, null).spoken, /^Walk 4 min to Eastern Market\. About 2 min into the station\. Board the Orange Line/);
});

test("arrived, then on transit: Ride the rest starts from the last good fix near the alighting stop, not the drop-off dock", () => {
  const model = rideModel(TRANSIT_ROUTE);
  const trip = rideTripOf(TRANSIT_ROUTE, [at(0, -400), TRIP_END])!;
  let s = tripRideStart(trip);
  for (let m = 0; m <= 1000; m += 10) s = tripStep(model, trip, s, fix(pointAt(model, m)), "full").state;
  assert.equal(s.ride.arrived, true);
  const dock = s.ride.goodFix!.point;
  // Off the train, near the stop: the line's state takes no more fixes, the trip's last good fix does.
  const near = at(5080, 4060);
  s = tripStep(model, trip, s, fix(near), "full").state;
  assert.deepEqual(s.ride.goodFix!.point, dock, "the line's goodFix froze at arrival");
  assert.equal(restNear(trip.rest!, s.ride.fix!.point, s.ride.arrived), true);
  const from = restFrom(s.lastGood, s.lastGood!.at + 1000);
  assert.deepEqual(from, near);
  assert.deepEqual(restRequest(trip.rest!, from)!.points[0], near);
  // A fix over a minute old is not used: the leg's own start is.
  const stale = restFrom(s.lastGood, s.lastGood!.at + REST_FIX_MAX_AGE_MS);
  assert.equal(stale, null);
  assert.deepEqual(restRequest(trip.rest!, stale)!.points[0], at(5050, 4000));
});

test("a ride that stops short walks to the line first and says the walk on at the finish, re-planned as it was (walk_in)", () => {
  const line = [at(0, 0), at(500, 0)];
  const walk = (m: number) => ({ geometry: { type: "LineString" as const, coordinates: [at(500, 0), at(500, m)] }, distance_m: m, duration_s: m, to: "" });
  const route = { preset: "commute", geometry: { type: "LineString", coordinates: line }, walk_in: { start: walk(40), end: walk(90) } } as unknown as RouteResponse;
  const trip = rideTripOf(route, [at(0, -40), at(500, 90)]);
  assert.ok(trip?.asPlanned);
  assert.equal(trip?.approach?.metres, 40);
  assert.match(trip?.finish?.shown ?? "", /Walk your bike 300 ft \(90 m\) to your destination\./);
  const leg = rideLegOf(route, [at(0, -40), at(500, 90)], false);
  assert.equal(leg.preset, "commute");
  assert.deepEqual(leg.points, [at(0, -40), at(500, 90)]);
  const plain = { ...route, walk_in: null } as unknown as RouteResponse;
  assert.equal(rideTripOf(plain, []), null);
});

test("a shared ride or Mass Ride stays fixed with walks at its ends; a Bikeshare or transit leg and Ride the rest do not", () => {
  const line = [at(0, 0), at(500, 0)];
  const walk = (m: number) => ({ geometry: { type: "LineString" as const, coordinates: [at(500, 0), at(500, m)] }, distance_m: m, duration_s: m, to: "" });
  const route = { preset: "mass-ride", geometry: { type: "LineString", coordinates: line }, walk_in: { start: walk(40), end: walk(90) } } as unknown as RouteResponse;
  const leg = rideLegOf(route, [at(0, -40), at(500, 90)], false);
  assert.ok(leg.trip?.asPlanned);
  assert.equal(fixedRide(leg, null, false), true);
  assert.equal(fixedRide({ ...leg, preset: "commute" }, { ride: true }, false), true);
  assert.equal(fixedRide({ ...leg, preset: "commute" }, { ride: true, own: true }, false), false);
  assert.equal(fixedRide(leg, { ride: false }, false), false);
  assert.equal(fixedRide({ ...leg, preset: "commute" }, null, false), false);
  assert.equal(fixedRide(leg, null, true), false);
  const transit = { approach: null, finish: null, departure: null, rest: null } as RideTrip;
  assert.equal(fixedRide({ ...leg, trip: transit }, { ride: true }, false), false);
});

test("Spanish: the walk, dock and hand-off lines are Spanish, the names as they are, miles first (routing audit D30)", () => {
  setLanguageForTest("es");
  try {
    const trip = rideTripOf(BIKESHARE, [at(0, -400), DESTINATION])!;
    const words = approachWords(trip.approach!, null);
    assert.equal(words.shown, "Camine hasta 4th & E St NW, 0.2 mi (0.4 km). 5 bicicletas clásicas disponibles.");
    assert.equal(words.spoken, "Camine hasta 4th & E St NW, 0.2 millas. 5 bicicletas clásicas disponibles.");
    assert.equal(trip.approach!.reached, "Ha llegado a 4th & E St NW. Tome una bicicleta y pedalee.");
    assert.equal(trip.finish!.spoken, "Devuelva la bicicleta en Union Station. Camine 0.2 millas hasta el final.");
    const free = rideTripOf(line({ bikeshare: { ...SHARE, bike: "ebike", start: { ...SHARE.start, kind: "free_bike" } } as BikesharePlan }), [])!;
    assert.equal(approachWords(free.approach!, null).shown, "Camine hasta la bicicleta eléctrica estacionada fuera de una estación, 0.2 mi (0.4 km).");
    assert.equal(free.approach!.reached, "Ha llegado a la bicicleta eléctrica. Tómela y pedalee.");
    assert.equal(restReadySaid({ alightName: "Federal Triangle" }), "Cerca de Federal Triangle. Recorrer el resto planea el recorrido hasta su destino.");
    assert.equal(restClosedSaid(["K Street"]), "Cerrado en el camino: K Street. Presione Recorrer el resto otra vez para ir de todos modos.");
    const walk = (m: number) => ({ geometry: { type: "LineString" as const, coordinates: [at(500, 0), at(500, m)] }, distance_m: m, duration_s: m, to: "" });
    const walkIn = { preset: "commute", geometry: { type: "LineString", coordinates: [at(0, 0), at(500, 0)] }, walk_in: { start: walk(40), end: walk(90) } } as unknown as RouteResponse;
    const short = rideTripOf(walkIn, [at(0, -40), at(500, 90)])!;
    assert.equal(short.finish!.shown, "El recorrido termina aquí. Camine con su bicicleta 300 ft (90 m) hasta su destino.");
    assert.equal(short.approach!.reached, "Ha llegado al inicio del recorrido. Siga en bicicleta.");
    assert.equal(approachWords(short.approach!, null).spoken, "Camine hasta el inicio del recorrido, 130 pies.");
    // The API's Spanish boarding step (src/core/transit.py Leg.words) loses its arrival clause as the English does.
    assert.equal(
      withoutSpare("Suba al tren MARC Penn Line, sale 7:00 am según horario desde Union Station MARC: llegada 6:40 am, 20 min de margen; siguiente tren: 8:00 am según horario. Viaje 45 min hasta Baltimore Penn Station."),
      "Suba al tren MARC Penn Line, sale 7:00 am según horario desde Union Station MARC. Siguiente tren: 8:00 am según horario. Viaje 45 min hasta Baltimore Penn Station.",
    );
  } finally {
    setLanguageForTest("en");
  }
});
