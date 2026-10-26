// Arrival clock times in a ride (the owner, 2026-10-26: "Add estimated clock time of arrival to the ride." and
// "Stops too"): lib/arrival.ts runs here, and RideMode's wiring is read as source, as the other ride tests do.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { FULL_M, GAP_S, HALT_CAP_S, START_M, arrivalClock, paceFactor, paceStart, paceStep, type PaceTrack } from "./arrival.ts";

const PACE = 5; // metres a second, the plan's

/** Fixes every `everyS` seconds at `speed` for `seconds`, from `track`'s last place (or 0). */
function ride(track: PaceTrack, speed: number, seconds: number, everyS = 1, line = "a"): PaceTrack {
  let t = track;
  let at = t.last?.atMs ?? 0;
  let m = t.last?.progressM ?? 0;
  if (!t.last) t = paceStep(t, { atMs: at, progressM: m, line, paceMs: PACE, riding: true });
  for (let s = 0; s < seconds; s += everyS) {
    at += everyS * 1000;
    m += speed * everyS;
    t = paceStep(t, { atMs: at, progressM: m, line, paceMs: PACE, riding: true });
  }
  return t;
}

test("at the plan's pace the factor stays 1", () => {
  const t = ride(paceStart(), PACE, 2000);
  assert.ok(Math.abs(paceFactor(t) - 1) < 1e-9);
});

test("no correction before START_M ridden, the whole ratio by FULL_M", () => {
  const early = ride(paceStart(), PACE * 1.5, (START_M - 50) / (PACE * 1.5));
  assert.equal(paceFactor(early), 1);
  const full = ride(paceStart(), PACE * 1.5, FULL_M / (PACE * 1.5) + 10);
  assert.ok(Math.abs(paceFactor(full) - 1.5) < 0.01, String(paceFactor(full)));
  const half = ride(paceStart(), PACE * 1.5, ((START_M + FULL_M) / 2) / (PACE * 1.5));
  assert.ok(paceFactor(half) > 1.2 && paceFactor(half) < 1.3, String(paceFactor(half)));
});

test("a slower rider gets later times, within twice either way", () => {
  assert.ok(Math.abs(paceFactor(ride(paceStart(), PACE * 0.8, 2000)) - 0.8) < 0.01);
  assert.equal(paceFactor(ride(paceStart(), PACE * 5, 2000)), 2);
  assert.equal(paceFactor(ride(paceStart(), PACE * 0.1, 20000)), 0.5);
});

test("a halt counts up to HALT_CAP_S, a coffee stop no more", () => {
  const before = ride(paceStart(), PACE, 1200);
  const coffee = ride(before, 0, 30 * 60);
  assert.equal(coffee.riddenS - before.riddenS, HALT_CAP_S);
  // Riding on starts a new halt next time.
  const after = ride(ride(coffee, PACE, 60), 0, 30);
  assert.equal(after.riddenS - coffee.riddenS, 60 + 30);
});

test("a gap in fixes, a new line, off route and going back are not counted", () => {
  const t = ride(paceStart(), PACE, 600);
  const last = t.last!;
  const gap = paceStep(t, { atMs: last.atMs + (GAP_S + 1) * 1000, progressM: last.progressM + 5000, line: "a", paceMs: PACE, riding: true });
  assert.equal(gap.metres, t.metres);
  assert.equal(gap.riddenS, t.riddenS);
  const rerouted = paceStep(t, { atMs: last.atMs + 1000, progressM: 0, line: "b", paceMs: PACE, riding: true });
  assert.equal(rerouted.riddenS, t.riddenS);
  assert.equal(rerouted.last?.line, "b");
  const off = paceStep(t, { atMs: last.atMs + 1000, progressM: last.progressM + 5, line: "a", paceMs: PACE, riding: false });
  assert.equal(off.last, null);
  assert.equal(off.riddenS, t.riddenS);
  const back = paceStep(t, { atMs: last.atMs + 1000, progressM: last.progressM - 50, line: "a", paceMs: PACE, riding: true });
  assert.equal(back.metres, t.metres);
});

test("the clock is the device's own: 12 hour in en-US, 24 hour in en-GB, rounded to the minute", () => {
  const now = new Date(2026, 9, 26, 6, 30, 0).getTime();
  // Newer ICU puts a narrow no-break space before AM.
  assert.equal(arrivalClock(now, 12 * 60 + 20, "en-US").replace(/\s/u, " "), "6:42 AM");
  assert.equal(arrivalClock(now + 12 * 3600_000, 12 * 60 + 40, "en-GB"), "18:43");
});

test("RideMode shows the arrival clock after each time to go and says it in Where am I?", () => {
  const source = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.equal((source.match(/<TimeToGo seconds=/g) ?? []).length, 2, "the next stop and the end");
  assert.match(source, /visually-hidden">, arriving about </);
  assert.match(source, /atPace\(toGo\(model, progress\), paceFactor\(paceRef\.current\)\)/);
  assert.equal((source.match(/milesRef\.current, arrivingAt\)/g) ?? []).length, 3);
  assert.match(source, /riding: !stepped\.state\.walking && !pausedRef\.current && !out\.state\.off && !out\.state\.arrived/);
});
