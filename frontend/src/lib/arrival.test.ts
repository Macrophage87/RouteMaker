// Arrival clock times in a ride (the owner, 2026-10-26: "Add estimated clock time of arrival to the ride." and
// "Stops too"): lib/arrival.ts runs here, and RideMode's wiring is read as source, as the other ride tests do.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { FULL_M, GAP_S, HALT_CAP_S, LEAVE_M, START_M, arrivalClock, atPace, leaveNowArrival, leaveNowArriveMs, paceFactor, paceStart, paceStep, type PaceTrack } from "./arrival.ts";
import { setLanguageForTest } from "./i18n.ts";
import { whenAt } from "./rideTime.ts";

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
  const going = ride(coffee, PACE, 60);
  assert.ok(Math.abs(going.riddenS - coffee.riddenS - 60) <= 1, String(going.riddenS - coffee.riddenS));
  const after = ride(going, 0, 30);
  assert.equal(after.riddenS - going.riddenS, 30);
});

test("GPS drift at a halt is still the halt: no new allowance for each wobble", () => {
  const before = ride(paceStart(), PACE, 1200);
  let t = before;
  let at = t.last!.atMs;
  const from = t.last!.progressM;
  // Thirty minutes stood still, the snapped place wandering up to 10 m either way.
  for (let s = 1; s <= 30 * 60; s++) {
    at += 1000;
    t = paceStep(t, { atMs: at, progressM: from + 10 * Math.sin(s / 7), line: "a", paceMs: PACE, riding: true });
  }
  assert.equal(t.riddenS - before.riddenS, HALT_CAP_S);
  assert.equal(t.metres, before.metres);
  // Riding off: the halt ends LEAVE_M past where it began, its distance credited.
  t = paceStep(t, { atMs: at + 5000, progressM: from + LEAVE_M + 10, line: "a", paceMs: PACE, riding: true });
  assert.equal(t.haltS, 0);
  assert.equal(t.metres - before.metres, LEAVE_M + 10);
});

test("atPace divides each time to go by the factor, and leaves the distances", () => {
  const togo = { stop: { number: 2, metres: 1000, seconds: 200 }, end: { metres: 3000, seconds: 600 } };
  assert.equal(atPace(togo, 1), togo);
  assert.deepEqual(atPace(togo, 2), { stop: { number: 2, metres: 1000, seconds: 100 }, end: { metres: 3000, seconds: 300 } });
  assert.deepEqual(atPace({ stop: null, end: { metres: 5, seconds: null } }, 0.5), { stop: null, end: { metres: 5, seconds: null } });
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

test("the plan's own seconds for a stretch (a climb, a junction wait) are what the rider is measured against", () => {
  // The plan takes twice the even pace's time on this stretch (a climb): a rider at the even pace is half as fast.
  let t = paceStart();
  t = paceStep(t, { atMs: 0, progressM: 0, line: "a", paceMs: PACE, plan: (a, b) => (2 * (b - a)) / PACE, riding: true });
  for (let s = 1; s <= 2000; s++) t = paceStep(t, { atMs: s * 1000, progressM: s * PACE, line: "a", paceMs: PACE, plan: (a, b) => (2 * (b - a)) / PACE, riding: true });
  assert.ok(Math.abs(paceFactor(t) - 2) < 0.01, String(paceFactor(t)));
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
  assert.match(source, /visually-hidden">\{t\(", arriving about"\)\} </);
  assert.match(source, /atPace\(toGo\(model, progress\), paceFactor\(paceRef\.current\)\)/);
  assert.equal((source.match(/milesRef\.current, arrivingAt\)/g) ?? []).length, 3);
  assert.match(source, /setClockTick\(\(n\) => n \+ 1\), 30_000\)/, "the clock moves on with no fix");
  assert.match(source, /\|\$\{togoWords\}`;/, "large text fits again when the times lengthen");
  assert.match(source, /riding: !stepped\.state\.walking && !pausedRef\.current && !out\.state\.off && !out\.state\.arrived/);
});

test("before a ride, the route's time ends with when it arrives leaving now, in English and Spanish", () => {
  const arrive = new Date(2026, 9, 27, 8, 27, 0).getTime();
  const words = leaveNowArrival(arrive, "en-US");
  assert.equal(words.shown.replace(/\s/gu, " "), "arrive 8:27 AM");
  assert.equal(words.said.replace(/\s/gu, " "), "arriving about 8:27 AM if you leave now");
  setLanguageForTest("es");
  try {
    const es = leaveNowArrival(arrive, "es-US");
    assert.match(es.shown, /^llegada 8:27\s?a/u);
    assert.match(es.said, /^llegada estimada 8:27\s?a.* si sale ahora$/u);
    // One o'clock needs no "la"/"las" either (round-2 audit D22: "hacia las 1:05" was wrong).
    const one = leaveNowArrival(new Date(2026, 9, 27, 13, 5, 0).getTime(), "es-US");
    assert.match(one.said, /^llegada estimada 1:05\s?p.* si sale ahora$/u);
    assert.doesNotMatch(one.said, /\blas 1:/u);
  } finally {
    setLanguageForTest("en");
  }
});

test("the arrival leaving now: a ride, at the time now; not a transit, bikeshare or Mass Ride plan, nor another ride time", () => {
  // Tuesday 2026-10-27, noon in DC (16:00 UTC): a weekday off-peak.
  const now = Date.UTC(2026, 9, 27, 16, 0, 0);
  assert.equal(whenAt(new Date(now)), "weekday_offpeak");
  const ride = { duration_s: 108 * 60, preset: "commuter" };
  assert.equal(leaveNowArriveMs(ride, now, null), now + 108 * 60_000, "When I'm planning is now");
  assert.equal(leaveNowArriveMs(ride, now, "weekday_offpeak"), now + 108 * 60_000, "the time chosen is the time now");
  assert.equal(leaveNowArriveMs(ride, now, "weekend"), null);
  assert.equal(leaveNowArriveMs(ride, now, "night"), null, "Night chosen at noon");
  assert.equal(leaveNowArriveMs({ ...ride, transit: {} }, now, null), null);
  assert.equal(leaveNowArriveMs({ ...ride, bikeshare: {} }, now, null), null);
  assert.equal(leaveNowArriveMs({ ...ride, preset: "mass-ride" }, now, null), null);
  assert.equal(leaveNowArriveMs(null, now, null), null);
});

test("Go's and Plan's route time carry the arrival, on App's minute clock", () => {
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.equal((panel.match(/<dd>\{timeShown\}<\/dd>/g) ?? []).length, 2, "Go's sheet and Plan's totals");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const arriveMs = leaveNowArriveMs\(shown, minute, dials\.when \?\? null\);/);
});
