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
  otherStreet,
  placeOnRoute,
  pointAt,
  routeJunctions,
  TRAIL_MARKER_M,
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
  assert.match(whereAmI(model, state), /^On the Capital Crescent Trail, about 0\.6 miles north of A Street\. Next, in 0\.7 miles: cross River Road/);
  assert.match(whereAmI(model, state, true), /^On the Capital Crescent Trail, about 0\.6 mi \(1\.0 km\) north of A Street\./);
  // On a street, as before.
  assert.match(whereAmI(model, { ...startState(), progressM: 100 }), /^On A Street\. /);
});
