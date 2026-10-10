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
  BACK_ON_ROUTE_SAID,
  OFF_ROUTE_KEPT_SAID,
  OFF_ROUTE_SAID,
  REPLAN_BACKOFF_MS,
  REPLAN_GAP_MS,
  ReplanGate,
  compassWord,
  cueSpoken,
  measureMap,
  nextAction,
  offThreshold,
  pointAt,
  replanPoints,
  rideModel,
  says,
  sentenceOf,
  snap,
  startState,
  step,
  toGo,
  wayBack,
  whereAmI,
  withoutMetric,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./navigate.ts";

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
  assert.equal(turn.text, "Left onto B Street at a signal, low stress (LTS 1).");
  assert.ok(Math.abs(turn.atM - 1000) < 2, `${turn.atM}`);
  assert.ok(Math.abs(model.lengthM - 2000) < 2);
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
  assert.match(turn[0].spoken, /^In \d+ feet, left onto B Street at a signal, low stress \(LTS 1\)\.$/);
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
  assert.match(events[2].spoken, /^In \d+ feet, cross C Street \(LTS 4\), no signal mapped \(Very high stress junction\)\.$/);
});

test("Quiet: nothing but arrival", () => {
  const model = rideModel(lRoute());
  const { events } = ride(model, "quiet", 0, 2000);
  assert.deepEqual(
    events.map((e) => e.phase),
    ["arrive"],
  );
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
  assert.match(spoken, /^On A Street\. Next, in 0\.4 miles: left onto B Street, busy road \(LTS 3\)\. 0\.4 miles to stop 1\. 1 mile to the end\.$/);
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
