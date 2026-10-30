// Ride mode's engine (WEB-NAV-plan.md sections 2-4): progress along the line, the cue schedule per
// level, off route with its hysteresis, the re-plan's points and gate, and the words.
import { test } from "node:test";
import { routeRequestBody } from "./api.ts";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { spokenDistance } from "./format.ts";
import { cueParts } from "./cueShown.ts";
import {
  CUE_SHEET_SHOWN,
  arrivedShown,
  cueShort,
  whereAmIShown,
  ADVANCE_MIN_M,
  END_FIX_MAX_AGE_MS,
  END_PART_WAY_M,
  END_LEFT_MIN_M,
  END_LEFT_MIN_SHARE,
  JOG_M,
  JOG_TURNS,
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
  REPLAN_MOVED_M,
  replanHeld,
  arrivalSideWords,
  compassWord,
  crossingWords,
  crossArrow,
  avoidWords,
  cueSpoken,
  exitWords,
  ordinal,
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
  cueWords,
  signalsCard,
  REPLAN_UTURN,
  REPLAN_FOUND,
  REPLAN_REJOIN,
  REPLAN_AHEAD,
  REPLAN_NO_AHEAD,
  UTURNS_BEFORE_AHEAD,
  UTURN_RECHECK_MS,
  UTURN_START,
  UTURN_TAKEN_M,
  keepsAhead,
  uturnAheadOnly,
  uturnStep,
  type UTurnEvent,
  type UTurnState,
  replanTold,
  says,
  setsOffBack,
  UTURN_SAID,
  withUTurn,
  isStartUTurn,
  sentenceOf,
  snap,
  startState,
  PASSED_M,
  step,
  secondsAt,
  secondsBetween,
  timelineOf,
  toGo,
  turnWords,
  wayBack,
  ontoWords,
  wayRidden,
  wayWords,
  whereAmI,
  withoutMetric,
  spokenText,
  stretchWords,
  walkWords,
  flaggedOntoWords,
  laneEndsWords,
  type Cue,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./navigate.ts";
import { parseTrailMiles } from "./trailMiles.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";

// Spanish's catalog is fetched on choosing it (lib/i18n.ts loadLanguage), as the app does before it starts.
await loadLanguage("es");

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

test("rideModel: a run of signals is a short card, Corkers on a Mass Ride; the voice keeps the sentence (the 2026-10-28 audit, P6)", () => {
  const route = lRoute();
  const sentence =
    "0.4 to 0.9 mi (0.6 to 1.4 km): 4 crossings with traffic signals (Scott Circle Northwest, M Street Northwest, K Street Northwest, and 1 more), 2 of them heavy-traffic roads (LTS 4) (Very high stress junctions).";
  const group: DescriptionEntry = {
    ...stretch(600, 1400, sentence),
    kind: "junction",
    tier: null,
    severity: "red",
    group: { number: 1, count: 4, lts4: 2, streets: ["Scott Circle Northwest", "M Street Northwest", "K Street Northwest"], more: 1 },
  };
  route.description = [...(route.description ?? []).slice(0, 1), group, ...(route.description ?? []).slice(1)];
  const cue = rideModel(route).cues.find((c) => c.source === "junction")!;
  assert.deepEqual(cue.card, {
    head: "4 signals ahead",
    rest: "Scott Cir, M St, K St +1 · 2 busy",
    said: "4 crossings with traffic signals (Scott Circle Northwest, M Street Northwest, K Street Northwest, and 1 more), 2 of them heavy-traffic roads (LTS 4; very high stress junctions).",
  });
  assert.doesNotMatch(cue.card!.said, /\)\s*\(/, "no two brackets in a row");
  // The voice is the API's sentence, as before.
  assert.equal(cueWords(cue, true), "4 crossings with traffic signals (Scott Circle Northwest, M Street Northwest, K Street Northwest, and 1 more), 2 of them heavy-traffic roads.");
  const mass = rideModel({ ...route, preset: "mass-ride" }).cues.find((c) => c.source === "junction")!;
  assert.equal(mass.card!.head, "Corkers: 4 signals ahead");
  // No busy road and none more: the streets alone.
  assert.equal(signalsCard({ number: 2, count: 2, lts4: 0, streets: ["A Street Southeast", "B Street"], more: 0 }, "2 crossings.", false).rest, "A St, B St");
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const cueShown = cue\?\.card \?\? cueParts\(/);
  assert.match(ride, /<span className="visually-hidden">\{cue\.card\?\.said \?\? cue\.rideText \?\? cue\.text\}<\/span>/);
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
  // Feet up to just under 1,000 ft, not tenths of a mile (routing audit D7).
  assert.equal(spokenDistance(229.5), "800 feet");
  assert.equal(spokenDistance(240), "800 feet");
  assert.equal(spokenDistance(170), "600 feet");
  assert.equal(spokenDistance(285), "900 feet");
  assert.equal(spokenDistance(290), "0.2 miles");
  assert.equal(spokenDistance(643.7), "0.4 miles");
  assert.equal(spokenDistance(1609.344), "1 mile");
  assert.equal(spokenDistance(3218.7), "2 miles");
  assert.equal(withoutMetric("Walk your bike here, for 300 ft (90 m)."), "Walk your bike here, for 300 ft.");
  assert.equal(withoutMetric("1.0 to 1.6 mi (1.6 to 2.6 km): 6 crossings"), "1.0 to 1.6 mi: 6 crossings");
  assert.equal(withoutMetric("low stress (LTS 1)."), "low stress (LTS 1).");
  // The server's Spanish (routemaker.lang_es).
  assert.equal(withoutMetric("1.0 a 1.6 mi (1.6 a 2.6 km): 6 cruces"), "1.0 a 1.6 mi: 6 cruces");
  assert.equal(withoutMetric("Camine con su bicicleta aquí, por 300 ft (90 m)."), "Camine con su bicicleta aquí, por 300 ft.");
});

test("spokenText: a group of crossings is said without its severity, which the screen keeps (D33)", () => {
  // The server's own shape (describe.group_sentence): "(LTS 4)" before the severity.
  const group =
    "1.0 to 1.2 mi (1.6 to 1.9 km): 2 crossings with traffic signals (A Street and B Street), 2 of them heavy-traffic roads (LTS 4) (Very high stress junctions).";
  assert.equal(spokenText(group), "1.0 to 1.2 mi: 2 crossings with traffic signals (A Street and B Street), 2 of them heavy-traffic roads.");
  assert.equal(
    spokenText("3 crossings with traffic signals (A Street, B Street and C Street), 1 of them a heavy-traffic road (LTS 4) (Very high stress junctions)."),
    "3 crossings with traffic signals (A Street, B Street and C Street), 1 of them a heavy-traffic road.",
  );
  assert.equal(
    spokenText("2 cruces con semáforo, todos ellos calles de tráfico pesado (LTS 4) (intersecciones de estrés muy alto)."),
    "2 cruces con semáforo, todos ellos calles de tráfico pesado.",
  );
  // Red with no heavy-traffic road (LTS 3.5): nothing else says how bad, so it stays.
  assert.equal(spokenText("2 crossings (Very high stress junctions)."), "2 crossings (Very high stress junctions).");
  // A higher stress group keeps its severity: nothing else in it says so.
  assert.equal(spokenText("2 crossings (Higher stress junctions)."), "2 crossings (Higher stress junctions).");
  assert.equal(spokenText("2 cruces (intersecciones de estrés más alto)."), "2 cruces (intersecciones de estrés más alto).");
  // One junction's own severity is not this change's.
  assert.equal(spokenText("Cross K Street (Very high stress junction)."), "Cross K Street (Very high stress junction).");
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

test("toGo from the route's time marks: a slow climb ahead and a junction wait where they are (Stephen 2026-10-26)", () => {
  // 2,000 m in 400 s: the first 900 m quick (90 s), a 15 s wait at a signal there, then 10 m/s to the stop at
  // 1,000 m (100 m, 10 s) and a climb to the end (1,000 m, 285 s).
  const route = { ...twoLegs(), time_marks: [[0, 0], [0.45, 90], [0.45, 105], [0.5, 115], [1, 400]] };
  const model = rideModel(route);
  const { state } = ride(model, "quiet", 0, 400);
  const togo = toGo(model, state.progressM ?? 0);
  const at = state.progressM ?? 0;
  // At 400 m: 40 s along. To the stop at 1,000 m, 60 s riding and its wait; to the end, the climb as well.
  assert.ok(Math.abs((togo.stop?.seconds ?? 0) - (115 - at / 10)) < 1, String(togo.stop?.seconds));
  assert.ok(Math.abs((togo.end.seconds ?? 0) - (400 - at / 10)) < 1, String(togo.end.seconds));
  // Evenly spread it would have been 120 s and 320 s.
  const even = toGo(rideModel(twoLegs()), at);
  assert.ok(Math.abs((even.end.seconds ?? 0) - (2000 - at) / 5) < 1);
});

test("timelineOf: scaled to the route's duration; out of order, empty or timeless marks are none", () => {
  const line = timelineOf([[0, 0], [0.5, 50], [1, 100]], 2000, 300);
  assert.deepEqual(line && [...line.m], [0, 1000, 2000]);
  assert.deepEqual(line && [...line.s], [0, 150, 300]);
  assert.equal(timelineOf([[0, 0], [0.6, 50], [0.5, 60]], 2000, 300), null);
  assert.equal(timelineOf([[0, 0], [1, 0]], 2000, 300), null);
  assert.equal(timelineOf(null, 2000, 300), null);
  assert.equal(timelineOf([[0, 0], [1, 10]], 2000, 0), null);
});

test("secondsAt: a wait counts once its place is reached; before the start and past the end, the ends", () => {
  const model = rideModel({ ...twoLegs(), time_marks: [[0, 0], [0.5, 100], [0.5, 115], [1, 400]] });
  assert.equal(secondsAt(model, -5), 0);
  assert.ok(Math.abs((secondsAt(model, model.lengthM / 2 - 1) ?? 0) - 99.9) < 0.2);
  assert.ok(Math.abs((secondsAt(model, model.lengthM / 2) ?? 0) - 115) < 1e-6);
  assert.equal(secondsAt(model, 5000), 400);
  assert.equal(secondsBetween(model, 1500, 500), 0);
});

test("whereAmI with an arrival clock: each to-go sentence ends with the clock time of the plan's seconds", () => {
  const model = rideModel(twoLegs());
  const { state } = ride(model, "quiet", 0, 400);
  const spoken = whereAmI(model, state, false, null, (s) => `${Math.round(s)} s`);
  assert.match(spoken, / 0\.4 miles to stop 1, arriving about 120 s\. 1 mile to the end, arriving about 320 s\.$/);
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

test("a re-plan hung past REPLAN_TIMEOUT_MS lets the gate go, and a late answer never frees a newer one", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /if \(ended\.current \|\| ticket !== replanTicket\.current\) return;\s*released = true;\s*gate\.finish\(false\);\s*setReplanning\(false\);/);
  assert.match(ride, /else if \(!released\) gate\.finish\(found !== null\);\s*\/\/[^\n]*\n\s*\/\/[^\n]*\n\s*else if \(found && !voided\(\) && !gate\.busy\) gate\.finish\(true\);/);
  // Told "No signal" once, at the timeout.
  assert.match(ride, /if \(!found\) \{\s*\/\/[^\n]*\n\s*if \(released\) return false;/);
});

test("after a new route, no automatic re-plan until the rider has moved 50 m or been on its line (review RIDE-6)", () => {
  const from = at(0, 0);
  assert.equal(REPLAN_MOVED_M, 50);
  assert.equal(replanHeld(from, at(30, 0)), true, "standing still in a car park");
  assert.equal(replanHeld(from, at(60, 0)), false);
  assert.equal(replanHeld(null, at(0, 0)), false, "on the line since");
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /plan\.current = \{ points, loop: false \};\s*replannedFrom\.current = here;/);
  assert.match(ride, /if \(!out\.state\.off && out\.state\.offCount === 0 && out\.state\.progressM !== null\) replannedFrom\.current = null;/);
  assert.match(ride, /out\.state\.goodFix && !replanHeld\(replannedFrom\.current, fix\.point\)\) \{/);
});

test("a polite cue carries its sentence from where the rider is when it is said (review RIDE-4)", () => {
  const model = rideModel(lRoute());
  const { events } = ride(model, "full", 0, 2000);
  const advance = events.find((e) => e.phase === "advance" && e.cue?.kind === "turn");
  assert.ok(advance?.respoken);
  const cue = advance.cue!;
  assert.equal(advance.respoken(cue.atM - 100), cueSpoken(cue, "advance", 100, true));
  assert.equal(advance.respoken(cue.atM), null, "at the turn: its now says it");
  assert.ok(events.filter((e) => e.urgent).every((e) => !e.respoken), "urgent cues are said at once");
  const src = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(src, /announcer\.current\?\.say\(event\.spoken, event\.urgent, event\.after, again\);/);
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

test("the stretch after a via point is read against the one before it; after a stop it starts afresh (audit D29)", () => {
  const coordinates = [at(0, 0), at(500, 0), at(1000, 0)];
  const description: DescriptionEntry[] = [
    stretch(0, 500, "a", { street: "A Street", tier: 1 }),
    { ...stretch(500, 500, "Via point at 0.3 mi (0.5 km)."), kind: "via", via: 1 },
    stretch(500, 1000, "b", { street: "Georgia Avenue", tier: 3 }),
  ];
  const route = { ...lRoute(), geometry: { type: "LineString" as const, coordinates }, distance_m: 1000, leg_ends: [1, 2], description };
  // Ridden through: the busy road ahead is said.
  assert.deepEqual(rideModel(route, [1]).cues.map((c) => c.kind), ["busy", "end"]);
  // A stop: the ride starts again there, as before.
  assert.deepEqual(rideModel(route).cues.map((c) => c.kind), ["stop", "end"]);
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

test("onto: one street's other side straight on is not a new way; North and South Avenue or Capitol are", () => {
  const onto = (a: string, b: string) =>
    rideModel(
      straightRoute([
        stretch(0, 1000, `${a}.`, { street: a }),
        stretch(1000, 3000, `Continue onto ${b}.`, { street: b, turn: straightOnto(b) }),
      ]),
    )
      .cues.filter((c) => c.kind === "onto")
      .map((c) => c.text);
  assert.deepEqual(onto("West Pratt Street", "East Pratt Street"), []);
  assert.deepEqual(onto("C Street Northwest", "C Street Northeast"), []);
  assert.deepEqual(onto("1st Street NW", "1st Street SW"), []);
  assert.deepEqual(onto("North Charles Street", "South Charles Street"), []);
  assert.deepEqual(onto("North Avenue", "South Avenue"), ["Continue onto South Avenue."]);
  assert.deepEqual(onto("North Capitol Street", "South Capitol Street"), ["Continue onto South Capitol Street."]);
  assert.deepEqual(onto("North Carolina Avenue Southeast", "South Carolina Avenue Southeast"), ["Continue onto South Carolina Avenue Southeast."]);
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

test("toward: a turn onto an unnamed path says the trail it leads to; the path stays unnamed", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1500, "Capital Crescent Trail.", { street: "Capital Crescent Trail", facility: "path" }),
      stretch(1500, 1650, "Right onto the path to Rock Creek Trail.", { street: "path", facility: "path", turn: { ...turning("right", "path"), toward: "Rock Creek Trail" } }),
      stretch(1650, 3000, "Left onto Rock Creek Trail.", { street: "Rock Creek Trail", facility: "path", turn: turning("left", "Rock Creek Trail") }),
    ]),
  );
  const [onto, next] = model.cues;
  assert.equal(onto.text, "Right onto the path to Rock Creek Trail.");
  assert.equal(onto.street, "path");
  assert.equal(onto.toward, "Rock Creek Trail");
  assert.equal(cueSpoken(onto, "now", 0), "Right now onto the path to Rock Creek Trail.");
  assert.equal(next.text, "Left onto Rock Creek Trail.");
  assert.equal(model.stretches[1].street, "path");
  // An older API's turn, with no `toward`: as before.
  assert.equal(turnWords("right", "path"), "Right onto the path.");
  assert.equal(turnWords("right", "path", false, null, "Rock Creek Trail"), "Right onto the path to Rock Creek Trail.");
  // Only a path with no name is said so.
  assert.equal(turnWords("right", "Bridge Path", false, null, "Rock Creek Trail"), "Right onto Bridge Path.");
});

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

test("jog: a right then a bear left 30 m on is one cue, said early for both; at the junction each turn is said on its own", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 930, "Right onto 6th Street Northwest.", { street: "6th Street Northwest", turn: turning("right", "6th Street Northwest") }),
      stretch(930, 2200, "Bear left onto Rhode Island Avenue Northwest.", { street: "Rhode Island Avenue Northwest", turn: turning("bear_left", "Rhode Island Avenue Northwest") }),
    ]),
  );
  const [first, second] = model.cues;
  assert.equal(first.text, "Right onto 6th Street Northwest, then immediately bear left onto Rhode Island Avenue Northwest.");
  assert.equal(cueSpoken(first, "now", 0), "Right now onto 6th Street Northwest.");
  assert.equal(
    cueSpoken(first, "advance", 152.4),
    `In ${spokenDistance(152.4)}, right onto 6th Street Northwest, then immediately bear left onto Rhode Island Avenue Northwest.`,
  );
  assert.ok(second.joined && second.movement === "bear_left");
  assert.equal(nextAction(model, 910)?.index, second.index);
  // The owner, 2026-10-26: "do so as a prep command with all three, then go step by step at the intersection".
  for (const level of ["full", "stoker"] as const) {
    const said = ride(model, level, 0, 1200).events.filter((e) => e.cue?.kind === "turn");
    assert.ok(said.length >= 3, level);
    assert.ok(
      said.slice(0, -1).every((e) => e.cue?.index === first.index),
      level,
    );
    assert.deepEqual(said.slice(-2).map((e) => [e.cue?.index, e.phase, e.spoken]), [
      [first.index, "now", "Right now onto 6th Street Northwest."],
      [second.index, "now", "Bear left now onto Rhode Island Avenue Northwest."],
    ], level);
  }
  // The second's "now" waits until the rider is past the first turn, however close the two.
  const close = rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 906, "Right onto 6th Street Northwest.", { street: "6th Street Northwest", turn: turning("right", "6th Street Northwest") }),
      stretch(906, 2200, "Bear left onto Rhode Island Avenue Northwest.", { street: "Rhode Island Avenue Northwest", turn: turning("bear_left", "Rhode Island Avenue Northwest") }),
    ]),
  );
  const before = ride(close, "full", 0, 895, 5);
  assert.ok(!before.events.some((e) => e.cue?.index === 1));
  const past = ride(close, "full", 900, 904, 2, before.state);
  assert.deepEqual(past.events.map((e) => [e.cue?.index, e.phase, e.after]), [[1, "now", true]]);
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

test("jog: three turns in a row are one cue, said early together, then each on its own; a fourth is its own cue", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "A Street.", { street: "A Street" }),
      stretch(900, 950, "Right onto B Street.", { street: "B Street", turn: turning("right", "B Street") }),
      stretch(950, 1000, "Left onto C Street.", { street: "C Street", turn: turning("left", "C Street") }),
      stretch(1000, 1050, "Right onto D Street.", { street: "D Street", turn: turning("right", "D Street") }),
      stretch(1050, 2200, "Left onto E Street.", { street: "E Street", turn: turning("left", "E Street") }),
    ]),
  );
  assert.equal(JOG_TURNS, 3);
  assert.deepEqual(
    model.cues.filter((c) => c.kind === "turn").map((c) => [c.text, !!c.joined]),
    [
      ["Right onto B Street, then immediately left onto C Street, then immediately right onto D Street.", false],
      // On the card once the first is passed: the turns still to come, with their arrow.
      ["Left onto C Street, then immediately right onto D Street.", true],
      ["Right onto D Street.", true],
      ["Left onto E Street.", false],
    ],
  );
  assert.deepEqual(model.cues[0].then?.map((t) => t.movement), ["left", "right"]);
  const said = ride(model, "full", 0, 1100).events.filter((e) => e.cue?.kind === "turn");
  assert.match(said[0].spoken, /^In .*, right onto B Street, then immediately left onto C Street, then immediately right onto D Street\.$/);
  assert.deepEqual(
    said.filter((e) => e.phase === "now").map((e) => e.spoken),
    ["Right now onto B Street.", "Left now onto C Street.", "Right now onto D Street.", "Left now onto E Street."],
  );
  assert.deepEqual(
    cueSheet(model, 0).map((r) => r.text),
    ["Right onto B Street, then immediately left onto C Street, then immediately right onto D Street.", "Left onto E Street.", "The end of the route."],
  );
});

test("jog: the reminder about 10 s out is the turns alone, so 'now' does not cut it off; in full when said first (routing audit D8)", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "A Street.", { street: "A Street" }),
      stretch(900, 950, "Right onto B Street.", { street: "B Street", turn: turning("right", "B Street") }),
      stretch(950, 1000, "Left onto C Street.", { street: "C Street", turn: turning("left", "C Street") }),
      stretch(1000, 1050, "Bear right to stay on D Street.", { street: "D Street", turn: { ...turning("bear_right", "D Street"), stay: true } }),
      stretch(1050, 2200, "Left onto E Street.", { street: "E Street", turn: turning("left", "E Street") }),
    ]),
  );
  const first = model.cues[0];
  const said = ride(model, "full", 0, 1100).events.filter((e) => e.cue?.index === first.index);
  assert.deepEqual(said.map((e) => e.phase), ["advance", "prepare", "now"]);
  assert.match(said[0].spoken, /^In .*, right onto B Street, then immediately left onto C Street, then immediately bear right to stay on D Street\.$/);
  assert.match(said[1].spoken, /^In .*, right, then immediately left, then immediately bear right\.$/);
  // Prepare as the first thing said (a ride that starts close, a gap): the streets in full.
  assert.equal(cueSpoken(first, "prepare", 45, true), "In 150 feet, right onto B Street, then immediately left onto C Street, then immediately bear right to stay on D Street.");
  // A plain turn's prepare is unchanged.
  assert.equal(cueSpoken(model.cues[3], "prepare", 45), "In 150 feet, left onto E Street.");
  // A crossing keeps "Cross X, then ..."; a circle keeps its exit.
  const crossing = rideModel(
    straightRoute([
      stretch(0, 900, "Needwood Road bike lane.", { street: "Needwood Road bike lane" }),
      stretch(900, 925, "Cross Redland Road.", { street: "Needwood Road bike lane", turn: { ...turning("bear_right", "Needwood Road bike lane"), cross: "Redland Road" } }),
      stretch(925, 2200, "Left onto Redland Road bike lane.", { street: "Redland Road bike lane", turn: turning("left", "Redland Road bike lane") }),
    ]),
  ).cues[0];
  assert.equal(cueSpoken(crossing, "prepare", 45), "In 150 feet, cross Redland Road, then left.");
  const circle = rideModel(
    straightRoute([
      stretch(0, 900, "Massachusetts Avenue Northwest.", { street: "Massachusetts Avenue Northwest" }),
      stretch(900, 920, "Bear right onto Dupont Circle Northwest.", { street: "Dupont Circle Northwest", turn: turning("bear_right", "Dupont Circle Northwest") }),
      stretch(920, 2200, "Take the 2nd exit onto P Street Northwest at Dupont Circle Northwest.", {
        street: "P Street Northwest",
        turn: { ...turning("left", "P Street Northwest"), exit: { number: 2, circle: "Dupont Circle Northwest" } },
      }),
    ]),
  ).cues[0];
  assert.equal(cueSpoken(circle, "prepare", 45), "In 150 feet, bear right, then immediately take the 2nd exit at Dupont Circle Northwest.");
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

test("a fork along one trail stays 'to stay on' at the turn and inside a jog, never 'now onto' its own trail (routing audit D6)", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Paint Branch Trail.", { street: "Paint Branch Trail", facility: "path" }),
      stretch(900, 2200, "Bear right to stay on Paint Branch Trail.", {
        street: "Paint Branch Trail",
        facility: "path",
        turn: { ...turning("bear_right", "Paint Branch Trail"), stay: true },
      }),
    ]),
  );
  const fork = model.cues[0];
  assert.equal(fork.text, "Bear right to stay on Paint Branch Trail.");
  assert.equal(cueSpoken(fork, "advance", 152.4), `In ${spokenDistance(152.4)}, bear right to stay on Paint Branch Trail.`);
  // "Keep right now." since round-2 D22(d) (owner-approved 2026-10-27; was "Bear right now.").
  assert.equal(cueSpoken(fork, "now", 0), "Keep right now.");
  // A stay fork as a jog's later turn: said "to stay on" in the first turn's text, and "now" alone at its own turn.
  const jog = rideModel(
    straightRoute([
      stretch(0, 900, "Q Street Northwest.", { street: "Q Street Northwest" }),
      stretch(900, 930, "Right onto Paint Branch Trail.", { street: "Paint Branch Trail", facility: "path", turn: turning("right", "Paint Branch Trail") }),
      stretch(930, 2200, "Bear right to stay on Paint Branch Trail.", {
        street: "Paint Branch Trail",
        facility: "path",
        turn: { ...turning("bear_right", "Paint Branch Trail"), stay: true },
      }),
    ]),
  );
  const [first, second] = jog.cues;
  assert.equal(first.text, "Right onto Paint Branch Trail, then immediately bear right to stay on Paint Branch Trail.");
  assert.ok(second.joined);
  assert.equal(cueSpoken(second, "now", 0), "Keep right now.");
  // A plain turn keeps its street at "now".
  assert.equal(cueSpoken(first, "now", 0), "Right now onto Paint Branch Trail.");
});

test("an unusual junction's ways ride on its turn cue for the card to draw; a plain turn has none (the owner, 2026-10-20)", () => {
  const route = lRoute();
  route.description = [
    stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): Grubb Road, fairly low stress (LTS 2).", { street: "Grubb Road" }),
    stretch(1000, 1500, "0.6 to 0.9 mi (1.0 to 1.5 km): Left onto the service road, fairly low stress (LTS 2).", {
      street: "service road",
      turn: { movement: "left", onto: "service road", control: null, severity: null, shape: { out: -90, others: [0, 90] } },
    }),
    stretch(1500, 2000, "0.9 to 1.2 mi (1.5 to 2.0 km): Right onto C Street, fairly low stress (LTS 2).", {
      street: "C Street",
      turn: { movement: "right", onto: "C Street", control: null, severity: null, shape: null },
    }),
  ];
  const turns = rideModel(route).cues.filter((c) => c.kind === "turn");
  assert.deepEqual(
    turns.map((c) => [c.text, c.junction ?? null]),
    [
      ["Left onto the service road.", { out: -90, others: [0, 90] }],
      ["Right onto C Street.", null],
    ],
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
  // The card leads with it (the owner, 2026-10-20: "There's no U turn symbol."), until the rider is on the way.
  assert.equal(nextAction(model, 0)?.movement, "uturn");
  assert.equal(nextAction(model, 9.9)?.movement, "uturn");
  assert.equal(nextAction(model, PASSED_M)?.text, "Left onto B Street.");
  assert.equal(nextAction(model, 20)?.text, "Left onto B Street.");
  assert.equal(whereAmI(model, { ...startState(), progressM: 0 }).includes("Next: make a U-turn."), true);
  // Without a U-turn, the start is as before: the first turn.
  assert.equal(nextAction(rideModel(lRoute()), 0)?.text, "Left onto B Street.");
  // A first turn within 10 m of the start: the card moves on to it when the voice does.
  const near = withUTurn({ ...rideModel(lRoute()), cues: rideModel(lRoute()).cues.map((c, i) => (i === 0 ? { ...c, atM: 6 } : c)) });
  assert.equal(nextAction(near, 2)?.movement, "uturn");
  assert.equal(nextAction(near, 3.5)?.text, "Left onto B Street.");
  const out = step(model, startState(), fix(at(0, 0)), "full");
  assert.ok(out.events.some((e) => e.spoken === "Make a U-turn now."), JSON.stringify(out.events.map((e) => e.spoken)));
  const { events } = ride(model, "full", 0, 1100, 20);
  assert.equal(events.filter((e) => e.spoken.includes("U-turn")).length, 1);
  assert.ok(events.some((e) => e.spoken === "Left now onto B Street."));
});

test("a U-turn the directions say (a dead end, audit D31) is a turn cue with its distance, not a re-route's", () => {
  const route = lRoute();
  const description = (route.description ?? []).map((e) =>
    e.street === "B Street" && e.kind === "stretch"
      ? { ...e, street: "A Street", text: "0.6 to 1.2 mi (1.0 to 2.0 km): Make a U-turn on A Street, low stress (LTS 1).", turn: { movement: "uturn" as const, onto: "A Street", control: null, severity: null } }
      : e,
  );
  const model = rideModel({ ...route, description });
  const uturn = model.cues.find((c) => c.movement === "uturn");
  assert.ok(uturn, JSON.stringify(model.cues.map((c) => c.text)));
  assert.equal(uturn.kind, "turn");
  assert.equal(uturn.text, "Make a U-turn.");
  assert.equal(Math.round(uturn.atM), 1000);
  assert.equal(isStartUTurn(uturn), false);
  assert.equal(cueSpoken(uturn, "advance", 152.4), "In 500 feet, make a U-turn.");
  assert.equal(cueSpoken(uturn, "now", 10), "Make a U-turn now.");
  // Ahead until passed, as any turn; once passed the card moves on (a re-route's U-turn waits PASSED_M).
  assert.equal(nextAction(model, 900)?.movement, "uturn");
  assert.notEqual(nextAction(model, 1003)?.movement, "uturn");
  assert.equal(isStartUTurn(withUTurn(rideModel(lRoute())).cues[0]), true);
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

test("off a circle the cue says its exit, said and shown; 'now' is the exit (the owner, 2026-10-20: ring picture + exit number)", () => {
  assert.deepEqual([1, 2, 3, 4, 11, 21, 22].map(ordinal), ["1st", "2nd", "3rd", "4th", "11th", "21st", "22nd"]);
  assert.equal(exitWords({ number: 3, circle: "Dupont Circle Northwest" }, "P Street Northwest"), "Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest");
  assert.equal(exitWords({ number: 1, circle: null }, null), "Take the 1st exit at the roundabout");
  const route = lRoute();
  route.description = [
    stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): Massachusetts Avenue Northwest, busy road (LTS 3).", { street: "Massachusetts Avenue Northwest" }),
    stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest, busy road (LTS 3).", {
      street: "P Street Northwest",
      turn: {
        movement: "left",
        onto: "P Street Northwest",
        control: null,
        severity: null,
        shape: { out: -90, others: [80, -30], ring: "right" },
        exit: { number: 3, circle: "Dupont Circle Northwest" },
      },
    }),
  ];
  const [turn] = rideModel(route).cues.filter((c) => c.kind === "turn");
  assert.equal(turn.text, "Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest.");
  assert.deepEqual(turn.exit, { number: 3, circle: "Dupont Circle Northwest" });
  assert.equal(turn.junction?.ring, "right");
  assert.equal(cueSpoken(turn, "now", 10), "Exit now onto P Street Northwest.");
  assert.equal(cueSpoken(turn, "advance", 150), "In 500 feet, take the 3rd exit onto P Street Northwest at Dupont Circle Northwest.");
});

test("a ring kept as its own short stretch, then the way off: the jog says the exit, and so does its 'now'", () => {
  const route = lRoute();
  route.description = [
    stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): Massachusetts Avenue Northwest, busy road (LTS 3).", { street: "Massachusetts Avenue Northwest" }),
    stretch(1000, 1020, "0.6 to 0.6 mi (1.0 to 1.0 km): Bear right onto Dupont Circle Northwest, busy road (LTS 3).", {
      street: "Dupont Circle Northwest",
      turn: { movement: "bear_right", onto: "Dupont Circle Northwest", control: null, severity: null },
    }),
    stretch(1020, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Take the 2nd exit onto P Street Northwest at Dupont Circle Northwest, busy road (LTS 3).", {
      street: "P Street Northwest",
      turn: { movement: "left", onto: "P Street Northwest", control: null, severity: null, exit: { number: 2, circle: "Dupont Circle Northwest" } },
    }),
  ];
  const [first, second] = rideModel(route).cues.filter((c) => c.kind === "turn");
  assert.equal(first.text, "Bear right onto Dupont Circle Northwest, then immediately take the 2nd exit onto P Street Northwest at Dupont Circle Northwest.");
  assert.equal(second.joined, true);
  assert.equal(cueSpoken(second, "now", 5), "Exit now onto P Street Northwest.");
  // An exit with a turn right after it: its own "now" is the exit alone, the turn said at its own.
  const exitFirst = { ...second, joined: false, then: [{ movement: "right" as const, street: "Q Street Northwest" }] };
  assert.equal(cueSpoken(exitFirst, "now", 5), "Exit now onto P Street Northwest.");
});

test("two U-turn re-routes ridden past, then the third keeps the rider's way (the owner, 2026-10-20)", () => {
  assert.equal(UTURNS_BEFORE_AHEAD, 2);
  assert.equal(keepsAhead(0), false);
  assert.equal(keepsAhead(1), false);
  assert.equal(keepsAhead(2), true);
  assert.equal(REPLAN_AHEAD, "New route found. Keep going ahead.");
  // Said at the stoker's level, as "New route found." was before it.
  assert.equal(replanTold(false, "stoker", REPLAN_AHEAD), "say");
  assert.equal(replanTold(false, "quiet", REPLAN_AHEAD), "quiet");
});

test("ahead_only is sent only with a heading", () => {
  const body = (options: Parameters<typeof routeRequestBody>[2]) => JSON.parse(routeRequestBody([[-77, 38.9], [-77.01, 38.9]], "default", options));
  assert.equal(body({ heading: 90, aheadOnly: true }).ahead_only, true);
  assert.equal(body({ heading: 90 }).ahead_only, undefined);
  assert.equal(body({ heading: null, aheadOnly: true }).ahead_only, undefined);
});

test("no way ahead on the third: said plainly once, and the route is left up (the owner, 2026-10-20)", () => {
  assert.equal(REPLAN_NO_AHEAD, "No route found ahead. Make a U-turn.");
  assert.equal(replanTold(false, "stoker", REPLAN_NO_AHEAD), "say");
  // RideMode keeps the U-turns with uturnStep (below); what it does with its answers is wired there.
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Held, off route promises no new way; the silent check never takes the gate the rider's asks need.
  assert.match(ride, /prefsRef\.current\.verbosity, auto && !uturns\.current\.held\);/);
  assert.match(ride, /if \(check \? gate\.busy \|\| checking\.current : !gate\.begin\(Date\.now\(\)\)\) \{/);
  assert.match(ride, /announcer\.current\?\.say\(note, note === REPLAN_NO_AHEAD\)/);
  // A check that still turns round says and shows nothing.
  assert.match(ride, /if \(check && \(!found \|\| heading === null \|\| setsOffBack\(found\.geometry\.coordinates, heading\)\)\) return false;/);
  assert.match(ride, /if \(offRoute\.replan === "ask"\) void replan\(out\.state\.goodFix\.point\);\s*(\/\/[^\n]*\s*)?else if \(offRoute\.replan === "check"\) void replan\(out\.state\.goodFix\.point, undefined, false, false, true\);/);
});

// The U-turn re-routes as a sequence (lib/navigate.ts uturnStep; the v0.10.1 end review asked for it tested, not read).
const HEADING = 90;
/** A re-route made moving (heading 90), as RideMode's replan makes it: ahead only from the count, then counted. */
function reroute(state: UTurnState, turned: boolean, now: number, note = REPLAN_FOUND) {
  const aheadOnly = uturnAheadOnly(state, HEADING);
  return { aheadOnly, ...uturnStep(state, { kind: "rerouted", turned, aheadOnly, stopped: false, note, now }) };
}

test("U-turns: two asked, the third ahead only, and a way ahead starts the count again", () => {
  let state = UTURN_START;
  let step = reroute(state, true, 1000);
  assert.deepEqual([step.aheadOnly, step.note, step.state.inARow, step.state.held], [false, REPLAN_UTURN, 1, false]);
  step = reroute((state = step.state), true, 2000);
  assert.deepEqual([step.aheadOnly, step.note, step.state.inARow], [false, REPLAN_UTURN, 2]);
  step = reroute((state = step.state), false, 3000);
  assert.deepEqual([step.aheadOnly, step.note, step.state.inARow, step.state.held], [true, REPLAN_AHEAD, 0, false]);
  // Without a heading (Road closed's turn round) nothing is ahead only.
  assert.equal(uturnAheadOnly({ ...state, inARow: 5 }, null), false);
});

test("U-turns: the third still turns round: said once, held, checked silently each minute, let go by a way ahead", () => {
  let state = reroute(reroute(UTURN_START, true, 0).state, true, 0).state;
  const third = reroute(state, true, 10_000);
  assert.deepEqual([third.aheadOnly, third.note, third.state.inARow, third.state.held], [true, REPLAN_NO_AHEAD, 3, true]);
  state = third.state;
  const off = (now: number) => uturnStep(state, { kind: "off-route", now });
  // Off route while held: no re-plan out loud; a silent check once UTURN_RECHECK_MS has passed, and not again at once.
  assert.equal(off(10_000 + UTURN_RECHECK_MS - 1).replan, null);
  const checked = off(10_000 + UTURN_RECHECK_MS);
  assert.equal(checked.replan, "check");
  state = checked.state;
  assert.equal(off(10_000 + UTURN_RECHECK_MS + 1).replan, null);
  // The check finds a way ahead: taken as any re-route is, and the hold is let go.
  const ahead = reroute(state, false, 80_000);
  assert.deepEqual([ahead.aheadOnly, ahead.note, ahead.state.held, ahead.state.inARow], [true, REPLAN_AHEAD, false, 0]);
  assert.equal(uturnStep(ahead.state, { kind: "off-route", now: 80_001 }).replan, "ask");
});

test("U-turns: a hold is let go by riding the U-turn route, Re-plan from here, or the other line; a way back is never held", () => {
  const held = reroute(reroute(reroute(UTURN_START, true, 0).state, true, 0).state, true, 0).state;
  assert.equal(held.held, true);
  const along = (event: Omit<Extract<UTurnEvent, { kind: "along" }>, "kind">) => uturnStep(held, { kind: "along", ...event }).state;
  // Turned round as asked, UTURN_TAKEN_M along the U-turn route: the count starts again.
  assert.deepEqual(along({ onUTurnRoute: true, off: false, progressM: UTURN_TAKEN_M }), { ...held, inARow: 0, held: false });
  assert.equal(along({ onUTurnRoute: true, off: false, progressM: UTURN_TAKEN_M - 1 }), held);
  assert.equal(along({ onUTurnRoute: true, off: true, progressM: 500 }), held);
  // Followed another route that far: the count starts again, the hold (only ever on a U-turn route) stays as it is.
  assert.deepEqual(along({ onUTurnRoute: false, off: false, progressM: 500 }), { ...held, inARow: 0 });
  assert.equal(along({ onUTurnRoute: false, off: true, progressM: 500 }), held);
  // Re-plan from here, standing still: no heading, so nothing turns round and the hold goes; the count stays.
  const asked = uturnStep(held, { kind: "rerouted", turned: false, aheadOnly: false, stopped: true, note: REPLAN_FOUND, now: 5 });
  assert.deepEqual([asked.note, asked.state.held, asked.state.inARow], [REPLAN_FOUND, false, 3]);
  assert.equal(uturnStep(held, { kind: "other-line" }).state.held, false);
  // A way back to the planned route that turns round is followed as told, not held.
  const back = reroute({ ...UTURN_START, inARow: 2 }, true, 0, REPLAN_REJOIN);
  assert.deepEqual([back.note, back.state.held, back.state.inARow], [REPLAN_REJOIN, false, 3]);
});

test("U-turns: a re-route made while stopped leaves the count, so pausing between ignored U-turns still reaches the third", () => {
  let state = reroute(UTURN_START, true, 0).state;
  const stopped = uturnStep(state, { kind: "rerouted", turned: false, aheadOnly: uturnAheadOnly(state, null), stopped: true, note: REPLAN_FOUND, now: 1 });
  assert.deepEqual([stopped.note, stopped.state.inARow], [REPLAN_FOUND, 1]);
  state = reroute(stopped.state, true, 2).state;
  assert.equal(state.inARow, 2);
  assert.equal(reroute(state, false, 3).aheadOnly, true, "the third is ahead only");
  // Road closed turns round on purpose (not stopped): its re-route starts the count again, as before.
  assert.equal(uturnStep(state, { kind: "rerouted", turned: false, aheadOnly: false, stopped: false, note: REPLAN_FOUND, now: 4 }).state.inARow, 0);
  // Then followed: the count does not carry down the new route to a missed turn miles on.
  const followed = uturnStep(stopped.state, { kind: "along", onUTurnRoute: false, off: false, progressM: UTURN_TAKEN_M }).state;
  assert.equal(followed.inARow, 0);
  assert.equal(reroute(followed, true, 5).aheadOnly, false);
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /stopped: \(heading === null && !turnRound\) \|\| press !== null/);
});

// ---- Crossings between two turns (the owner, 2026-10-20, at Needwood Road and Redland Road: "It should have told me to cross the street and turn left") ----

test("crossing: a short path across a road between two turns is said as the crossing, then the turn, drawn straight on", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Needwood Road bike lane.", { street: "Needwood Road bike lane" }),
      stretch(900, 925, "Cross Redland Road.", {
        street: "Needwood Road bike lane",
        turn: { ...turning("bear_right", "Needwood Road bike lane"), stay: true, cross: "Redland Road", shape: { out: 30, others: [-60] } },
      }),
      stretch(925, 2200, "Left onto Redland Road bike lane.", { street: "Redland Road bike lane", turn: turning("left", "Redland Road bike lane") }),
    ]),
  );
  const [first, second] = model.cues;
  assert.equal(first.cross, "Redland Road");
  assert.equal(first.junction, undefined);
  assert.equal(first.text, "Cross Redland Road, then left onto Redland Road bike lane.");
  assert.equal(cueSpoken(first, "now", 0), "Cross Redland Road now.");
  assert.equal(cueSpoken(first, "advance", 152.4), `In ${spokenDistance(152.4)}, cross Redland Road, then left onto Redland Road bike lane.`);
  assert.ok(second.joined && second.movement === "left");
  // At the crossing, step by step: the road, then the turn on its own.
  assert.equal(cueSpoken(second, "now", 0), "Left now onto Redland Road bike lane.");
});

test("crossing: a turn just before a crossing is not joined to it; the crossing keeps its own cue with the turn after", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "A Street.", { street: "A Street" }),
      stretch(900, 960, "Left onto Needwood Road bike lane.", { street: "Needwood Road bike lane", turn: turning("left", "Needwood Road bike lane") }),
      stretch(960, 985, "Cross Redland Road.", {
        street: "Needwood Road bike lane",
        turn: { ...turning("bear_right", "Needwood Road bike lane"), stay: true, cross: "Redland Road" },
      }),
      stretch(985, 2200, "Left onto Redland Road bike lane.", { street: "Redland Road bike lane", turn: turning("left", "Redland Road bike lane") }),
    ]),
  );
  const [left, crossing] = model.cues;
  assert.equal(left.text, "Left onto Needwood Road bike lane.");
  assert.equal(crossing.text, "Cross Redland Road, then left onto Redland Road bike lane.");
  assert.ok(!crossing.joined);
});

// ---- A turn onto a path on the far side of a road (the owner, 2026-10-24: "make it clear both from the arrow and directions to cross the road then turn right") ----

test("across: a turn onto a path just across a road says the road first, drawn across it then turning", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Guilford Avenue.", { street: "Guilford Avenue" }),
      stretch(900, 2200, "Cross Saint Paul Street, then right onto Saint Paul Street bike lane.", {
        street: "Saint Paul Street bike lane",
        turn: { ...turning("right", "Saint Paul Street bike lane"), across: "Saint Paul Street" },
      }),
    ]),
  );
  const [turn] = model.cues;
  assert.equal(turn.across, "Saint Paul Street");
  assert.equal(turn.text, "Cross Saint Paul Street, then right onto Saint Paul Street bike lane.");
  assert.equal(cueSpoken(turn, "now", 0), "Cross Saint Paul Street now, then right onto Saint Paul Street bike lane.");
  assert.equal(cueSpoken(turn, "advance", 152.4), `In ${spokenDistance(152.4)}, cross Saint Paul Street, then right onto Saint Paul Street bike lane.`);
  assert.equal(crossArrow(turn), "cross_right");
  // The card: the crossing large, the turn under it in small print.
  assert.deepEqual(cueParts(turn.text), { head: "Cross Saint Paul St", rest: "Then right onto Saint Paul Street bike lane." });
});

test("across: a turn soon after is not joined to it", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 900, "Guilford Avenue.", { street: "Guilford Avenue" }),
      stretch(900, 950, "Cross Saint Paul Street, then left onto Saint Paul Street bike lane.", {
        street: "Saint Paul Street bike lane",
        turn: { ...turning("left", "Saint Paul Street bike lane"), across: "Saint Paul Street" },
      }),
      stretch(950, 2200, "Right onto Charles Street.", { street: "Charles Street", turn: turning("right", "Charles Street") }),
    ]),
  );
  const [turn, next] = model.cues;
  assert.equal(turn.text, "Cross Saint Paul Street, then left onto Saint Paul Street bike lane.");
  assert.equal(crossArrow(turn), "cross_left");
  assert.ok(!next.joined);
});

test("crossArrow: a crossing between two turns turns the way the turn after it does; alone, straight over the road", () => {
  assert.equal(crossArrow({ cross: "Redland Road", then: [{ movement: "left", street: null }], movement: "bear_right" }), "cross_left");
  assert.equal(crossArrow({ cross: "Redland Road", movement: "bear_right" }), "cross");
  assert.equal(crossArrow({ movement: "right" }), null);
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const across = crossArrow\(cue\);/);
});

// ---- D14: non-turn cues in Ride's own words (the owner approved the wording, 2026-10-27) ----------------------

test("D14: a straight change onto a busy road is 'Busy road on ...', its street's capitals kept, no LTS said", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): R Street Northwest, low stress (LTS 1).", { street: "R Street Northwest" }),
      stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Massachusetts Avenue Northwest, busy road (LTS 3).", { street: "Massachusetts Avenue Northwest", tier: 3 }),
      stretch(2000, 3000, "1.2 to 1.9 mi (2.0 to 3.0 km): US 29, heavy traffic (LTS 4).", { street: "US 29", tier: 4 }),
    ]),
  );
  const [busy, heavy] = model.cues.filter((c) => c.kind === "busy");
  // The API's sentence stays the cue's text (Plan, the courses); Ride shows and says its own.
  assert.match(busy.text, /busy road \(LTS 3\)/);
  assert.equal(busy.rideText, "Busy road on Massachusetts Avenue Northwest.");
  assert.equal(cueSpoken(busy, "advance", 150), "In 500 feet, busy road on Massachusetts Avenue Northwest.");
  assert.equal(cueSpoken(heavy, "advance", 150), "In 500 feet, heavy traffic on US 29.");
  assert.doesNotMatch(cueSpoken(heavy, "advance", 150), /LTS|uS 29/);
  // The card's large line says the same words.
  assert.match(cueParts(busy.rideText ?? busy.text).head, /^Busy road on Massachusetts Ave/);
});

test("D14: calmer, unpaved and Avoid-rated stretches, named and unnamed, with the surface after", () => {
  assert.equal(stretchWords("calmer", { street: "Q Street Northwest", tier: 2, surface: null }), "Calmer riding on Q Street Northwest.");
  assert.equal(stretchWords("calmer", { street: "unnamed path", tier: 1, surface: null }), "Calmer riding.");
  assert.equal(stretchWords("unpaved", { street: "C&O Canal Towpath", tier: 1, surface: "unpaved" }), "Unpaved surface on C&O Canal Towpath.");
  assert.equal(stretchWords("unpaved", { street: null, tier: 1, surface: "partly unpaved" }), "Partly unpaved surface.");
  assert.equal(stretchWords("busy", { street: "Whitehurst Freeway", tier: 5, surface: null }), "Avoid-rated road on Whitehurst Freeway.");
  assert.equal(stretchWords("busy", { street: "Beach Drive", tier: 3, surface: "partly unpaved" }), "Busy road on Beach Drive, partly unpaved.");
  assert.equal(stretchWords("busy", { street: "service road beside East-West Highway", tier: 3, surface: null }), "Busy road on the service road beside East-West Highway.");
});

test("D14: a walk says how far, not 'here', in feet aloud and with the metric on screen", () => {
  const route = straightRoute([
    stretch(0, 1000, "0.0 to 0.6 mi: A Street, low stress (LTS 1).", { street: "A Street" }),
    { ...stretch(1000, 1037, "At 0.6 mi (1.0 km): walk your bike here, for 120 ft (37 m)."), kind: "walk" },
    stretch(1037, 2000, "0.6 to 1.2 mi: A Street, low stress (LTS 1).", { street: "A Street" }),
  ]);
  const model = rideModel(route);
  const walk = model.cues.find((c) => c.kind === "walk")!;
  assert.match(walk.rideText ?? "", /^Walk your bike for 1\d\d ft \(37 m\)\.$/);
  assert.equal(cueSpoken(walk, "advance", 150), "In 500 feet, walk your bike for 120 feet.");
  assert.doesNotMatch(cueSpoken(walk, "advance", 150), /here| ft/);
  // Where am I? says the same words, the screen's with the metric.
  assert.match(whereAmI(model, { ...startState(), progressM: 900 }), /Next, in \d+ feet: walk your bike for 120 feet\./);
  assert.match(whereAmI(model, { ...startState(), progressM: 900 }, true), /: walk your bike for 1\d\d ft \(37 m\)\./);
});

test("D14: the first letter is lowered by the cue's kind, never a work zone's road name", () => {
  const zone = { index: 0, kind: "hazard", atM: 100, text: "Connecticut Avenue marked closed ahead.", movement: null, street: null, severity: "red", tier: null, stop: null, source: "workzone" } as Cue;
  assert.equal(cueSpoken(zone, "advance", 150), "In 500 feet, Connecticut Avenue marked closed ahead.");
  const crossing = { ...zone, source: "junction", rideText: crossingWords("Georgia Avenue", "none") } as Cue;
  assert.equal(cueSpoken(crossing, "advance", 150), "In 500 feet, busy crossing at Georgia Avenue, no signal.");
  // An API sentence a hazard is still read from: its "(LTS 4)" is not said; the screen keeps it.
  const flagged = { ...zone, source: "stretch", text: "Continue onto Georgia Avenue at a signal (Higher stress junction), heavy traffic (LTS 4)." } as Cue;
  assert.equal(cueSpoken(flagged, "advance", 150), "In 500 feet, continue onto Georgia Avenue at a signal (Higher stress junction), heavy traffic.");
});

test("D14: in Spanish the stretch and walk cues are whole Spanish sentences", () => {
  setLanguageForTest("es");
  try {
    assert.equal(stretchWords("busy", { street: "Georgia Avenue", tier: 3, surface: null }), "Calle con mucho tráfico en Georgia Avenue.");
    assert.equal(stretchWords("busy", { street: "Georgia Avenue", tier: 4, surface: "unpaved" }), "Tráfico pesado en Georgia Avenue, sin pavimentar.");
    // The same names as Plan's (src/routemaker/lang_es.py): "pesado", and "Avoid" as the rating's name (D22).
    assert.equal(stretchWords("busy", { street: "Georgia Avenue", tier: 5, surface: null }), "Calle calificada Avoid en Georgia Avenue.");
    assert.equal(walkWords(37, true), "Camine con su bicicleta por 120 pies.");
  } finally {
    setLanguageForTest("en");
  }
});

/** An Avoid-rated junction's entry as the API sends it (src/routemaker/avoid_junctions.py entries). */
function avoidEntry(atM: number, street: string | null, reason: string | null): DescriptionEntry {
  const where = `${(atM / 1609.344).toFixed(1)} mi (${(atM / 1000).toFixed(1)} km)`;
  const said = [street, reason].filter(Boolean).join(", ");
  return {
    ...stretch(atM, atM, `Avoid-rated junction ahead at ${where}${said ? `: ${said}` : ""}. Riding through it is a really bad idea. Please reconsider your route.`),
    kind: "avoid",
    street,
    reason,
    tier: null,
    severity: "avoid",
  };
}

test('R2: the Avoid-rated junction cue says the warning, the name with its capitals and the reason, never "mi"', () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1000, "0.0 to 0.6 mi: A Street, low stress (LTS 1).", { street: "A Street" }),
      avoidEntry(600, "St. Paul Street and Colesville Road", "no safe crossing"),
    ]),
  );
  const cue = model.cues.find((c) => c.source === "avoid") as Cue;
  const plea = "Riding through it is a really bad idea. Please reconsider your route.";
  // The card.
  assert.equal(cue.rideText, `Avoid-rated junction ahead. St. Paul Street and Colesville Road, no safe crossing. ${plea}`);
  assert.equal(cueSpoken(cue, "advance", 150), `In 500 feet, avoid-rated junction ahead. St. Paul Street and Colesville Road, no safe crossing. ${plea}`);
  assert.match(whereAmI(model, { ...startState(), progressM: 500 }), /: avoid-rated junction ahead\. St\. Paul Street and Colesville Road, no safe crossing\./);
  // No name or reason: the warning and the plea, no distance.
  const bare = { ...cue, rideText: avoidWords({ street: null, reason: null }) };
  assert.equal(cueSpoken(bare, "advance", 150), `In 500 feet, avoid-rated junction ahead. ${plea}`);
  // An entry with no text and no reason: the name alone.
  assert.equal(avoidWords({ street: "Main St." }), `Avoid-rated junction ahead. Main St. ${plea}`);
  // A route saved from an older API (no reason field) keeps its reason, said from the sentence after the first ": ".
  const older = { ...avoidEntry(600, "St. Paul Street and Colesville Road", "no safe crossing") } as Partial<DescriptionEntry>;
  delete older.reason;
  const olderModel = rideModel(straightRoute([stretch(0, 1000, "0.0 to 0.6 mi: A Street, low stress (LTS 1).", { street: "A Street" }), older as DescriptionEntry]));
  assert.equal(
    (olderModel.cues.find((c) => c.source === "avoid") as Cue).rideText,
    `Avoid-rated junction ahead. St. Paul Street and Colesville Road, no safe crossing. ${plea}`,
  );
  // An older sentence without the plea, or in the warning-first shape: the warning once, the plea added.
  assert.equal(avoidWords({ street: "Dupont Circle", text: "At 0.7 mi: Avoid-rated junction ahead: Dupont Circle." }), `Avoid-rated junction ahead. Dupont Circle. ${plea}`);
  assert.equal(avoidWords({ street: "Main St", text: "At 0.7 mi: Main St and 1st Ave, no gap in fast traffic." }), `Avoid-rated junction ahead. Main St and 1st Ave, no gap in fast traffic. ${plea}`);
  // The new API's null reason is not an older answer: the fields, never the sentence.
  assert.equal(avoidWords({ street: "Main St", reason: null, text: "At 0.7 mi: Main St, something else." }), `Avoid-rated junction ahead. Main St. ${plea}`);
  setLanguageForTest("es");
  try {
    const es = rideModel(straightRoute([stretch(0, 1000, "x", { street: "A Street" }), avoidEntry(600, "Colesville Road and Georgia Avenue", "no safe crossing")]));
    const said = cueSpoken(es.cues.find((c) => c.source === "avoid") as Cue, "advance", 150);
    assert.equal(
      said,
      "En 500 pies, intersección calificada Avoid más adelante. Colesville Road and Georgia Avenue, no safe crossing. Pasar por ella es una muy mala idea. Por favor, reconsidere su ruta.",
    );
    assert.doesNotMatch(said, /\bmi\b/);
    // An older answer's English plea is said in Spanish.
    assert.equal(
      avoidWords({ street: "Main St", text: `Avoid-rated junction ahead at 0.4 mi (0.6 km): Main St and 1st Ave, no safe crossing. ${plea}` }),
      "Intersección calificada Avoid más adelante. Main St and 1st Ave, no safe crossing. Pasar por ella es una muy mala idea. Por favor, reconsidere su ruta.",
    );
    assert.doesNotMatch(cueSpoken({ ...bare, rideText: avoidWords({ street: null, reason: null }) }, "advance", 150), /\bmi\b/);
  } finally {
    setLanguageForTest("en");
  }
});

test("D16: in Spanish a lane named after its street says its facility in Spanish, the street as it is; English as it was", () => {
  const lane = "9th Street Northwest protected bike lane";
  const route = straightRoute([
    stretch(0, 1000, "0.0 to 0.6 mi: A Street, low stress (LTS 1).", { street: "A Street" }),
    stretch(1000, 3000, "x", { street: lane, facility: "path", turn: straightOnto(lane) }),
  ]);
  assert.equal(turnWords("right", lane), `Right onto ${lane}.`);
  assert.match(whereAmI(rideModel(route), { ...startState(), progressM: 1500 }), /^On the 9th Street Northwest protected bike lane[,.]/);
  setLanguageForTest("es");
  try {
    assert.equal(turnWords("right", lane), "Gire a la derecha hacia el carril bici protegido de 9th Street Northwest.");
    assert.equal(wayWords("Saint Paul Street bike lane"), "el carril bici de Saint Paul Street");
    assert.equal(wayWords("path beside Saint Paul Street"), "el sendero junto a Saint Paul Street");
    // Where am I? on it: its own article, not "el el".
    const said = whereAmI(rideModel(route), { ...startState(), progressM: 1500 });
    assert.match(said, /^En el carril bici protegido de 9th Street Northwest[,.]/);
    assert.doesNotMatch(said, /el el/);
  } finally {
    setLanguageForTest("en");
  }
});

test("D17: a stop says which side of the street it is on, where the router gives it, in the end cue's words", () => {
  const sided = { ...twoLegs(), leg_arrival_sides: ["left", "right"] } as RouteResponse;
  const model = rideModel(sided);
  const stop = model.cues.find((c) => c.kind === "stop") as Cue;
  assert.equal(stop.side, "left");
  assert.equal(stop.text, "Stop 1. Destination on your left.");
  const { events } = ride(model, "quiet", 0, 2000);
  assert.deepEqual(
    events.map((e) => e.spoken),
    ["You have reached stop 1. Destination on your left.", "You have arrived at the end of the route."],
  );
  // Named, numbered among stops past a via point (the plan's point 2 is stop 1).
  const withVia = { ...twoLegs(), leg_ends: [1, 2, 4], leg_arrival_sides: [null, "right", null] } as RouteResponse;
  withVia.description = (withVia.description ?? []).map((e) => (e.kind === "via" ? { ...e, via: 2 } : e));
  const named = rideModel(withVia, [1], new Map([[2, "Union Market"]])).cues.find((c) => c.kind === "stop") as Cue;
  assert.equal(cueSpoken(named, "arrive", 0), "You have reached stop 1, Union Market. Destination on your right.");
  // Unknown, absent, or not one per leg: the cue as it was.
  for (const sides of [[null, "left"], undefined, ["left"]]) {
    const plain = rideModel({ ...twoLegs(), leg_arrival_sides: sides } as RouteResponse).cues.find((c) => c.kind === "stop") as Cue;
    assert.equal(plain.text, "Stop 1.");
    assert.equal(cueSpoken(plain, "arrive", 0), "You have reached stop 1.");
  }
  setLanguageForTest("es");
  try {
    assert.equal(cueSpoken(stop, "arrive", 0), "Ha llegado a la parada 1. El destino está a su izquierda.");
  } finally {
    setLanguageForTest("en");
  }
});

test('D22: Where am I? in Spanish says "a aproximadamente" before miles, not "a unos 0.3 millas"', () => {
  const route = straightRoute([
    stretch(0, 1000, "0.0 to 0.6 mi: A Street, low stress (LTS 1).", { street: "A Street" }),
    stretch(1000, 3000, "x", { street: "Custis Trail", facility: "path", turn: straightOnto("Custis Trail") }),
  ]);
  setLanguageForTest("es");
  try {
    const said = whereAmI(rideModel(route), { ...startState(), progressM: 1500 });
    assert.match(said, /^En el Custis Trail, a aproximadamente 0\.3 millas al \S+ de A Street\./);
    assert.doesNotMatch(said, /a unos/);
  } finally {
    setLanguageForTest("en");
  }
});

// ---- Round-2 audit, banked items the owner approved 2026-10-27 7:52 PM ET ("make the banked changes") ----------------

/** A stretch entered straight on at a flagged junction, as the API sends it (describe.py: turn.movement "straight"). */
function flaggedStraight(from: number, to: number, street: string, control: "signal" | "none" | "stop" | null, tier: number): DescriptionEntry {
  const words = control === "signal" ? " at a signal" : control === "none" ? ", no signal mapped" : control === "stop" ? " at a stop sign" : "";
  return stretch(from, to, `x: Continue onto ${street}${words} (Higher stress junction), heavy traffic (LTS ${tier}).`, {
    street,
    tier,
    turn: { movement: "straight", onto: street, control, severity: "orange" },
    severity: "orange",
  });
}

test("D25: a flagged straight-on name change is said in Ride's words, its control kept, no '(Higher stress junction)'", () => {
  const model = rideModel(
    straightRoute([
      stretch(0, 1000, "0.0 to 0.6 mi: 16th Street Northwest, fairly low stress (LTS 2).", { street: "16th Street Northwest", tier: 2 }),
      flaggedStraight(1000, 2000, "Georgia Avenue", "signal", 4),
      flaggedStraight(2000, 3000, "Connecticut Avenue", "none", 4),
    ]),
  );
  const [signal, none] = model.cues.filter((c) => c.kind === "hazard");
  // Plan's sentence stays the cue's text; Ride shows and says its own.
  assert.match(signal.text, /Higher stress junction/);
  assert.equal(signal.rideText, "Continue onto Georgia Avenue. Busy junction at a signal. Heavy traffic.");
  assert.equal(cueSpoken(signal, "advance", 150), "In 500 feet, continue onto Georgia Avenue. Busy junction at a signal. Heavy traffic.");
  // Already heavy before: no "Heavy traffic." again.
  assert.equal(cueSpoken(none, "advance", 150), "In 500 feet, continue onto Connecticut Avenue. Busy junction, no signal.");
  for (const cue of [signal, none]) assert.doesNotMatch(cueSpoken(cue, "advance", 150), /Higher stress|LTS|\(/);
  // Unnamed, a stop sign, no control mapped.
  const before = stretch(0, 1000, "a", { street: "A Street", tier: 1 });
  assert.equal(flaggedOntoWords(flaggedStraight(1000, 2000, "unnamed road", "stop", 3), before), "Busy junction at a stop sign. Busy road.");
  assert.equal(flaggedOntoWords(flaggedStraight(1000, 2000, "B Street", null, 1), before), "Continue onto B Street. Busy junction.");
  setLanguageForTest("es");
  try {
    assert.equal(
      flaggedOntoWords(flaggedStraight(1000, 2000, "Georgia Avenue", "none", 4), before),
      "Continúe por Georgia Avenue. Intersección con mucho tráfico, sin semáforo. Tráfico pesado.",
    );
    assert.equal(flaggedOntoWords(flaggedStraight(1000, 2000, "Georgia Avenue", "signal", 1), before), "Continúe por Georgia Avenue. Intersección con mucho tráfico, con semáforo.");
  } finally {
    setLanguageForTest("en");
  }
});

test("D28: 'Bike lane ends' only on a known no-lane that lasts, on the same street, never on LTS 4 or Avoid", () => {
  const ct = "Connecticut Avenue Northwest";
  const lane = (from: number, to: number, facility: DescriptionEntry["facility"], tier = 2, street = ct) =>
    stretch(from, to, `x: Continue on ${street}, fairly low stress (LTS ${tier}).`, { street, tier, facility });
  const cuesOf = (...rest: DescriptionEntry[]) =>
    rideModel(straightRoute([stretch(0, 500, "A Street.", { street: "A Street" }), { ...lane(500, 1300, "protected"), turn: turning("right", ct) }, ...rest])).cues;
  // A protected lane ends, the street goes on with no lane: said, in the app's words, at Full only.
  const ends = cuesOf(lane(1300, 2100, "none")).find((c) => c.kind === "laneEnds") as Cue;
  assert.ok(ends);
  assert.equal(ends.rideText, `Bike lane ends on ${ct}.`);
  assert.equal(cueSpoken(ends, "advance", 150), `In 500 feet, bike lane ends on ${ct}.`);
  assert.ok(says("full", ends) && !says("stoker", ends) && !says("quiet", ends));
  // Not known (null, as an older API sent "none" too): nothing.
  assert.ok(!cuesOf(lane(1300, 2100, null)).some((c) => c.kind === "laneEnds"));
  // The lane comes back within LANE_RETURN_M, or a turn comes first: nothing.
  assert.ok(!cuesOf(lane(1300, 1400, "none"), lane(1400, 2100, "lane")).some((c) => c.kind === "laneEnds"));
  assert.ok(!cuesOf(lane(1300, 1400, "none"), { ...lane(1400, 2100, "none", 2, "B Street"), turn: turning("left", "B Street") }).some((c) => c.kind === "laneEnds"));
  // Two no-lane pieces of the same street that together last: said.
  assert.ok(cuesOf(lane(1300, 1400, "none"), lane(1400, 2100, "none", 1)).some((c) => c.kind === "laneEnds"));
  // LTS 4 or Avoid, where painted lanes are hidden: never.
  assert.ok(!cuesOf(lane(1300, 2100, "none", 4)).some((c) => c.kind === "laneEnds"));
  // The tier rises to a busy road too: the busy cue says the lane ended first.
  const busy = cuesOf(lane(1300, 2100, "none", 3)).find((c) => c.kind === "busy") as Cue;
  assert.equal(busy.rideText, `Bike lane ends. Busy road on ${ct}.`);
  assert.equal(cueSpoken(busy, "advance", 150), `In 500 feet, bike lane ends. Busy road on ${ct}.`);
  setLanguageForTest("es");
  try {
    const es = cuesOf(lane(1300, 2100, "none")).find((c) => c.kind === "laneEnds") as Cue;
    assert.equal(cueSpoken(es, "advance", 150), `En 500 pies, termina el carril bici en ${ct}.`);
    assert.equal(laneEndsWords(null), "Termina el carril bici.");
  } finally {
    setLanguageForTest("en");
  }
});

test("D26: a destination on the left of a busy two-way road is said early as a crossing, never stacked on the last turn", () => {
  const ga = "Georgia Avenue Northwest";
  const arrive = (lastM: number, extra: Partial<DescriptionEntry> = {}, side: "left" | "right" = "left") =>
    rideModel({
      ...straightRoute([
        stretch(0, 300, "A Street.", { street: "A Street" }),
        stretch(300, 300 + lastM, "Right onto Georgia Avenue Northwest, busy road (LTS 3).", {
          street: ga,
          tier: 3,
          facility: "none",
          oneway: false,
          turn: turning("right", ga),
          ...extra,
        }),
      ]),
      arrival_side: side,
    } as RouteResponse);
  const said = (model: RideModel, level: Verbosity = "full") => ride(model, level, 0, model.lengthM).events.map((e) => e.spoken);
  const early = (words: string[]) => words.filter((w) => /across/.test(w));
  const full = said(arrive(400));
  assert.deepEqual(early(full), ["In 500 feet, the destination is across Georgia Avenue Northwest, on your left."]);
  // After the turn's "now", before the arrival, which is as it was.
  assert.ok(full.indexOf(early(full)[0]) > full.indexOf("Right now onto Georgia Avenue Northwest."));
  assert.equal(full.at(-1), "You have arrived at the end of the route. Destination on your left.");
  assert.deepEqual(early(said(arrive(400), "stoker")), ["In 500 feet, the destination is across Georgia Avenue Northwest, on your left."]);
  assert.deepEqual(early(said(arrive(400), "quiet")), []);
  // A last stretch too short to say it apart from the turn: not said.
  assert.deepEqual(early(said(arrive(90))), []);
  // Not said on the right, a calm road, a lane or cycletrack, a one-way road, or where the facility or one-way is not known.
  for (const [extra, side] of [
    [{}, "right"],
    [{ tier: 2 }, "left"],
    [{ facility: "lane" }, "left"],
    [{ facility: "protected" }, "left"],
    [{ oneway: true }, "left"],
    [{ oneway: null }, "left"],
    [{ facility: null }, "left"],
  ] as [Partial<DescriptionEntry>, "left" | "right"][]) {
    assert.deepEqual(early(said(arrive(400, extra, side))), [], JSON.stringify([extra, side]));
  }
  // Unnamed: "the road".
  const unnamed = arrive(400, { street: "unnamed road", turn: turning("right", "unnamed road") });
  assert.deepEqual(early(said(unnamed)), ["In 500 feet, the destination is across the road, on your left."]);
  setLanguageForTest("es");
  try {
    assert.ok(said(arrive(400)).includes("En 500 pies, el destino está al otro lado de Georgia Avenue Northwest, a su izquierda."));
    assert.ok(said(unnamed).includes("En 500 pies, el destino está al otro lado de la calle, a su izquierda."));
  } finally {
    setLanguageForTest("en");
  }
});

test("D27: one 'Continue on ... for ...' after a turn, at Full only, measured to the next turn, not a stress change", () => {
  const wod = "Washington and Old Dominion Trail";
  const route = (trailM: number, extra: DescriptionEntry[] = []) =>
    straightRoute([
      stretch(0, 300, "A Street.", { street: "A Street" }),
      stretch(300, 300 + trailM, "Right onto the trail.", { street: wod, facility: "path", turn: turning("right", wod) }),
      ...extra,
      stretch(300 + trailM + extra.reduce((m, e) => m + (e.to_m - e.from_m), 0), 300 + trailM + extra.reduce((m, e) => m + (e.to_m - e.from_m), 0) + 500, "Left onto B Street.", {
        street: "B Street",
        turn: turning("left", "B Street"),
      }),
    ]);
  // 16 km of trail, a busy stretch of the same trail half way: one cue, 60 m past the turn, to the B Street turn.
  const long = rideModel(route(8000, [stretch(8300, 16300, "x", { street: wod, facility: "path", tier: 3 })]));
  const full = ride(long, "full", 0, 2000).events.filter((e) => /^Continue/.test(e.spoken));
  assert.deepEqual(
    full.map((e) => e.spoken),
    [`Continue on ${wod} for ${spokenDistance(16300 - 360)}.`],
  );
  assert.equal(spokenDistance(16300 - 360), "9.9 miles");
  assert.equal(full[0].urgent, false);
  assert.equal(full[0].cue?.kind, "turn");
  // Stoker and Quiet: none.
  for (const level of ["stoker", "quiet"] as const) assert.ok(!ride(long, level, 0, 2000).events.some((e) => /^Continue on/.test(e.spoken)));
  // Under a mile to the next turn: none.
  assert.ok(!ride(rideModel(route(1500)), "full", 0, 1000).events.some((e) => /^Continue on/.test(e.spoken)));
  // Started past the window after the turn: none.
  const late = ride(long, "full", 700, 1500, 5, { ...startState() }).events;
  assert.ok(!late.some((e) => /^Continue on/.test(e.spoken)));
  setLanguageForTest("es");
  try {
    const es = ride(long, "full", 0, 1000).events.find((e) => /^Siga/.test(e.spoken));
    assert.equal(es?.spoken, `Siga por ${wod} durante 9.9 millas.`);
  } finally {
    setLanguageForTest("en");
  }
});

test("D22(d): a bear at a fork along one way says 'Keep right now.', the advance cue's verb in Spanish too", () => {
  const fork = (movement: "bear_right" | "bear_left" | "right") =>
    rideModel(
      straightRoute([
        stretch(0, 900, "Paint Branch Trail.", { street: "Paint Branch Trail", facility: "path" }),
        stretch(900, 2200, "x", { street: "Paint Branch Trail", facility: "path", turn: { ...turning(movement, "Paint Branch Trail"), stay: true } }),
      ]),
    ).cues[0];
  assert.equal(cueSpoken(fork("bear_right"), "now", 0), "Keep right now.");
  assert.equal(cueSpoken(fork("bear_left"), "now", 0), "Keep left now.");
  // A full turn to stay on the way keeps its own verb; a bear that is no fork keeps "Bear right now onto ...".
  assert.equal(cueSpoken(fork("right"), "now", 0), "Right now.");
  const plain = { ...fork("bear_right"), stay: undefined, street: "B Street" };
  assert.equal(cueSpoken(plain, "now", 0), "Bear right now onto B Street.");
  setLanguageForTest("es");
  try {
    const cue = fork("bear_right");
    assert.equal(cueSpoken(cue, "advance", 152.4), "En 500 pies, manténgase a la derecha para seguir en Paint Branch Trail.");
    assert.equal(cueSpoken(cue, "now", 0), "Manténgase a la derecha ahora.");
    assert.equal(cueSpoken(fork("bear_left"), "now", 0), "Manténgase a la izquierda ahora.");
  } finally {
    setLanguageForTest("en");
  }
});

test("the screen's short words (the UI review, 2026-10-28): Where am I? in two lines, the weak-GPS rows, the arrival", () => {
  const model = rideModel(twoLegs());
  const { state } = ride(model, "quiet", 0, 400);
  // The street, then the next cue's distance and street and the arrival clock; the voice's sentence is whereAmI's.
  assert.deepEqual(whereAmIShown(model, state, null, (s) => `${Math.round(s)} s`), ["A St", "0.4 mi (0.6 km) → B St · 320 s"]);
  assert.deepEqual(whereAmIShown(model, state), ["A St", "0.4 mi (0.6 km) → B St"]);
  assert.match(whereAmI(model, state), /^On A Street\. Next, in 0\.4 miles: left onto B Street\./);
  assert.deepEqual(whereAmIShown(model, { ...state, progressM: null }), ["Finding your place on the route."]);
  // The weak-GPS list: each row short on screen, its whole sentence kept beside it.
  const rows = cueSheet(model, 400);
  assert.equal(rows[0].shown, "0.4 mi (0.6 km) · Stop 1");
  // The turn is at the stop: nought from the row before.
  assert.equal(rows[1].shown, "0 ft (0 m) · Left · B St");
  assert.equal(rows[1].text, "Left onto B Street.");
  assert.equal(CUE_SHEET_SHOWN, 3);
  assert.equal(cueShort("Left onto Church Street Northwest."), "Left · Church St NW");
  assert.equal(cueShort("Right."), "Right");
  assert.equal(cueShort("Right, then immediately right onto Union Station Drive Northeast."), "Right · Union Station Dr NE");
  assert.equal(cueShort("Bear left onto the path, then immediately left onto Corregidor Street Northwest, then immediately right onto N Street Northwest."), "Bear left · Corregidor St NW");
  assert.equal(cueShort("Bear left to stay on Metropolitan Branch Trail."), "Bear left to stay on Metropolitan Branch Trl");
  // Arrived: the destination's name where the map has one.
  assert.equal(arrivedShown("Union Station"), "Arrived: Union Station");
  assert.equal(arrivedShown(null), "Arrived");
});
