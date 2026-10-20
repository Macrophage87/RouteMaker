// Ride mode's engine (WEB-NAV-plan.md sections 2-4): progress along the line, the cue schedule per
// level, off route with its hysteresis, the re-plan's points and gate, and the words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { spokenDistance } from "./format.ts";
import {
  ADVANCE_MIN_M,
  END_FIX_MAX_AGE_MS,
  END_PART_WAY_M,
  END_LEFT_MIN_M,
  END_LEFT_MIN_SHARE,
  JOG_M,
  ONTO_TRAIL_MIN_M,
  planAfterEnd,
  GPS_WEAK_MS,
  GPS_WEAK_SAID,
  weighFix,
  CUE_SHEET_MIN_MS,
  CUE_SHEET_ROWS,
  cueSheet,
  cueSheetAfterMs,
  cueSheetShown,
  CUE_SHEET_CHECK_MS,
  BACK_ON_ROUTE_SAID,
  OFF_ROUTE_KEPT_SAID,
  OFF_ROUTE_SAID,
  REPLAN_BACKOFF_MS,
  REPLAN_GAP_MS,
  ReplanGate,
  arrivalSideWords,
  compassWord,
  crossingWords,
  cueSpoken,
  isUnnamed,
  measureMap,
  nextAction,
  offThreshold,
  otherStreet,
  placeOnRoute,
  pointAt,
  routeJunctions,
  TRAIL_MARKER_M,
  replanPoints,
  rideModel,
  REPLAN_UTURN,
  says,
  setsOffBack,
  UTURN_SAID,
  withUTurn,
  sentenceOf,
  snap,
  startState,
  step,
  toGo,
  turnWords,
  wayBack,
  ontoWords,
  wayRidden,
  wayWords,
  whereAmI,
  withoutMetric,
  type Cue,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./navigate.ts";
import { parseTrailMiles } from "./trailMiles.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);

/** A point `east` and `north` metres from the origin. */
function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}

function stretch(from: number, to: number, text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return {
    kind: "stretch",
    from_m: from,
    to_m: to,
    from_mi: from / 1609.344,
    to_mi: to / 1609.344,
    street: null,
    tier: 1,
    facility: null,
    turn: null,
    text,
    ...extra,
  };
}

/** East 1,000 m on A Street, left (north) 1,000 m on B Street, with a red junction at 1,500 m. */
function lRoute(): RouteResponse {
  const description: DescriptionEntry[] = [
    stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): A Street, low stress (LTS 1).", { street: "A Street" }),
    stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Left onto B Street at a signal, low stress (LTS 1).", {
      street: "B Street",
      turn: { movement: "left", onto: "B Street", control: "signal", severity: null },
    }),
    {
      ...stretch(1500, 1500, "At 0.9 mi (1.5 km): Cross C Street (LTS 4), no signal mapped (Very high stress junction)."),
      kind: "junction",
      street: "C Street",
      tier: null,
      severity: "red",
      turn: { movement: "straight", onto: null, control: "none", severity: "red" },
    },
  ];
  return {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0, 0), at(500, 0), at(1000, 0), at(1000, 500), at(1000, 1000)] },
    distance_m: 2000,
    duration_s: 400,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [4],
    description,
  } as RouteResponse;
}

let clock = 0;
function fix(point: LonLat, extra: Partial<RideFix> = {}): RideFix {
  clock += 1000;
  return { point, accuracyM: 5, speedMs: 5, headingDeg: null, at: clock, ...extra };
}

/** Ride the line from `fromM` to `toM` in `stepM` steps, `offM` metres to the side; every event said. */
function ride(model: RideModel, level: Verbosity, fromM: number, toM: number, stepM = 5, state: RideState = startState()) {
  const events: RideEvent[] = [];
  let s = state;
  for (let m = fromM; m <= toM; m += stepM) {
    const out = step(model, s, fix(pointAt(model, m)), level);
    s = out.state;
    events.push(...out.events);
  }
  return { state: s, events };
}

test("sentenceOf: the API's sentence without its position", () => {
  assert.equal(sentenceOf({ text: "0.6 to 1.2 mi (1.0 to 2.0 km): Left onto B Street." }), "Left onto B Street.");
  assert.equal(sentenceOf({ text: "Stop 1 at 4.2 mi (6.8 km)." }), "Stop 1 at 4.2 mi (6.8 km).");
});

test("rideModel: a cue for the turn, the flagged crossing and the end; none for the start", () => {
  const model = rideModel(lRoute());
  assert.deepEqual(
    model.cues.map((c) => c.kind),
    ["turn", "hazard", "end"],
  );
  const turn = model.cues[0];
  assert.equal(turn.movement, "left");
  assert.equal(turn.street, "B Street");
  // The turn and the street only (v0.7.0 "Go riding fixes" item 2): no junction or stress words.
  assert.equal(turn.text, "Left onto B Street.");
  assert.ok(Math.abs(turn.atM - 1000) < 2, `${turn.atM}`);
  assert.ok(Math.abs(model.lengthM - 2000) < 2);
});

test("rideModel: a work zone on the route is a hazard cue; the disclaimer line is not a cue", () => {
  const route = lRoute();
  const zone = (from: number, text: string, severity: DescriptionEntry["severity"]): DescriptionEntry => ({
    ...stretch(from, from, text),
    kind: "workzone",
    tier: null,
    severity,
  });
  route.description = [
    zone(0, "Work zones are the transportation agencies' own data.", null),
    ...(route.description ?? []).slice(0, 1),
    zone(600, "Work zone ahead at 0.4 mi (0.6 km) on A Street: a lane closed.", "orange"),
    ...(route.description ?? []).slice(1),
  ];
  const model = rideModel(route);
  assert.deepEqual(
    model.cues.map((c) => c.kind),
    ["hazard", "turn", "hazard", "end"],
  );
  assert.ok(Math.abs(model.cues[0].atM - 600) < 2, `${model.cues[0].atM}`);
  assert.ok(says("stoker", model.cues[0]), "Stoker hears an orange work zone");
});

test("rideModel: a climb in the description is not a cue, and the stretch after it is read against the stretch before", () => {
  const route = lRoute();
  const plain = rideModel(lRoute()).cues.map((c) => c.kind);
  const stretches = route.description ?? [];
  route.description = [
    ...stretches.slice(0, 1),
    {
      ...stretch(600, 1400, "At 0.4 mi (0.6 km): Category 5 climb, 0.5 miles (0.8 km) at 5.4%, 141 ft (43 m) gained, to the summit at 0.9 mi (1.4 km)."),
      kind: "climb",
      tier: null,
    },
    ...stretches.slice(1),
  ];
  assert.deepEqual(
    rideModel(route).cues.map((c) => c.kind),
    plain,
  );
});

test("measureMap: stops anchor on their vertices however the two measures drift", () => {
  // The route's measure says the stop is at 1,200 m; its vertex is at 1,000 m along the line.
  const along = new Float64Array([0, 500, 1000, 1500, 2000]);
  const map = measureMap(
    {
      distance_m: 2400,
      leg_ends: [2, 4],
      description: [
        stretch(0, 1200, "x"),
        { ...stretch(1200, 1200, "Stop 1 at 0.7 mi (1.2 km)."), kind: "via", via: 1 },
        stretch(1200, 2400, "y"),
      ],
    },
    along,
  );
  assert.equal(map(0), 0);
  assert.equal(map(1200), 1000);
  assert.equal(map(600), 500);
  assert.equal(map(2400), 2000);
  assert.equal(map(1800), 1500);
  // Without usable stops: one scale for the whole route.
  const flat = measureMap({ distance_m: 4000, leg_ends: [4], description: null }, along);
  assert.equal(flat(2000), 1000);
});

test("snap: windowed, and the first pass of an out-and-back", () => {
  // Out 1,000 m and back on the same street.
  const coordinates = [at(0, 0), at(1000, 0), at(0, 0)];
  const along = new Float64Array([0, 1000, 2000]);
  const model = { coordinates, along };
  assert.ok(Math.abs((snap(model, at(300, 3))?.alongM ?? -1) - 300) < 1, "the way out first");
  assert.ok(Math.abs((snap(model, at(300, 3), 1500, 2000)?.alongM ?? -1) - 1700) < 1, "the window holds the way back");
  // A window that cuts a segment: the nearest point inside it.
  assert.ok(Math.abs((snap(model, at(900, 0), 0, 500)?.alongM ?? -1) - 500) < 1);
});

test("Full: advance, prepare and now at a turn, each once, farthest first", () => {
  const model = rideModel(lRoute());
  const { events } = ride(model, "full", 0, 1100);
  const turn = events.filter((e) => e.cue?.kind === "turn");
  assert.deepEqual(
    turn.map((e) => e.phase),
    ["advance", "prepare", "now"],
  );
  assert.match(turn[0].spoken, /^In \d+ feet, left onto B Street\.$/);
  assert.equal(turn[2].spoken, "Left now onto B Street.");
  assert.equal(turn[2].urgent, true);
  assert.equal(turn[0].urgent, false);
  // At 5 m/s the advance is the 500 ft floor (150 m), not 27 s (135 m).
  assert.ok(turn[0].spoken.includes("500 feet") || turn[0].spoken.includes("450 feet"), turn[0].spoken);
});

test("Stoker: one warning ahead and now at a turn; the red crossing; arrival", () => {
  const model = rideModel(lRoute());
  const { events, state } = ride(model, "stoker", 0, 2000);
  assert.deepEqual(
    events.map((e) => `${e.cue?.kind}:${e.phase}`),
    ["turn:ahead", "turn:now", "hazard:ahead", "end:arrive"],
  );
  assert.equal(state.arrived, true);
  assert.equal(events[3].spoken, "You have arrived at the end of the route.");
  assert.match(events[2].spoken, /^In \d+ feet, busy crossing at C Street, no signal\.$/);
});

test("Quiet: nothing but arrival", () => {
  const model = rideModel(lRoute());
  const { events } = ride(model, "quiet", 0, 2000);
  assert.deepEqual(
    events.map((e) => e.phase),
    ["arrive"],
  );
});

/** lRoute with the junction at 1,500 m set to `control`, and the left onto B Street at `turnSeverity`. */
function busyRoute(control: "signal" | "stop" | "all_stop" | "none" | null, turnSeverity: "orange" | "red" | null = null): RouteResponse {
  const route = lRoute();
  const [a, b, j] = route.description as DescriptionEntry[];
  const turn = { ...(b.turn as NonNullable<DescriptionEntry["turn"]>), severity: turnSeverity };
  return { ...route, description: [a, { ...b, turn, severity: turnSeverity }, { ...j, turn: { ...(j.turn as NonNullable<DescriptionEntry["turn"]>), control } }] };
}

test("a flagged crossing is one short line: the street and its control, no LTS or stress words; the cue sheet keeps the API's", () => {
  const signal = rideModel(busyRoute("signal"));
  const { events } = ride(signal, "full", 0, 2000);
  const crossing = events.filter((e) => e.cue?.kind === "hazard");
  assert.equal(crossing.length, 1);
  assert.match(crossing[0].spoken, /^In \d+ feet, busy crossing at C Street, signal\.$/);
  const hazard = signal.cues.find((c) => c.kind === "hazard");
  assert.equal(hazard?.rideText, "Busy crossing at C Street, signal.");
  assert.equal(hazard?.text, "Cross C Street (LTS 4), no signal mapped (Very high stress junction).");
  const none = ride(rideModel(busyRoute("none")), "full", 0, 2000).events.find((e) => e.cue?.kind === "hazard");
  assert.match(none?.spoken ?? "", /^In \d+ feet, busy crossing at C Street, no signal\.$/);
  assert.equal(rideModel(busyRoute("stop")).cues.find((c) => c.kind === "hazard")?.rideText, "Busy crossing at C Street, stop sign.");
  assert.equal(rideModel(busyRoute("all_stop")).cues.find((c) => c.kind === "hazard")?.rideText, "Busy crossing at C Street, stop sign.");
  assert.equal(rideModel(busyRoute(null)).cues.find((c) => c.kind === "hazard")?.rideText, "Busy crossing at C Street.");
  for (const e of events) assert.doesNotMatch(e.spoken, /LTS|stress junction/, e.spoken);
});

test("a turn at a red junction says Busy junction in its first warning only; now is the turn alone", () => {
  const model = rideModel(busyRoute("signal", "red"));
  const turn = ride(model, "full", 0, 1100).events.filter((e) => e.cue?.kind === "turn");
  assert.deepEqual(turn.map((e) => e.phase), ["advance", "prepare", "now"]);
  assert.match(turn[0].spoken, /^In \d+ feet, left onto B Street\. Busy junction\.$/);
  assert.match(turn[1].spoken, /^In \d+ feet, left onto B Street\.$/);
  assert.equal(turn[2].spoken, "Left now onto B Street.");
  // The stoker's one warning ahead is its first.
  const stoker = ride(model, "stoker", 0, 1100).events.filter((e) => e.cue?.kind === "turn");
  assert.match(stoker[0].spoken, /^In \d+ feet, left onto B Street\. Busy junction\.$/);
  assert.equal(stoker[1].spoken, "Left now onto B Street.");
  // The card's and the cue sheet's line is the turn alone.
  assert.equal(model.cues.find((c) => c.kind === "turn")?.text, "Left onto B Street.");
  // Quiet stays quiet.
  assert.deepEqual(ride(model, "quiet", 0, 2000).events.map((e) => e.phase), ["arrive"]);
});

test("a flagged turn first said at prepare (a ride started close to it) still says Busy junction", () => {
  const model = rideModel(busyRoute("signal", "red"));
  const turnAt = model.cues.find((c) => c.kind === "turn")!.atM;
  const turn = ride(model, "full", turnAt - 30, turnAt + 20).events.filter((e) => e.cue?.kind === "turn");
  assert.deepEqual(turn.map((e) => e.phase), ["prepare", "now"]);
  assert.match(turn[0].spoken, /^In \d+ feet, left onto B Street\. Busy junction\.$/);
});

test("an unnamed busy crossing says only that it is busy", () => {
  assert.equal(crossingWords(null, "signal"), "Busy crossing, signal.");
  assert.equal(crossingWords(null, undefined), "Busy crossing.");
});

test("a turn at an unflagged junction is the turn and the street only", () => {
  const turn = ride(rideModel(busyRoute("signal")), "full", 0, 1100).events.filter((e) => e.cue?.kind === "turn");
  assert.match(turn[0].spoken, /^In \d+ feet, left onto B Street\.$/);
  assert.equal(turn[2].spoken, "Left now onto B Street.");
});

test("says: the plan's table per level", () => {
  const busy3 = { kind: "busy" as const, tier: 3, severity: null };
  const busy4 = { kind: "busy" as const, tier: 4, severity: null };
  const orange = { kind: "hazard" as const, tier: null, severity: "orange" as const };
  assert.equal(says("full", busy3), true);
  assert.equal(says("stoker", busy3), false);
  assert.equal(says("stoker", busy4), true);
  assert.equal(says("stoker", orange), true);
  assert.equal(says("stoker", { kind: "unpaved", tier: 1, severity: null }), false);
  assert.equal(says("stoker", { kind: "calmer", tier: 1, severity: null }), false);
  assert.equal(says("quiet", { kind: "stop", tier: null, severity: null }), true);
  assert.equal(says("quiet", { kind: "turn", tier: null, severity: null }), false);
});

test("a ride that starts inside a cue's threshold says only the nearest phase", () => {
  const model = rideModel(lRoute());
  const { events } = ride(model, "full", 960, 975);
  assert.deepEqual(
    events.filter((e) => e.cue?.kind === "turn").map((e) => e.phase),
    ["prepare"],
  );
});

test("a cue passed during a gap is dropped, not said late", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 800).state;
  // Twenty seconds without a fix, then the rider is past the turn.
  clock += 20_000;
  const out = step(model, s, fix(pointAt(model, 1100)), "full");
  s = out.state;
  assert.deepEqual(out.events, []);
  assert.ok((s.progressM ?? 0) > 1050, `${s.progressM}`);
});

test("poor fixes move nothing but the marker", () => {
  const model = rideModel(lRoute());
  const s = ride(model, "full", 0, 100).state;
  const out = step(model, s, fix(at(600, 300), { accuracyM: 80 }), "full");
  assert.equal(out.state.progressM, s.progressM);
  assert.equal(out.state.off, false);
  assert.deepEqual(out.state.fix?.point, at(600, 300));
});

test("jitter backwards at a light does not move progress back", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 400).state;
  const before = s.progressM ?? 0;
  for (const back of [10, 25, 5, 20]) s = step(model, s, fix(pointAt(model, before - back)), "full").state;
  assert.ok((s.progressM ?? 0) >= before - 30, `${s.progressM}`);
});

test("off route: three far fixes over 8 s, said once; back within half clears it", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 300).state;
  const events: RideEvent[] = [];
  // 60 m north of the line, one fix a second.
  for (let i = 0; i < 12; i += 1) {
    const out = step(model, s, fix(at(300, 60)), "full");
    s = out.state;
    events.push(...out.events);
  }
  assert.equal(s.off, true);
  assert.deepEqual(
    events.map((e) => e.spoken),
    [OFF_ROUTE_SAID],
  );
  assert.equal(events[0].urgent, true);
  // 20 m off is inside the 30 m threshold but not inside half of it: still off.
  s = step(model, s, fix(at(300, 20)), "full").state;
  assert.equal(s.off, true);
  const back = step(model, s, fix(at(305, 5)), "full");
  assert.equal(back.state.off, false);
  assert.deepEqual(
    back.events.map((e) => e.spoken),
    [BACK_ON_ROUTE_SAID],
  );
});

test("off route needs the time as well as the fixes; a quick swerve is not off", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 300).state;
  for (let i = 0; i < 3; i += 1) s = step(model, s, fix(at(300, 60), { at: (clock += 500) }), "full").state;
  assert.equal(s.off, false);
  s = step(model, s, fix(at(300, 2)), "full").state;
  assert.equal(s.offCount, 0);
});

test("off route without re-planning says only that", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 300).state;
  const said: string[] = [];
  for (let i = 0; i < 12; i += 1) {
    const out = step(model, s, fix(at(300, 60)), "full", false);
    s = out.state;
    said.push(...out.events.map((e) => e.spoken));
  }
  assert.deepEqual(said, [OFF_ROUTE_KEPT_SAID]);
});

test("offThreshold: 100 ft floor, 1.5 x accuracy, 330 ft cap", () => {
  assert.equal(offThreshold(5), 30);
  assert.equal(offThreshold(40), 60);
  assert.equal(offThreshold(500), 100);
});

test("spokenDistance and withoutMetric: US units only when spoken", () => {
  assert.equal(spokenDistance(15), "50 feet");
  assert.equal(spokenDistance(91.44), "300 feet");
  assert.equal(spokenDistance(150), "500 feet");
  assert.equal(spokenDistance(643.7), "0.4 miles");
  assert.equal(spokenDistance(1609.344), "1 mile");
  assert.equal(spokenDistance(3218.7), "2 miles");
  assert.equal(withoutMetric("Walk your bike here, for 300 ft (90 m)."), "Walk your bike here, for 300 ft.");
  assert.equal(withoutMetric("1.0 to 1.6 mi (1.6 to 2.6 km): 6 crossings"), "1.0 to 1.6 mi: 6 crossings");
  assert.equal(withoutMetric("low stress (LTS 1)."), "low stress (LTS 1).");
});

test("cueSpoken: stops and the end", () => {
  const model = rideModel(lRoute());
  assert.equal(cueSpoken({ ...model.cues[0], kind: "stop", stop: 2 }, "arrive", 0), "You have reached stop 2.");
  assert.equal(cueSpoken({ ...model.cues[0], movement: "right", street: null }, "now", 0), "Right now.");
});

/** Two legs: east 1,000 m to a stop, then north 1,000 m to the end. */
function twoLegs(): RouteResponse {
  const route = lRoute();
  return {
    ...route,
    leg_ends: [2, 4],
    description: [
      stretch(0, 1000, "0.0 to 0.6 mi: A Street, low stress (LTS 1).", { street: "A Street" }),
      { ...stretch(1000, 1000, "Stop 1 at 0.6 mi (1.0 km)."), kind: "via", via: 1 },
      stretch(1000, 2000, "0.6 to 1.2 mi: Left onto B Street, busy road (LTS 3).", {
        street: "B Street",
        tier: 3,
        turn: { movement: "left", onto: "B Street", control: null, severity: null },
      }),
    ],
  };
}

test("stops: reached and said, at every level", () => {
  const model = rideModel(twoLegs());
  const { events } = ride(model, "quiet", 0, 2000);
  assert.deepEqual(
    events.map((e) => e.spoken),
    ["You have reached stop 1.", "You have arrived at the end of the route."],
  );
});

test("toGo and whereAmI: to the next stop and the end; US units spoken, metric on screen", () => {
  const model = rideModel(twoLegs());
  const { state } = ride(model, "quiet", 0, 400);
  const togo = toGo(model, state.progressM ?? 0);
  assert.equal(togo.stop?.number, 1);
  assert.ok(Math.abs((togo.stop?.metres ?? 0) - 600) < 3);
  assert.ok(Math.abs(togo.end.metres - 1600) < 3);
  assert.ok(Math.abs((togo.end.seconds ?? 0) - 320) < 2, "at the route's own pace, 5 m/s");
  const spoken = whereAmI(model, state);
  assert.match(spoken, /^On A Street\. Next, in 0\.4 miles: left onto B Street\. 0\.4 miles to stop 1\. 1 mile to the end\.$/);
  const shown = whereAmI(model, state, true);
  assert.match(shown, /0\.4 mi \(0\.6 km\) to stop 1/);
});

test("whereAmI off route: the way back, its distance and direction", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 300).state;
  for (let i = 0; i < 12; i += 1) s = step(model, s, fix(at(300, 60)), "full").state;
  assert.equal(whereAmI(model, s), "Off the planned route. The route is 200 feet to the south.");
  const back = wayBack(model, s);
  assert.equal(back?.direction, "south");
});

test("compassWord", () => {
  assert.equal(compassWord(at(0, 0), at(0, 100)), "north");
  assert.equal(compassWord(at(0, 0), at(100, 100)), "northeast");
  assert.equal(compassWord(at(0, 0), at(-100, 0)), "west");
});

test("nextAction: the turn, then the crossing, then the end", () => {
  const model = rideModel(lRoute());
  assert.equal(nextAction(model, 0)?.kind, "turn");
  assert.equal(nextAction(model, 1100)?.kind, "hazard");
  assert.equal(nextAction(model, 1600)?.kind, "end");
});

test("replanPoints: here, the stops not passed, the end; a loop goes back to its start", () => {
  const model = rideModel(twoLegs());
  const plan: LonLat[] = [at(0, 0), at(1000, 0), at(1000, 1000)];
  const here = at(400, 80);
  assert.deepEqual(replanPoints(model, 400, here, plan, false), [here, plan[1], plan[2]]);
  assert.deepEqual(replanPoints(model, 1300, here, plan, false), [here, plan[2]]);
  // A loop of a start and two stops: its end is its start.
  const loopPlan: LonLat[] = [at(0, 0), at(1000, 0), at(1000, 1000)];
  assert.deepEqual(replanPoints(model, 400, here, loopPlan, true), [here, loopPlan[1], loopPlan[2], loopPlan[0]]);
});

test("ReplanGate: one in flight, 30 s apart, 2 min after two failures, online lifts the gap", () => {
  const gate = new ReplanGate();
  assert.equal(gate.begin(0), true);
  assert.equal(gate.begin(1), false, "one in flight");
  gate.finish(false);
  assert.equal(gate.begin(REPLAN_GAP_MS - 1), false);
  assert.equal(gate.begin(REPLAN_GAP_MS), true);
  gate.finish(false);
  assert.equal(gate.begin(2 * REPLAN_GAP_MS), false, "two failures: the backoff");
  assert.equal(gate.begin(REPLAN_GAP_MS + REPLAN_BACKOFF_MS), true);
  gate.finish(true);
  gate.online();
  assert.equal(gate.begin(REPLAN_GAP_MS + REPLAN_BACKOFF_MS + 1), true, "online: no wait");
});

test("a loop's start is not its end: arrival comes only at the end of the line", () => {
  const coordinates = [at(0, 0), at(500, 0), at(500, 500), at(0, 500), at(0, 0)];
  const route = { ...lRoute(), geometry: { type: "LineString" as const, coordinates }, distance_m: 2000, leg_ends: [4], description: [] };
  const model = rideModel(route);
  const first = ride(model, "full", 0, 50);
  assert.equal(first.state.arrived, false);
  assert.ok((first.state.progressM ?? 99) < 60);
  const all = ride(model, "full", 55, 2000, 5, first.state);
  assert.equal(all.state.arrived, true);
});

test("privacy: the engine reads no storage and calls no network", () => {
  const source = readFileSync(new URL("./navigate.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /localStorage|sessionStorage|indexedDB|fetch\(|segment-info|\/api\/reverse/);
});

/** A route of `coordinates` with no description but the end. */
function bare(coordinates: LonLat[]): RideModel {
  return rideModel({ ...lRoute(), geometry: { type: "LineString", coordinates }, leg_ends: [coordinates.length - 1], description: [] });
}

test("out-and-back on one street (or a lane 10 m over): the way back is followed and arrives", () => {
  for (const gap of [0, 10]) {
    const model = bare([at(0, 0), at(1000, 0), at(1000, gap), at(0, gap)]);
    const r = ride(model, "full", 0, model.lengthM);
    assert.equal(r.state.arrived, true, `gap ${gap}`);
    assert.ok((r.state.progressM ?? 0) > model.lengthM - 25, `gap ${gap}: ${r.state.progressM}`);
  }
});

test("a figure eight: through the crossing, progress stays on the pass being ridden", () => {
  // East 600 m, a square north and back down through the first leg's middle, then on south.
  const model = bare([at(0, 0), at(600, 0), at(600, 300), at(300, 300), at(300, -300)]);
  const first = ride(model, "full", 0, 300).state;
  assert.ok(Math.abs((first.progressM ?? 0) - 300) < 6, `${first.progressM}`);
  // The second pass of the crossing is at 600 + 300 + 300 + 300 = 1,500 m: well ahead of the window.
  const second = ride(model, "full", 305, 1600, 5, first).state;
  assert.ok(Math.abs((second.progressM ?? 0) - 1600) < 6, `${second.progressM}`);
});

test("a gap in the fixes (a tunnel): the window grows, progress carries on", () => {
  const model = rideModel(lRoute());
  const s = ride(model, "full", 0, 200).state;
  // 20 s without a fix, then 400 m on: past the usual 250 m window.
  const out = step(model, s, fix(pointAt(model, 600), { at: (clock += 20_000) }), "full");
  assert.ok(Math.abs((out.state.progressM ?? 0) - 600) < 2, `${out.state.progressM}`);
  assert.equal(out.state.off, false);
});

test("off route, then rejoining far ahead: back on there, the cues carry on, and it arrives", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 300).state;
  // 200 m north of A Street, east, then back onto B Street at 1,200 m.
  for (let east = 300; east <= 900; east += 10) s = step(model, s, fix(at(east, 200)), "full", false).state;
  assert.equal(s.off, true);
  assert.ok(Math.abs((s.progressM ?? 0) - 300) < 0.01, "progress waits while off route");
  // Far ahead: back on after three fixes riding along B Street, not on the first.
  let back = step(model, s, fix(at(1000, 200)), "full", false);
  assert.equal(back.state.off, true, "one fix on the line far ahead is not yet back");
  back = step(model, back.state, fix(at(1000, 205)), "full", false);
  back = step(model, back.state, fix(at(1000, 210)), "full", false);
  assert.equal(back.state.off, false);
  assert.ok(Math.abs((back.state.progressM ?? 0) - 1210) < 2, `${back.state.progressM}`);
  const rest = ride(model, "full", 1215, 2000, 5, back.state);
  assert.equal(rest.state.arrived, true);
  assert.ok(rest.events.some((e) => e.cue?.kind === "hazard"), "the red crossing at 1,500 m is still said");
});

test("a loop: a first fix near the start but nearer the return leg starts at the start", () => {
  // A square loop back from the north; the rider is 18 m north of the start, 2 m off the return leg.
  const model = bare([at(0, 0), at(500, 0), at(500, 500), at(2, 500), at(2, 0), at(0, 0)]);
  const out = step(model, startState(), fix(at(0, 18)), "full");
  assert.equal(out.state.arrived, false);
  assert.ok((out.state.progressM ?? 99) < 30, `${out.state.progressM}`);
});

test("off route edges: 3 fixes over exactly 8 s are off; 2 fixes or 7.9 s are not", () => {
  const model = rideModel(lRoute());
  const base = ride(model, "full", 0, 300).state;
  const far = (s: RideState, t: number) => step(model, s, { point: at(300, 60), accuracyM: 5, speedMs: 5, headingDeg: null, at: t }, "full").state;
  const t0 = clock + 1000;
  clock += 20_000;
  assert.equal(far(far(far(base, t0), t0 + 4000), t0 + 8000).off, true);
  assert.equal(far(far(base, t0), t0 + 10_000).off, false);
  assert.equal(far(far(far(base, t0), t0 + 4000), t0 + 7900).off, false);
});

test("back on route: within half the threshold clears (14 m of 30), outside it does not (16 m)", () => {
  const model = rideModel(lRoute());
  let s = ride(model, "full", 0, 300).state;
  for (let i = 0; i < 12; i += 1) s = step(model, s, fix(at(300, 60)), "full").state;
  assert.equal(step(model, s, fix(at(300, 16)), "full").state.off, true);
  const back = step(model, s, fix(at(300, 14)), "full");
  assert.equal(back.state.off, false);
  assert.equal(back.events[0].urgent, false, "back on route is polite");
});

test("off and back at the quiet level: nothing said, the state still kept; stoker hears only the leaving", () => {
  for (const [level, said] of [
    ["quiet", []],
    ["stoker", [OFF_ROUTE_SAID]],
  ] as const) {
    const model = rideModel(lRoute());
    let s = ride(model, level, 0, 300).state;
    const events: RideEvent[] = [];
    for (let i = 0; i < 12; i += 1) {
      const out = step(model, s, fix(at(300, 60)), level);
      s = out.state;
      events.push(...out.events);
    }
    assert.equal(s.off, true, level);
    const back = step(model, s, fix(at(305, 2)), level);
    assert.equal(back.state.off, false, level);
    assert.deepEqual([...events, ...back.events].map((e) => e.spoken), said, level);
  }
});

test("at 10 m/s the cues move out with speed: advance about 270 m, prepare 100 m, now 20 m", () => {
  const model = rideModel(lRoute());
  let s = startState();
  s = { ...s, speedMs: 10 };
  const heard: { phase: string; progress: number }[] = [];
  for (let m = 0; m <= 1000; m += 5) {
    const out = step(model, s, fix(pointAt(model, m), { speedMs: 10, at: (clock += 500) }), "full");
    s = out.state;
    for (const e of out.events) if (e.cue?.kind === "turn") heard.push({ phase: e.phase ?? "", progress: m });
  }
  const where = (phase: string) => 1000 - (heard.find((h) => h.phase === phase)?.progress ?? -1);
  assert.ok(Math.abs(where("advance") - 270) <= 5, `advance ${where("advance")}`);
  assert.ok(Math.abs(where("prepare") - 100) <= 5, `prepare ${where("prepare")}`);
  assert.ok(Math.abs(where("now") - 20) <= 5, `now ${where("now")}`);
  // The stoker's warning at 10 m/s: 17 s, 170 m.
  let t = startState();
  t = { ...t, speedMs: 10 };
  let ahead = -1;
  for (let m = 0; m <= 1000 && ahead < 0; m += 5) {
    const out = step(model, t, fix(pointAt(model, m), { speedMs: 10, at: (clock += 500) }), "stoker");
    t = out.state;
    if (out.events.some((e) => e.phase === "ahead")) ahead = 1000 - m;
  }
  assert.ok(Math.abs(ahead - 170) <= 5, `ahead ${ahead}`);
});

test("arrival at a stop and the end is urgent; at most one sentence a fix", () => {
  const model = rideModel(twoLegs());
  let s = startState();
  for (let m = 0; m <= model.lengthM; m += 5) {
    const out = step(model, s, fix(pointAt(model, m)), "full");
    s = out.state;
    assert.ok(out.events.length <= 1, `${m}: ${out.events.map((e) => e.spoken)}`);
    for (const e of out.events) if (e.phase === "arrive") assert.equal(e.urgent, true, e.spoken);
  }
  assert.equal(s.arrived, true);
});

test("jitter back 50 m: progress goes back exactly the tolerance", () => {
  const model = rideModel(lRoute());
  const s = ride(model, "full", 0, 400).state;
  const out = step(model, s, fix(pointAt(model, 350)), "full");
  assert.ok(Math.abs((out.state.progressM ?? 0) - 370) < 0.01, `${out.state.progressM}`);
});

test("speech has no metric: a cue with metres, two brackets in one sentence", () => {
  assert.equal(withoutMetric("10 mph (about 16 km/h) for 1 mi (1.6 km)."), "10 mph for 1 mi.");
  const cue = { ...rideModel(lRoute()).cues[0], text: "Walk 300 ft (90 m) across the bridge." };
  assert.equal(cueSpoken(cue, "advance", 150), "In 500 feet, walk 300 ft across the bridge.");
});

test("measureMap: a stop off the uniform scale maps onto its vertex", () => {
  const along = new Float64Array([0, 500, 1000, 1500, 2000]);
  const map = measureMap(
    {
      distance_m: 2000,
      leg_ends: [1, 4],
      description: [stretch(0, 1000, "x"), { ...stretch(1000, 1000, "Stop 1."), kind: "via", via: 1 }, stretch(1000, 2000, "y")],
    },
    along,
  );
  assert.equal(map(1000), 500);
  assert.equal(map(500), 250);
});

test("ReplanGate: the numbers, a success resets the backoff, online in flight changes nothing", () => {
  assert.equal(REPLAN_GAP_MS, 30_000);
  assert.equal(REPLAN_BACKOFF_MS, 120_000);
  const gate = new ReplanGate();
  gate.begin(0);
  gate.finish(false);
  gate.begin(30_000);
  gate.finish(false);
  gate.begin(150_000);
  gate.finish(true);
  assert.equal(gate.begin(180_000), true, "after a success the gap is 30 s again");
  gate.online();
  gate.finish(true);
  assert.equal(gate.begin(180_001), false, "online while in flight did not lift the gap");
});

test("replanPoints: a stop already reached is dropped, matched by its number", () => {
  const model = rideModel(twoLegs());
  const plan: LonLat[] = [at(0, 0), at(1000, 0), at(1000, 1000)];
  const stopAt = model.cues.find((c) => c.kind === "stop")?.atM ?? 0;
  assert.deepEqual(replanPoints(model, stopAt - 10, at(0, 0), plan, false), [at(0, 0), plan[2]], "within 20 m of it");
});

test("goodFix: the last fix good enough for cues, what a re-plan starts from", () => {
  const model = rideModel(lRoute());
  const s = ride(model, "full", 0, 100).state;
  const out = step(model, s, fix(at(600, 300), { accuracyM: 400 }), "full");
  assert.deepEqual(out.state.goodFix, s.fix);
});

test("a detour that only crosses the route far ahead does not rejoin it, nor skip the stop between", () => {
  const model = rideModel(twoLegs());
  let s = ride(model, "full", 0, 300).state;
  for (let east = 300; east <= 900; east += 10) s = step(model, s, fix(at(east, 200)), "full", false).state;
  assert.equal(s.off, true);
  // East across B Street (the second leg, past stop 1 at 1,000 m) and on.
  const said: string[] = [];
  for (let east = 980; east <= 1100; east += 5) {
    const out = step(model, s, fix(at(east, 200)), "full", false);
    s = out.state;
    said.push(...out.events.map((e) => e.spoken));
  }
  assert.equal(s.off, true);
  assert.ok(Math.abs((s.progressM ?? 0) - 300) < 0.01, `${s.progressM}`);
  assert.deepEqual(said, []);
  assert.equal(replanPoints(model, s.progressM ?? 0, at(1100, 200), [at(0, 0), at(1000, 0), at(1000, 1000)], false).length, 3, "stop 1 still sent");
});

test("off route scales with a fix's accuracy: 60 m off is on route at 40 m accuracy, off at 5 m", () => {
  const model = rideModel(lRoute());
  for (const [accuracyM, off] of [
    [40, false],
    [5, true],
  ] as const) {
    let s = ride(model, "full", 0, 300).state;
    for (let i = 0; i < 12; i += 1) s = step(model, s, fix(at(300, 50), { accuracyM }), "full").state;
    assert.equal(s.off, off, `accuracy ${accuracyM}`);
  }
});

test("replanPoints with two stops: each matched by its number", () => {
  const coordinates = [at(0, 0), at(500, 0), at(1000, 0), at(1500, 0)];
  const description: DescriptionEntry[] = [
    stretch(0, 500, "a"),
    { ...stretch(500, 500, "Stop 1."), kind: "via", via: 1 },
    stretch(500, 1000, "b"),
    { ...stretch(1000, 1000, "Stop 2."), kind: "via", via: 2 },
    stretch(1000, 1500, "c"),
  ];
  const model = rideModel({ ...lRoute(), geometry: { type: "LineString", coordinates }, distance_m: 1500, leg_ends: [1, 2, 3], description });
  const plan: LonLat[] = [at(0, 0), at(500, 0), at(1000, 0), at(1500, 0)];
  assert.deepEqual(replanPoints(model, 700, at(700, 50), plan, false), [at(700, 50), plan[2], plan[3]]);
  assert.deepEqual(replanPoints(model, 100, at(100, 50), plan, false), [at(100, 50), plan[1], plan[2], plan[3]]);
});

test("a via point is no cue and no number, and a passed one is dropped from the re-plan (v0.7.0)", () => {
  const coordinates = [at(0, 0), at(500, 0), at(1000, 0), at(1500, 0)];
  const description: DescriptionEntry[] = [
    stretch(0, 500, "a"),
    { ...stretch(500, 500, "Stop 1."), kind: "via", via: 1 },
    stretch(500, 1000, "b"),
    { ...stretch(1000, 1000, "Stop 2."), kind: "via", via: 2 },
    stretch(1000, 1500, "c"),
  ];
  // Point 1 is a via point: only point 2 is a stop, and it is Stop 1.
  const model = rideModel({ ...lRoute(), geometry: { type: "LineString", coordinates }, distance_m: 1500, leg_ends: [1, 2, 3], description }, [1]);
  const stops = model.cues.filter((c) => c.kind === "stop");
  assert.deepEqual(stops.map((c) => [c.text, c.stop, c.point]), [["Stop 1.", 1, 2]]);
  assert.deepEqual(model.passes?.map((x) => [x.point, Math.round(x.atM)]), [[1, 500]]);
  const plan: LonLat[] = [at(0, 0), at(500, 0), at(1000, 0), at(1500, 0)];
  assert.deepEqual(replanPoints(model, 700, at(700, 50), plan, false), [at(700, 50), plan[2], plan[3]]);
  assert.deepEqual(replanPoints(model, 100, at(100, 50), plan, false), [at(100, 50), plan[1], plan[2], plan[3]]);
  assert.deepEqual(replanPoints(model, 1200, at(1200, 50), plan, false), [at(1200, 50), plan[3]]);
});

/** East 300 m on A Street, left onto the Capital Crescent Trail north for 2,700 m, crossing River Road at 2,500 m. */
function trailRoute(): RouteResponse {
  const description: DescriptionEntry[] = [
    stretch(0, 300, "0.0 to 0.2 mi (0.0 to 0.3 km): A Street, low stress (LTS 1).", { street: "A Street" }),
    stretch(300, 3000, "0.2 to 1.9 mi (0.3 to 3.0 km): Left onto Capital Crescent Trail, low stress (LTS 1), path.", {
      street: "Capital Crescent Trail",
      facility: "path",
      turn: { movement: "left", onto: "Capital Crescent Trail", control: null, severity: null },
    }),
    {
      ...stretch(2500, 2500, "At 1.6 mi (2.5 km): Cross River Road (LTS 3), no signal mapped (Higher stress junction)."),
      kind: "junction",
      street: "River Road",
      tier: null,
      severity: "orange",
      turn: { movement: "straight", onto: null, control: "none", severity: "orange" },
    },
  ];
  return { ...lRoute(), geometry: { type: "LineString", coordinates: [at(0, 0), at(300, 0), at(300, 1500), at(300, 2700)] }, distance_m: 3000, leg_ends: [3], description } as RouteResponse;
}

test("routeJunctions: each change of named street and each flagged crossing, from the route's own data", () => {
  const junctions = routeJunctions(rideModel(trailRoute()));
  assert.deepEqual(
    junctions.map((j) => [Math.round(j.atM), j.streets]),
    [
      [300, ["A Street", "Capital Crescent Trail"]],
      [2500, ["Capital Crescent Trail", "River Road"]],
    ],
  );
});

test("placeOnRoute: the nearest junction on a street; on a trail far from one, the trail marker (OWNER-DECISIONS 465)", () => {
  const model = rideModel(trailRoute());
  const onStreet = placeOnRoute(model, 100);
  assert.equal(onStreet?.kind, "junction");
  assert.deepEqual(onStreet?.kind === "junction" && onStreet.junction.streets, ["A Street", "Capital Crescent Trail"]);
  // Mid-trail, 1,000 m from the junction behind and 1,200 m from the one ahead: the trail, from where the route met it.
  const midTrail = placeOnRoute(model, 1300);
  assert.equal(midTrail?.kind, "trail");
  if (midTrail?.kind === "trail") {
    assert.equal(midTrail.trail, "Capital Crescent Trail");
    assert.equal(otherStreet(midTrail.junction, midTrail.trail), "A Street");
    assert.ok(Math.abs(midTrail.metres - 1000) < 3, `${midTrail.metres}`);
    assert.equal(midTrail.direction, "north");
  }
  // Within a quarter mile of a crossing: the crossing.
  const nearCrossing = placeOnRoute(model, 2400);
  assert.deepEqual(nearCrossing?.kind === "junction" && nearCrossing.junction.streets, ["Capital Crescent Trail", "River Road"]);
  // Past it by more than TRAIL_MARKER_M: measured from it.
  const past = placeOnRoute(model, 2500 + TRAIL_MARKER_M + 40);
  assert.ok(past?.kind === "trail" && otherStreet(past.junction, past.trail) === "River Road" && past.direction === "north", JSON.stringify(past));
});

test("whereAmI on a long trail says the trail marker, US units spoken and metric on screen", () => {
  const model = rideModel(trailRoute());
  const state = { ...startState(), progressM: 1300 };
  assert.match(whereAmI(model, state), /^On the Capital Crescent Trail, about 0\.6 miles north of A Street\. Next, in 0\.7 miles: busy crossing at River Road, no signal\./);
  assert.match(whereAmI(model, state, true), /^On the Capital Crescent Trail, about 0\.6 mi \(1\.0 km\) north of A Street\./);
  // On a street, as before.
  assert.match(whereAmI(model, { ...startState(), progressM: 100 }), /^On A Street\. /);
});

test("whereAmI on a long trail the mile file knows: its mile marker, posted or computed, in place of the junction (465)", () => {
  const model = rideModel(trailRoute());
  const state = { ...startState(), progressM: 1300 };
  // The trail's line from mile 0, a mile south of where the route meets it.
  const line = { n: "Capital Crescent Trail", s: 1609, l: [at(300, 0), at(300, 3000)] };
  const computed = parseTrailMiles({ trails: [line], markers: [] });
  assert.match(whereAmI(model, state, false, computed), /^On the Capital Crescent Trail, at about mile 1\.6\. Next, in 0\.7 miles: busy crossing at River Road, no signal\./);
  assert.match(whereAmI(model, state, true, computed), /^On the Capital Crescent Trail, at about mile 1\.6\. /);
  const [x, y] = at(300, 1050);
  const posted = parseTrailMiles({ trails: [line], markers: [{ id: "n1", x, y, t: "Capital Crescent Trail", m: 2 }] });
  assert.match(whereAmI(model, state, false, posted), /^On the Capital Crescent Trail, at mile marker 2\. /);
  // Near the crossing the crossing still names the place; on a street, the street; another trail's file, the junction.
  assert.match(whereAmI(model, { ...startState(), progressM: 2400 }, false, computed), /^On the Capital Crescent Trail\. /);
  assert.match(whereAmI(model, { ...startState(), progressM: 100 }, false, computed), /^On A Street\. /);
  const other = parseTrailMiles({ trails: [{ ...line, n: "Metropolitan Branch Trail" }], markers: [] });
  assert.match(whereAmI(model, state, false, other), /about 0\.6 miles north of A Street/);
});

/**
 * East 300 m on an unnamed path, left onto the Capital Crescent Trail north for 2,700 m, then an unnamed
 * path on to the end (the owner, 2026-10-12: "about 1.2 miles south of unnamed path").
 */
function unnamedPathRoute(): RouteResponse {
  const description: DescriptionEntry[] = [
    stretch(0, 300, "0.0 to 0.2 mi (0.0 to 0.3 km): unnamed path, low stress (LTS 1), path.", { street: "unnamed path", facility: "path" }),
    stretch(300, 3000, "0.2 to 1.9 mi (0.3 to 3.0 km): Left onto Capital Crescent Trail, low stress (LTS 1), path.", {
      street: "Capital Crescent Trail",
      facility: "path",
      turn: { movement: "left", onto: "Capital Crescent Trail", control: null, severity: null },
    }),
    stretch(3000, 6000, "1.9 to 3.7 mi (3.0 to 6.0 km): unnamed path, low stress (LTS 1), path.", { street: "unnamed path", facility: "path" }),
  ];
  return {
    ...lRoute(),
    geometry: { type: "LineString", coordinates: [at(0, 0), at(300, 0), at(300, 2700), at(300, 5700)] },
    distance_m: 6000,
    leg_ends: [3],
    description,
  } as RouteResponse;
}

test("whereAmI: an unnamed path is never a trail name nor a street to measure from", () => {
  const model = rideModel(unnamedPathRoute());
  // Its junctions have the trail as their named street; none is between two unnamed ways.
  for (const j of routeJunctions(model)) assert.ok(j.streets.includes("Capital Crescent Trail"), JSON.stringify(j));
  // Mid-trail: the only junctions are with unnamed paths, so no marker, just the trail.
  assert.deepEqual(placeOnRoute(model, 1600), { kind: "street", street: "Capital Crescent Trail" });
  assert.match(whereAmI(model, { ...startState(), progressM: 1600 }), /^On the Capital Crescent Trail\. /);
  // Far along the unnamed path: said plainly ("a path", the owner's word), no distance, no "unnamed".
  for (const progressM of [100, 5000]) {
    const said = whereAmI(model, { ...startState(), progressM });
    assert.match(said, /^On a path\. /);
    assert.doesNotMatch(said, /of unnamed|the unnamed|about/i);
  }
  assert.notEqual(placeOnRoute(model, 5000)?.kind, "trail");
});

test("whereAmI: the named trail marker still measures from a named street", () => {
  const route = unnamedPathRoute();
  // The route now joins the trail from A Street: the marker is back.
  route.description![0] = stretch(0, 300, "0.0 to 0.2 mi (0.0 to 0.3 km): A Street, low stress (LTS 1).", { street: "A Street" });
  const model = rideModel(route);
  assert.match(whereAmI(model, { ...startState(), progressM: 1300 }), /^On the Capital Crescent Trail, about 0\.6 miles north of A Street\. /);
  // Past the trail onto the unnamed path, far from A Street: plainly the path.
  assert.match(whereAmI(model, { ...startState(), progressM: 5000 }), /^On a path\. /);
});

test("whereAmI: the trail marker never measures from a junction off the trail", () => {
  // East 300 m on A Street, 700 m of unnamed path, then the Capital Crescent Trail for 3,000 m: the trail's
  // one junction is with the unnamed path, so there is nothing on it to measure from.
  const description: DescriptionEntry[] = [
    stretch(0, 300, "0.0 to 0.2 mi (0.0 to 0.3 km): A Street, low stress (LTS 1).", { street: "A Street" }),
    stretch(300, 1000, "0.2 to 0.6 mi (0.3 to 1.0 km): unnamed path, low stress (LTS 1), path.", { street: "unnamed path", facility: "path" }),
    stretch(1000, 4000, "0.6 to 2.5 mi (1.0 to 4.0 km): Capital Crescent Trail, low stress (LTS 1), path.", {
      street: "Capital Crescent Trail",
      facility: "path",
    }),
  ];
  const model = rideModel({
    ...lRoute(),
    geometry: { type: "LineString", coordinates: [at(0, 0), at(300, 0), at(300, 700), at(300, 3700)] },
    distance_m: 4000,
    leg_ends: [3],
    description,
  } as RouteResponse);
  assert.deepEqual(placeOnRoute(model, 2500), { kind: "street", street: "Capital Crescent Trail" });
  const said = whereAmI(model, { ...startState(), progressM: 2500 });
  assert.match(said, /^On the Capital Crescent Trail\. /);
  assert.doesNotMatch(said, /A Street|about/);
});

test("otherStreet: the trail's other street; off the trail, the named one whatever the order", () => {
  assert.equal(otherStreet({ atM: 0, streets: ["Capital Crescent Trail", "River Road"] }, "Capital Crescent Trail"), "River Road");
  assert.equal(otherStreet({ atM: 0, streets: ["River Road", "Capital Crescent Trail"] }, "Capital Crescent Trail"), "River Road");
  assert.equal(otherStreet({ atM: 0, streets: ["unnamed path", "A Street"] }, "Capital Crescent Trail"), "A Street");
  assert.equal(otherStreet({ atM: 0, streets: ["A Street", "unnamed path"] }, "Capital Crescent Trail"), "A Street");
});

test("wayRidden: a name as given, an unnamed way plainly, and nothing for an untraced one", () => {
  const way = (street: string | null, facility: string | null = null) => wayRidden({ fromM: 0, toM: 100, street, facility } as RideModel["stretches"][number]);
  assert.equal(way("R Street Northwest"), "R Street Northwest");
  assert.equal(way(null, "protected"), "a path");
  assert.equal(way(null, "path"), "a path");
  assert.equal(way(null), "an unnamed road");
  assert.equal(way("unnamed road", "protected"), "an unnamed road");
  assert.equal(way("unnamed path"), "a path", "an older API's word");
  assert.equal(way("path"), "a path");
  assert.equal(way("9th Street Northwest protected bike lane", "protected"), "9th Street Northwest protected bike lane");
  assert.equal(way("this part of the route"), null);
  assert.equal(wayRidden(null), null);
});

test("whereAmI on \"this part of the route\": On the route.", () => {
  const route = unnamedPathRoute();
  route.description![2] = stretch(3000, 6000, "1.9 to 3.7 mi (3.0 to 6.0 km): this part of the route, low stress (LTS 1).", { street: "this part of the route" });
  const model = rideModel(route);
  assert.match(whereAmI(model, { ...startState(), progressM: 5000 }), /^On the route\. /);
});

// ---- Go riding fixes (v0.7.0 plan, 2026-10-15): the turn and the street only; the arrival side ----

test("turn cues are the turn and the street only, never stress, LTS or junction words", () => {
  assert.equal(turnWords("left", "R Street Northwest"), "Left onto R Street Northwest.");
  assert.equal(turnWords("right", "9th Street Northwest protected bike lane"), "Right onto 9th Street Northwest protected bike lane.");
  assert.equal(turnWords("right", "path"), "Right onto the path.");
  assert.equal(turnWords("left", "unnamed path"), "Left onto the path.", "an older API's word");
  assert.equal(turnWords("left", "unnamed road"), "Left.");
  assert.equal(turnWords("left", null), "Left.");
  const model = rideModel(lRoute());
  const { events } = ride(model, "full", 0, 2000);
  const turns = events.filter((e) => e.cue?.kind === "turn");
  assert.ok(turns.length >= 3);
  for (const event of turns) {
    assert.doesNotMatch(event.spoken, /LTS|stress|signal|stop sign|junction/i, event.spoken);
    assert.doesNotMatch(event.cue!.text, /LTS|stress|signal|stop sign|junction/i, event.cue!.text);
  }
});

test("the last cue says which side the destination is on, from the router, and nothing when unknown", () => {
  assert.equal(arrivalSideWords("right"), "Destination on your right.");
  assert.equal(arrivalSideWords(null), "");
  assert.equal(arrivalSideWords(undefined), "");
  for (const side of ["left", "right"] as const) {
    const model = rideModel({ ...lRoute(), arrival_side: side });
    const end = model.cues[model.cues.length - 1];
    assert.equal(end.text, `The end of the route. Destination on your ${side}.`);
    const { events } = ride(model, "quiet", 0, 2000);
    assert.equal(events.at(-1)?.spoken, `You have arrived at the end of the route. Destination on your ${side}.`);
  }
  const unknown = rideModel({ ...lRoute(), arrival_side: null });
  assert.equal(unknown.cues.at(-1)?.text, "The end of the route.");
  assert.equal(cueSpoken(unknown.cues.at(-1)!, "arrive", 0), "You have arrived at the end of the route.");
});

test("a path with no name is unnamed; a bike lane named for its street is a name", () => {
  assert.equal(isUnnamed("path"), true);
  assert.equal(isUnnamed("unnamed path"), true);
  assert.equal(isUnnamed("9th Street Northwest bike lane"), false);
  assert.equal(isUnnamed("Capital Crescent Trail"), false);
});

test("weighFix: 12 s of only poor fixes says GPS is weak once; a good fix takes it down (review RIDE-3)", () => {
  assert.equal(GPS_WEAK_MS, 12_000);
  assert.equal(GPS_WEAK_SAID, "GPS is weak: turn cues paused.");
  let s = weighFix({ goodAt: 0, weak: false }, 5, 1000);
  assert.deepEqual(s, { goodAt: 1000, weak: false, sayNow: false });
  s = weighFix(s, 80, 12_999);
  assert.equal(s.weak, false, "under 12 s since the good one");
  s = weighFix(s, 80, 13_000);
  assert.deepEqual(s, { goodAt: 1000, weak: true, sayNow: true });
  s = weighFix(s, 120, 20_000);
  assert.deepEqual(s, { goodAt: 1000, weak: true, sayNow: false }, "said once");
  s = weighFix(s, 0, 21_000);
  assert.deepEqual(s, { goodAt: 21_000, weak: false, sayNow: false }, "a fix with no accuracy counts as good, as step's does");
  // Exactly POOR_FIX_M is good, as in step.
  assert.equal(weighFix({ goodAt: 0, weak: true }, 50, 99_000).weak, false);
});

test("cueSheetAfterMs: the list after a minute, or the time to the next turn when that is longer (RIDE-3, owner)", () => {
  const model = rideModel(lRoute()); // the turn at 1,000 m; the route's pace 5 m/s
  assert.equal(CUE_SHEET_MIN_MS, 60_000);
  assert.equal(cueSheetAfterMs(model, 900, 5), 60_000, "100 m at 5 m/s is 20 s: the minute floor");
  assert.ok(Math.abs(cueSheetAfterMs(model, 0, 2) - 500_000) < 1000, "1,000 m at 2 m/s: 500 s");
  assert.ok(Math.abs(cueSheetAfterMs(model, 0, 0) - 200_000) < 1000, "stopped: the route's pace");
  assert.equal(cueSheetAfterMs(model, 1500, 5), 60_000, "no turn ahead: the floor");
});

test("cueSheetShown: from the weak note on, once the wait is over; a good fix goes back to the card", () => {
  const after = 60_000;
  let s = weighFix({ goodAt: 0, weak: false }, 5, 0);
  s = weighFix(s, 80, 12_000);
  assert.equal(s.weak, true);
  assert.equal(cueSheetShown(s, 12_000, after), false, "the note first, the list later");
  s = weighFix(s, 80, 59_999);
  assert.equal(cueSheetShown(s, 59_999, after), false);
  s = weighFix(s, 80, 60_000);
  assert.equal(cueSheetShown(s, 60_000, after), true);
  // A longer next-turn time holds it back.
  assert.equal(cueSheetShown(s, 60_000, 200_000), false);
  assert.equal(cueSheetShown(s, 200_000, 200_000), true);
  // A good fix: back to turn by turn.
  s = weighFix(s, 5, 61_000);
  assert.equal(cueSheetShown(s, 61_000, after), false);
  // No fixes at all after it (the timer asks): the list a minute on as well.
  assert.equal(cueSheetShown(s, 61_000 + 59_999, after), false);
  assert.equal(cueSheetShown(s, 61_000 + 60_000, after), true);
  assert.ok(CUE_SHEET_CHECK_MS <= 5000, "asked every few seconds");
});

test("cueSheet: the turns, stops and end ahead in order, the next first, each distance from the one before", () => {
  const model = rideModel(twoLegs()); // stop 1 at 1,000 m, then left onto B Street, the end at 2,000 m
  const rows = cueSheet(model, 400);
  assert.deepEqual(
    rows.map((r) => r.text),
    model.cues.filter((c) => c.atM > 401 && ["turn", "stop", "end"].includes(c.kind)).map((c) => c.text),
  );
  assert.match(rows[0].distance, /^In 0\.4 mi \(0\.6 km\)$/);
  assert.ok(rows.slice(1).every((r) => r.distance.startsWith("Then in ")));
  assert.ok(rows.length <= CUE_SHEET_ROWS);
  assert.deepEqual(cueSheet(model, model.lengthM), []);
});

/** A straight line east as long as `description`, for the "onto" cue (the owner, 2026-10-16: Custis Trail to the Mount Vernon Trail). */
function straightRoute(description: DescriptionEntry[]): RouteResponse {
  const end = Math.max(...description.map((e) => e.to_m));
  return { ...lRoute(), geometry: { type: "LineString", coordinates: [at(0, 0), at(end, 0)] }, distance_m: end, leg_ends: [1], description } as RouteResponse;
}

const straightOnto = (street: string) => ({ movement: "straight" as const, onto: street, control: null, severity: null });

test("onto: the Custis Trail straight on to the Mount Vernon Trail is said at the Full level (not Stoker or Quiet), on the card and in Where am I?", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1500, "0.0 to 0.9 mi: Custis Trail, traffic-free path.", { street: "Custis Trail", facility: "path" }),
      stretch(1500, 9000, "0.9 to 5.6 mi: Continue onto Mount Vernon Trail, traffic-free path.", {
        street: "Mount Vernon Trail",
        facility: "path",
        turn: straightOnto("Mount Vernon Trail"),
      }),
    ]),
  );
  const onto = model.cues.filter((c) => c.kind === "onto");
  assert.equal(onto.length, 1);
  assert.equal(onto[0].text, "Continue onto Mount Vernon Trail.");
  assert.equal(onto[0].movement, null);
  assert.ok(says("full", onto[0]) && !says("stoker", onto[0]) && !says("quiet", onto[0]));
  assert.equal(nextAction(model, 200)?.kind, "onto");
  assert.match(whereAmI(model, { ...startState(), progressM: 1000 }), /Next, in [^:]+: continue onto Mount Vernon Trail\./);
  assert.equal(cueSpoken(onto[0], "advance", 152.4), `In ${spokenDistance(152.4)}, continue onto Mount Vernon Trail.`);
  assert.equal(ride(model, "full", 0, 2000).events.filter((e) => e.cue?.kind === "onto").length, 1);
  assert.equal(ride(model, "stoker", 0, 2000).events.filter((e) => e.cue?.kind === "onto").length, 0);
  assert.equal(ride(model, "quiet", 0, 2000).events.filter((e) => e.cue?.kind === "onto").length, 0);
});

test("onto: through a short unnamed connector to a new trail it is said once; the same trail resuming is not said", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1500, "Custis Trail.", { street: "Custis Trail", facility: "path" }),
      stretch(1500, 1600, "Continue onto the path.", { street: "path", facility: "path", turn: straightOnto("path") }),
      stretch(1600, 9000, "Continue onto Mount Vernon Trail.", { street: "Mount Vernon Trail", facility: "path", turn: straightOnto("Mount Vernon Trail") }),
    ]),
  );
  assert.deepEqual(model.cues.filter((c) => c.kind === "onto").map((c) => c.text), ["Continue onto Mount Vernon Trail."]);
  const resumed = rideModel(
    straightRoute([
      stretch(0, 1500, "Custis Trail.", { street: "Custis Trail", facility: "path" }),
      stretch(1500, 1590, "Continue onto the path.", { street: "path", facility: "path", turn: straightOnto("path") }),
      stretch(1590, 4000, "Continue onto Custis Trail.", { street: "Custis Trail", facility: "path", turn: straightOnto("Custis Trail") }),
    ]),
  );
  assert.equal(resumed.cues.filter((c) => c.kind === "onto").length, 0);
});

test("onto: an unnamed path straight on to a named trail is said; a named trail to an unnamed path is not", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 500, "path.", { street: "path", facility: "path" }),
      stretch(500, 3000, "Continue onto Capital Crescent Trail.", { street: "Capital Crescent Trail", facility: "path", turn: straightOnto("Capital Crescent Trail") }),
      stretch(3000, 5000, "Continue onto the path.", { street: "path", facility: "path", turn: straightOnto("path") }),
    ]),
  );
  const onto = model.cues.filter((c) => c.kind === "onto");
  assert.deepEqual(onto.map((c) => c.text), ["Continue onto Capital Crescent Trail."]);
  assert.ok(Math.abs(onto[0].atM - 500) < 1, `${onto[0].atM}`);
});

test("onto: a road's new name straight on is said only when it lasts more than a quarter mile; the same name never", () => {
  const roads = rideModel(
    straightRoute([
      stretch(0, 1000, "A Street.", { street: "A Street" }),
      stretch(1000, 1300, "Continue onto B Street.", { street: "B Street", turn: straightOnto("B Street") }),
      stretch(1300, 2000, "Continue onto C Street.", { street: "C Street", turn: straightOnto("C Street") }),
    ]),
  );
  assert.deepEqual(roads.cues.filter((c) => c.kind === "onto").map((c) => c.text), ["Continue onto C Street."]);
  const same = rideModel(straightRoute([stretch(0, 1000, "A Street.", { street: "A Street" }), stretch(1000, 3000, "Continue on A Street.", { street: "A Street", tier: 2 })]));
  assert.equal(same.cues.filter((c) => c.kind === "onto").length, 0);
});

test("planAfterEnd: part way, the plan starts at the last good fix with the stops passed dropped; else as it was", () => {
  const model = rideModel(twoLegs());
  const plan: LonLat[] = [at(0, 0), at(1000, 0), at(1500, 0)];
  const here = at(1200, 10);
  const now = 1_000_000;
  const fixAt = (point: LonLat, at: number): RideFix => ({ point, accuracyM: 5, speedMs: 5, headingDeg: null, at });
  // Past stop 1: from here to the finish.
  assert.deepEqual(planAfterEnd(model, { progressM: 1200, goodFix: fixAt(here, now - 5000), arrived: false }, plan, false, now), { points: [here, plan[2]] });
  // Before stop 1: it is kept.
  assert.deepEqual(planAfterEnd(model, { progressM: 500, goodFix: fixAt(at(500, 0), now), arrived: false }, plan, false, now), { points: [at(500, 0), plan[1], plan[2]] });
  // A loop's finish stays its start.
  assert.deepEqual(planAfterEnd(model, { progressM: 1200, goodFix: fixAt(here, now), arrived: false }, plan, true, now), { points: [here, plan[2], plan[0]] });
  // Part way with no recent fix: the plan keeps its start, and says so.
  assert.equal(planAfterEnd(model, { progressM: 1200, goodFix: fixAt(here, now - END_FIX_MAX_AGE_MS - 1), arrived: false }, plan, false, now), "no-fix");
  assert.equal(planAfterEnd(model, { progressM: 1200, goodFix: null, arrived: false }, plan, false, now), "no-fix");
  // At the start, at the end, or arrived: the plan as it was.
  assert.equal(planAfterEnd(model, { progressM: END_PART_WAY_M - 1, goodFix: fixAt(here, now), arrived: false }, plan, false, now), null);
  assert.equal(planAfterEnd(model, { progressM: null, goodFix: null, arrived: false }, plan, false, now), null);
  assert.equal(planAfterEnd(model, { progressM: model.lengthM - END_LEFT_MIN_M + 1, goodFix: fixAt(here, now), arrived: false }, plan, false, now), null);
  // Under a tenth of a long route left (a loop must not shrink to a stub): as it was, though more than 400 m is left.
  const long = rideModel(straightRoute([stretch(0, 10_000, "A Street.", { street: "A Street" })]));
  const loopPlan: LonLat[] = [at(0, 0)];
  const near = at(9500, 0);
  assert.equal(planAfterEnd(long, { progressM: 9500, goodFix: fixAt(near, now), arrived: false }, loopPlan, true, now), null);
  assert.ok(END_LEFT_MIN_SHARE * long.lengthM > END_LEFT_MIN_M);
  assert.deepEqual(planAfterEnd(long, { progressM: 8900, goodFix: fixAt(at(8900, 0), now), arrived: false }, loopPlan, true, now), { points: [at(8900, 0), loopPlan[0]] });
  assert.equal(planAfterEnd(model, { progressM: 1200, goodFix: fixAt(here, now), arrived: true }, plan, false, now), null);
});

test("onto: a new trail name under about 1,000 ft is not said, and A then a short B then A again is a resume", () => {
  const short = rideModel(
    straightRoute([
      stretch(0, 1500, "Custis Trail.", { street: "Custis Trail", facility: "path" }),
      stretch(1500, 1500 + ONTO_TRAIL_MIN_M - 1, "Continue onto Bridge Path.", { street: "Bridge Path", facility: "path", turn: straightOnto("Bridge Path") }),
      stretch(1500 + ONTO_TRAIL_MIN_M - 1, 5000, "Continue onto Custis Trail.", { street: "Custis Trail", facility: "path", turn: straightOnto("Custis Trail") }),
    ]),
  );
  assert.equal(short.cues.filter((c) => c.kind === "onto").length, 0);
  // At least that long, the new trail is said, and the old one resuming after it is said again.
  const long = rideModel(
    straightRoute([
      stretch(0, 1500, "Custis Trail.", { street: "Custis Trail", facility: "path" }),
      stretch(1500, 1500 + ONTO_TRAIL_MIN_M, "Continue onto Bridge Path.", { street: "Bridge Path", facility: "path", turn: straightOnto("Bridge Path") }),
      stretch(1500 + ONTO_TRAIL_MIN_M, 5000, "Continue onto Custis Trail.", { street: "Custis Trail", facility: "path", turn: straightOnto("Custis Trail") }),
    ]),
  );
  assert.deepEqual(long.cues.filter((c) => c.kind === "onto").map((c) => c.text), ["Continue onto Bridge Path.", "Continue onto Custis Trail."]);
});

test("onto: a name that is the other with more after it is not a new way", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1000, "9th Street Northwest.", { street: "9th Street Northwest" }),
      stretch(1000, 3000, "Continue onto 9th Street Northwest protected bike lane.", {
        street: "9th Street Northwest protected bike lane",
        facility: "path",
        turn: straightOnto("9th Street Northwest protected bike lane"),
      }),
      stretch(3000, 5000, "Continue onto 9th Street Northwest.", { street: "9th Street Northwest", turn: straightOnto("9th Street Northwest") }),
    ]),
  );
  assert.equal(model.cues.filter((c) => c.kind === "onto").length, 0);
});

test("onto: a name only from the trail's route relation is never a Continue onto cue", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1500, "Custis Trail.", { street: "Custis Trail", facility: "path" }),
      stretch(1500, 9000, "Continue onto Mount Vernon Trail.", {
        street: "Mount Vernon Trail",
        facility: "path",
        relation_name: true,
        turn: straightOnto("Mount Vernon Trail"),
      }),
    ]),
  );
  assert.equal(model.cues.filter((c) => c.kind === "onto").length, 0);
});

/** A turn entry's `turn`, for the bear and jog cues (the owner, 2026-10-16, on Q Street NW: "complex turns which aren't announced"). */
const turning = (movement: "left" | "right" | "bear_left" | "bear_right", street: string) => ({ movement, onto: street, control: null, severity: null });

test("bear: a bear right off Q Street onto a diagonal is a turn cue, said at Full and Stoker, not Quiet", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 2200, "Bear right onto Rhode Island Avenue Northwest.", { street: "Rhode Island Avenue Northwest", turn: turning("bear_right", "Rhode Island Avenue Northwest") }),
    ]),
  );
  const turn = model.cues[0];
  assert.equal(turn.kind, "turn");
  assert.equal(turn.movement, "bear_right");
  assert.equal(turn.text, "Bear right onto Rhode Island Avenue Northwest.");
  assert.ok(says("full", turn) && says("stoker", turn) && !says("quiet", turn));
  assert.equal(cueSpoken(turn, "now", 0), "Bear right now onto Rhode Island Avenue Northwest.");
  assert.equal(turnWords("bear_left", null), "Bear left.");
  const spoken = ride(model, "stoker", 0, 1000).events.filter((e) => e.cue?.kind === "turn").map((e) => e.phase);
  assert.deepEqual(spoken, ["ahead", "now"]);
  assert.equal(ride(model, "quiet", 0, 1000).events.filter((e) => e.cue?.kind === "turn").length, 0);
});

test("jog: a right then a bear left 30 m on is one cue, said early for both; the second is kept for the card but not said again", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 930, "Right onto 6th Street Northwest.", { street: "6th Street Northwest", turn: turning("right", "6th Street Northwest") }),
      stretch(930, 2200, "Bear left onto Rhode Island Avenue Northwest.", { street: "Rhode Island Avenue Northwest", turn: turning("bear_left", "Rhode Island Avenue Northwest") }),
    ]),
  );
  const [first, second] = model.cues;
  assert.equal(first.text, "Right onto 6th Street Northwest, then immediately bear left onto Rhode Island Avenue Northwest.");
  assert.equal(cueSpoken(first, "now", 0), "Right now, then bear left onto Rhode Island Avenue Northwest.");
  assert.equal(
    cueSpoken(first, "advance", 152.4),
    `In ${spokenDistance(152.4)}, right onto 6th Street Northwest, then immediately bear left onto Rhode Island Avenue Northwest.`,
  );
  assert.ok(second.joined && second.movement === "bear_left");
  assert.equal(nextAction(model, 910)?.index, second.index);
  for (const level of ["full", "stoker"] as const) {
    const said = ride(model, level, 0, 1200).events.filter((e) => e.cue?.kind === "turn");
    assert.ok(said.length >= 2, level);
    assert.ok(
      said.every((e) => e.cue?.index === first.index),
      level,
    );
  }
  // Turns farther apart than JOG_M are each their own.
  const apart = rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 900 + JOG_M + 20, "Right onto 6th Street Northwest.", { street: "6th Street Northwest", turn: turning("right", "6th Street Northwest") }),
      stretch(900 + JOG_M + 20, 2200, "Left onto R Street Northwest.", { street: "R Street Northwest", turn: turning("left", "R Street Northwest") }),
    ]),
  );
  assert.deepEqual(
    apart.cues.filter((c) => c.kind === "turn").map((c) => [c.text, !!c.joined]),
    [
      ["Right onto 6th Street Northwest.", false],
      ["Left onto R Street Northwest.", false],
    ],
  );
});

test("bear: a curving road that keeps its name says nothing", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Beach Drive.", { street: "Beach Drive" }),
      stretch(900, 2200, "Continue on Beach Drive.", { street: "Beach Drive", tier: 2 }),
    ]),
  );
  assert.deepEqual(
    model.cues.map((c) => c.kind),
    ["end"],
  );
});

/** Q Street's jog: a right onto 6th Street at 900 m, a bear left onto Rhode Island Avenue 30 m on. */
function qStreetJog(): RideModel {
  return rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 930, "Right onto 6th Street Northwest.", { street: "6th Street Northwest", turn: turning("right", "6th Street Northwest") }),
      stretch(930, 2200, "Bear left onto Rhode Island Avenue Northwest.", { street: "Rhode Island Avenue Northwest", turn: turning("bear_left", "Rhode Island Avenue Northwest") }),
    ]),
  );
}

test('jog: the second turn says its own "now" where the first\'s was never said (a ride started, or a gap in the fixes, between the two)', () => {
  const model = qStreetJog();
  const second = model.cues[1];
  assert.ok(second.joined);
  for (const level of ["full", "stoker"] as const) {
    // Started (or rejoined) past the first turn.
    const started = ride(model, level, 912, 1000).events.filter((e) => e.cue?.kind === "turn");
    assert.deepEqual(
      started.map((e) => [e.cue?.index, e.phase, e.spoken]),
      [[second.index, "now", "Bear left now onto Rhode Island Avenue Northwest."]],
      level,
    );
    // A gap in the fixes over the first turn.
    const before = ride(model, level, 0, 880);
    const after = ride(model, level, 912, 1000, 5, before.state).events.filter((e) => e.cue?.kind === "turn");
    assert.deepEqual(
      after.map((e) => [e.cue?.index, e.phase]),
      [[second.index, "now"]],
      level,
    );
  }
  assert.equal(ride(model, "quiet", 912, 1000).events.filter((e) => e.cue?.kind === "turn").length, 0);
  // The cue sheet has no row for it: the first's row says it.
  assert.deepEqual(
    cueSheet(model, 0).map((r) => r.text),
    ["Right onto 6th Street Northwest, then immediately bear left onto Rhode Island Avenue Northwest.", "The end of the route."],
  );
});

test("jog: three turns in a row join the first two; the third is its own cue (pinned)", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "A Street.", { street: "A Street" }),
      stretch(900, 950, "Right onto B Street.", { street: "B Street", turn: turning("right", "B Street") }),
      stretch(950, 1000, "Left onto C Street.", { street: "C Street", turn: turning("left", "C Street") }),
      stretch(1000, 2200, "Right onto D Street.", { street: "D Street", turn: turning("right", "D Street") }),
    ]),
  );
  assert.deepEqual(
    model.cues.filter((c) => c.kind === "turn").map((c) => [c.text, !!c.joined]),
    [
      ["Right onto B Street, then immediately left onto C Street.", false],
      ["Left onto C Street.", true],
      ["Right onto D Street.", false],
    ],
  );
});

test("jog: a flagged junction between two close turns keeps them apart (pinned)", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "A Street.", { street: "A Street" }),
      stretch(900, 940, "Right onto B Street.", { street: "B Street", turn: turning("right", "B Street") }),
      { ...stretch(920, 920, "Crossing Big Avenue, higher stress junction."), kind: "junction", severity: "orange" },
      stretch(940, 2200, "Left onto C Street.", { street: "C Street", turn: turning("left", "C Street") }),
    ]),
  );
  assert.deepEqual(
    model.cues.filter((c) => c.kind !== "end").map((c) => [c.kind, c.text, !!c.joined]),
    [
      ["turn", "Right onto B Street.", false],
      ["hazard", "Crossing Big Avenue, higher stress junction.", false],
      ["turn", "Left onto C Street.", false],
    ],
  );
});

test("a fork along one trail is a turn cue to stay on it (the owner, 2026-10-18, Paint Branch Trail)", () => {
  assert.equal(turnWords("bear_right", "Paint Branch Trail", true), "Bear right to stay on Paint Branch Trail.");
  assert.equal(turnWords("left", "path", true), "Left to stay on the path.");
  const route = lRoute();
  route.description = [
    stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): Paint Branch Trail, traffic-free path.", { street: "Paint Branch Trail", facility: "path" }),
    stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Left to stay on Paint Branch Trail, traffic-free path.", {
      street: "Paint Branch Trail",
      facility: "path",
      turn: { movement: "left", onto: "Paint Branch Trail", control: null, severity: null, stay: true },
    }),
  ];
  const turns = rideModel(route).cues.filter((c) => c.kind === "turn");
  assert.deepEqual(
    turns.map((c) => [c.movement, c.text]),
    [["left", "Left to stay on Paint Branch Trail."]],
  );
});

test("a re-route that turns the rider round: judged from the line's first 25 m against the heading", () => {
  const east = lRoute().geometry.coordinates;
  assert.equal(setsOffBack(east, 270), true);
  assert.equal(setsOffBack(east, 90), false);
  // A turn is not a U-turn; no heading, no U-turn.
  assert.equal(setsOffBack(east, 180), false);
  assert.equal(setsOffBack(east, null), false);
  // The snap's metre of wiggle is read past.
  assert.equal(setsOffBack([at(0, 0), at(-1, 0), at(100, 0)], 270), true);
});

test("a U-turn re-route says it plainly: first on the card, said at once, then the turns as before", () => {
  assert.equal(REPLAN_UTURN, "New route found. Make a U-turn.");
  const model = withUTurn(rideModel(lRoute()));
  assert.equal(model.cues[0].text, UTURN_SAID);
  assert.equal(model.cues[0].movement, "uturn");
  assert.deepEqual(model.cues.map((c) => c.index), model.cues.map((_, i) => i));
  assert.equal(model.cues[1].text, "Left onto B Street.");
  const out = step(model, startState(), fix(at(0, 0)), "full");
  assert.ok(out.events.some((e) => e.spoken === "Make a U-turn now."), JSON.stringify(out.events.map((e) => e.spoken)));
  const { events } = ride(model, "full", 0, 1100, 20);
  assert.equal(events.filter((e) => e.spoken.includes("U-turn")).length, 1);
  assert.ok(events.some((e) => e.spoken === "Left now onto B Street."));
});

// ---- Service roads (the owner, 2026-10-20, on East-West Highway: "When going on a service road, especially next to a major road, say so") ----

test("service roads: a turn onto one says what it is and the road it runs beside", () => {
  assert.equal(turnWords("left", "service road beside East-West Highway"), "Left onto the service road beside East-West Highway.");
  assert.equal(turnWords("right", "service road"), "Right onto the service road.");
  assert.equal(turnWords("bear_left", "sidewalk beside East-West Highway"), "Bear left onto the sidewalk beside East-West Highway.");
  assert.equal(turnWords("left", "path beside East-West Highway"), "Left onto the path beside East-West Highway.");
  assert.equal(turnWords("right", "alley"), "Right onto the alley.");
  assert.equal(ontoWords("service road beside East-West Highway"), "Continue onto the service road beside East-West Highway.");
  assert.equal(wayWords("Spencer Road"), "Spencer Road");
  const cue = { index: 0, kind: "turn", atM: 100, text: "", movement: "left", street: "service road beside East-West Highway", severity: null, tier: 2, stop: null } as Cue;
  assert.equal(cueSpoken(cue, "now", 0), "Left now onto the service road beside East-West Highway.");
});

test("service roads: leaving the highway straight on for its service road is said, however short, and named in Where am I?", () => {
  const route = (highway: number, service: number) =>
    rideModel(
      straightRoute([
        stretch(0, 1500, "East-West Highway.", { street: "East-West Highway", tier: highway }),
        stretch(1500, 1800, "Continue onto the service road beside East-West Highway, fairly low stress (LTS 2).", {
          street: "service road beside East-West Highway",
          tier: service,
          turn: straightOnto("service road beside East-West Highway"),
        }),
        stretch(1800, 3000, "Continue onto East-West Highway.", { street: "East-West Highway", tier: highway, turn: straightOnto("East-West Highway") }),
      ]),
    );
  // At one level of stress: the onto cue, though the service road is far shorter than a quarter mile, and back
  // onto the highway after it.
  const level = route(2, 2);
  assert.deepEqual(
    level.cues.filter((c) => c.kind === "onto").map((c) => c.text),
    ["Continue onto the service road beside East-West Highway.", "Continue onto East-West Highway."],
  );
  assert.match(whereAmI(level, { ...startState(), progressM: 1600 }), /^On the service road beside East-West Highway/);
  // Off a busy highway: the calmer cue, which names it too.
  const calmer = route(4, 2).cues.find((c) => c.atM > 1400 && c.atM < 1600);
  assert.equal(calmer?.kind, "calmer");
  assert.match(calmer?.text ?? "", /^Continue onto the service road beside East-West Highway, /);
});
