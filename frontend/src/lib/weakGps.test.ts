// Weak GPS on the line (Stephen 2026-11-13, "All three, no new switches"): the turns still said for ESTIMATE_MS, as
// estimates ("In about ...", "About here: ..."), the ride carried on along the line at its last speed. Synthetic only.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ESTIMATE_AFTER_MS,
  ESTIMATE_MS,
  GPS_WEAK_MS,
  estimateStep,
  pointAt,
  rideModel,
  startState,
  step,
  weakNoteAfterMs,
  weighFix,
  type LonLat,
  type RideFix,
  type RideModel,
  type RideState,
} from "./navigate.ts";
import { setUnitsForTest } from "./units.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";

setUnitsForTest("us");
/** Poor fixes coming at riding speed, nothing else holding the ride. */
const weak = { poorSeen: true, lastSpeedMs: 5, free: true };
const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
const at = (east: number, north: number): LonLat => [-77.05 + east / KX, LAT + north / M_PER_DEG];

function stretch(from: number, to: number, text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street: null, tier: 1, facility: null, turn: null, text, ...extra };
}

/** East 1,000 m on A Street, then left (north) 1,000 m on B Street. */
function lRoute(): RouteResponse {
  return {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0, 0), at(1000, 0), at(1000, 1000)] },
    distance_m: 2000,
    duration_s: 400,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [2],
    description: [
      stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): A Street, low stress (LTS 1).", { street: "A Street" }),
      stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Left onto B Street, low stress (LTS 1).", {
        street: "B Street",
        turn: { movement: "left", onto: "B Street", control: null, severity: null },
      }),
    ],
  } as RouteResponse;
}

/** Good fixes along the line at 5 m/s from 0 to `toM`, one a second. */
function rideTo(model: RideModel, toM: number): RideState {
  let state = startState();
  for (let m = 0, s = 0; m <= toM; m += 5, s += 1) {
    const fix: RideFix = { point: pointAt(model, m), accuracyM: 5, speedMs: 5, headingDeg: 90, at: s * 1000 };
    state = step(model, state, fix, "full").state;
  }
  return state;
}

test("weak GPS: the next turn's cues said as estimates, at the reckoned place, each once", () => {
  const model = rideModel(lRoute());
  const before = rideTo(model, 805);
  assert.ok(Math.abs((before.progressM ?? 0) - 805) < 1);
  assert.deepEqual(estimateStep(model, before, ESTIMATE_AFTER_MS - 1, "full", weak).events, [], "an ordinary gap between fixes is not weak GPS");
  // 12 s on at 5 m/s: 60 m on, the turn about 135 m (450 ft) ahead.
  const first = estimateStep(model, before, 12_000, "full", weak);
  assert.equal(first.events.length, 1);
  assert.equal(first.events[0].phase, "advance");
  assert.match(first.events[0].spoken, /^In about \d+ feet, left onto B Street\.$/);
  assert.equal(first.state.progressM, before.progressM, "progress is a good fix's alone");
  assert.ok(Math.abs((first.state.estM ?? 0) - (before.progressM! + 60)) < 1);
  assert.deepEqual(estimateStep(model, first.state, 12_500, "full", weak).events, [], "never said twice");
  // 30 s: the prepare (45 m out); just after it is past ESTIMATE_MS, so the turn's "now" waits for a real fix.
  const prepare = estimateStep(model, first.state, 30_000, "full", weak);
  assert.deepEqual(prepare.events.map((e) => e.phase), ["prepare"]);
  assert.deepEqual(estimateStep(model, prepare.state, ESTIMATE_MS + 1, "full", weak).events, [], "after ESTIMATE_MS: paused, as before");
  // A good fix places the rider afresh: the reckoning is cleared, and what was said is not said again.
  const back = step(model, prepare.state, { point: pointAt(model, 960), accuracyM: 5, speedMs: 5, headingDeg: 90, at: 191_000 }, "full");
  assert.equal(back.state.estM, undefined);
  assert.equal(back.state.estSaid, undefined);
  assert.ok(back.events.every((e) => e.phase !== "advance" && e.phase !== "prepare"));
});

test("weak GPS near a turn: 'About here', urgent, so it gets the buzz", () => {
  const model = rideModel(lRoute());
  const before = rideTo(model, 940);
  const now = estimateStep(model, { ...before, said: { ...before.said, 1: ["advance", "prepare"], 0: before.said[0] } }, 10_000, "full", weak);
  const turn = now.events.find((e) => e.phase === "now");
  assert.ok(turn, JSON.stringify(now.events));
  assert.equal(turn.urgent, true);
  assert.match(turn.spoken, /^About here: Left now onto B Street\.$/);
});

test("weak GPS: nothing reckoned when stopped, off route, alongside, arrived or quiet", () => {
  const model = rideModel(lRoute());
  const before = rideTo(model, 800);
  for (const ground of [
    { ...weak, poorSeen: false },
    { ...weak, lastSpeedMs: 1 },
    { ...weak, free: false },
  ]) {
    assert.deepEqual(estimateStep(model, before, 12_000, "full", ground).events, []);
  }
  for (const state of [
    { ...before, speedMs: 0.5 },
    { ...before, off: true },
    { ...before, alongside: true },
    { ...before, arrived: true },
    { ...before, progressM: null },
  ]) {
    assert.deepEqual(estimateStep(model, state, 12_000, "full", weak).events, []);
  }
  assert.deepEqual(estimateStep(model, before, 12_000, "quiet", weak).events, [], "quiet says no turns, estimated or not");
});

test("the weak-GPS note waits for the estimates where the ride is reckoned, so it never says 'paused' over them", () => {
  const model = rideModel(lRoute());
  const moving = rideTo(model, 800);
  assert.equal(weakNoteAfterMs(model, moving, weak), ESTIMATE_MS);
  assert.equal(weakNoteAfterMs(model, { ...moving, speedMs: 0 }, weak), GPS_WEAK_MS, "stopped: as before");
  assert.equal(weakNoteAfterMs(model, { ...moving, off: true }, weak), GPS_WEAK_MS);
  assert.equal(weakNoteAfterMs(model, moving, { ...weak, free: false }), GPS_WEAK_MS, "walking to a dock: as before");
  assert.equal(weakNoteAfterMs(model, rideTo(model, 1100), weak), GPS_WEAK_MS, "only the end ahead: nothing to reckon");
  const fresh = { goodAt: 0, weak: false };
  assert.equal(weighFix(fresh, 80, GPS_WEAK_MS + 1).sayNow, true, "the old timing by default");
  assert.equal(weighFix(fresh, 80, GPS_WEAK_MS + 1, ESTIMATE_MS).sayNow, false);
  assert.equal(weighFix(fresh, 80, ESTIMATE_MS, ESTIMATE_MS).sayNow, true);
});

test("arriving waits for the last turn's 'now' to be said instead of cutting it off (the cue bench)", () => {
  const model = rideModel(lRoute());
  let state = rideTo(model, 805);
  const events = [];
  for (let m = 810, s = 200; m <= 2000; m += 5, s += 1) {
    const out = step(model, state, { point: pointAt(model, m), accuracyM: 5, speedMs: 5, headingDeg: 0, at: s * 1000 }, "full");
    state = out.state;
    events.push(...out.events);
  }
  const arrive = events.find((e) => e.phase === "arrive");
  assert.ok(arrive);
  assert.equal(arrive.urgent, true);
  assert.equal(arrive.after, true);
});

test("stopped at a light before a turn (GPS quiet, no poor fixes): never reckoned on to the turn", () => {
  const model = rideModel(lRoute());
  const braking = rideTo(model, 900);
  // The smoothed speed lags the brake; the last fix's own speed does not.
  assert.deepEqual(estimateStep(model, braking, 20_000, "full", { poorSeen: false, lastSpeedMs: 1.5, free: true }).events, []);
  assert.deepEqual(estimateStep(model, braking, 20_000, "full", { poorSeen: true, lastSpeedMs: 1.5, free: true }).events, []);
});

test("a reckoning that ran ahead: the real 'now' still comes at the turn on a good fix", () => {
  const model = rideModel(lRoute());
  const before = rideTo(model, 905);
  let state = { ...before, said: { ...before.said, 1: ["advance", "prepare"] as ("advance" | "prepare")[] } };
  const est = estimateStep(model, state, 20_000, "full", weak);
  assert.deepEqual(est.events.map((e) => e.phase), ["now"], "reckoned to the turn");
  // The rider had slowed: a good fix 40 m before the turn, then at it.
  state = step(model, est.state, { point: pointAt(model, 960), accuracyM: 5, speedMs: 3, headingDeg: 90, at: 300_000 }, "full").state;
  const at = step(model, state, { point: pointAt(model, 995), accuracyM: 5, speedMs: 3, headingDeg: 90, at: 310_000 }, "full");
  const all = [...at.events];
  assert.ok(all.some((e) => e.phase === "now" && /^Left now/.test(e.spoken)), JSON.stringify(all));
});

test("the weak-GPS note waits only where a turn's warning can be reached in the window", () => {
  const model = rideModel(lRoute());
  // 100 m in, the left turn's first warning is still far beyond 30 s at 5 m/s: the note is not held back.
  assert.equal(weakNoteAfterMs(model, rideTo(model, 100), weak), GPS_WEAK_MS);
  assert.equal(weakNoteAfterMs(model, rideTo(model, 800), weak), ESTIMATE_MS);
});

test("a reckoned place does not linger once nothing is reckoned", () => {
  const model = rideModel(lRoute());
  const reckoned = estimateStep(model, rideTo(model, 800), 10_000, "full", weak).state;
  assert.notEqual(reckoned.estM, undefined);
  assert.equal(estimateStep(model, reckoned, ESTIMATE_MS + 1_000, "full", weak).state.estM, undefined, "past the window");
  assert.equal(estimateStep(model, reckoned, 10_000, "full", { ...weak, lastSpeedMs: 0.5 }).state.estM, undefined, "slowed to a stop");
});
