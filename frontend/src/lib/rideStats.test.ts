// The ride's summary figures (lib/rideStats.ts; the owner, 2026-10-20). Made-up points along a meridian, not a real ride.
import { test } from "node:test";
import assert from "node:assert/strict";
import { elevationSpan, profileGain, statsPause, statsStart, statsStep, summaryRows, type RideStats } from "./rideStats.ts";
import type { RideFix, RideModel } from "./navigate.ts";
import type { RouteProfile } from "./api.ts";

// One metre north is about this many degrees of latitude.
const DEG_PER_M = 1 / 111_195;
const at = (m: number): [number, number] => [-77, 38.9 + m * DEG_PER_M];
const fix = (m: number, s: number, accuracyM = 5): RideFix => ({ point: at(m), accuracyM, speedMs: null, headingDeg: null, at: s * 1000 });
const model = {
  coordinates: [at(0), at(2000)],
  along: new Float64Array([0, 2000]),
  lengthM: 2000,
  cues: [],
  stretches: [
    { fromM: 0, toM: 1000, street: "A St", tier: 1, facility: null },
    { fromM: 1000, toM: 2000, street: "B St", tier: 3, facility: null },
  ],
  paceMs: 5,
} as unknown as RideModel;
const profile = { m: [0, 500, 1000, 1500, 2000], elevation_m: [10, 20, 15, 25, 25] } as unknown as RouteProfile;
const onRoute = (m: number) => ({ progressM: m, off: false });

/** A steady ride: a fix every `every` seconds at `speed` m/s, from `fromM` to `toM`. */
function ride(stats: RideStats, fromM: number, toM: number, speed: number, startS: number, every = 2): RideStats {
  let s = stats;
  for (let m = fromM, t = startS; m <= toM; m += speed * every, t += every) s = statsStep(s, fix(m, t), onRoute(m), model, profile);
  return s;
}

test("distance, moving time and the stress ridden add up along the route", () => {
  const s = ride(statsStart(0), 0, 2000, 5, 0);
  assert.ok(Math.abs(s.distanceM - 2000) < 5, String(s.distanceM));
  assert.ok(Math.abs(s.movingMs - 400_000) < 3000, String(s.movingMs));
  assert.ok(Math.abs((s.stressM["1"] ?? 0) - 1000) < 15);
  assert.ok(Math.abs((s.stressM["3"] ?? 0) - 1000) < 15);
  // 10 m up, 5 down, 10 up: 20 m climbed.
  assert.ok(Math.abs(s.climbM - 20) < 0.5, String(s.climbM));
});

test("standing still with the GPS wandering adds no distance or moving time", () => {
  let s = ride(statsStart(0), 0, 100, 5, 0);
  const before = s;
  for (let t = 22; t < 140; t += 2) s = statsStep(s, fix(100 + ((t % 4) - 2), t), onRoute(100), model, profile);
  assert.equal(s.distanceM, before.distanceM);
  assert.equal(s.movingMs, before.movingMs);
});

test("poor fixes, jumps and walking to a dock are not counted", () => {
  let s = ride(statsStart(0), 0, 100, 5, 0);
  const d = s.distanceM;
  s = statsStep(s, fix(400, 22, 80), onRoute(400), model, profile);
  assert.equal(s.distanceM, d);
  // 1 km in 2 s: a bad fix, skipped, and the next step counts from it.
  s = statsStep(s, fix(1100, 24), onRoute(1100), model, profile);
  assert.equal(s.distanceM, d);
  assert.equal(statsPause(s).last, null);
});

test("off the route, distance counts but not climbing or stress", () => {
  let s = statsStep(statsStart(0), fix(0, 0), { progressM: 0, off: true }, model, profile);
  s = statsStep(s, fix(600, 120), { progressM: 600, off: true }, model, profile);
  assert.ok(s.distanceM > 590);
  assert.equal(s.climbM, 0);
  assert.deepEqual(s.stressM, {});
});

test("profileGain interpolates and counts only the way up", () => {
  assert.equal(profileGain(profile, 0, 250), 5);
  assert.equal(profileGain(profile, 500, 1000), 0);
  assert.equal(profileGain(null, 0, 2000), 0);
  assert.equal(profileGain(profile, 900, 800), 0);
});

test("the rows are US units first with metric in brackets; total time only where it differs", () => {
  const s = ride(statsStart(0), 0, 2000, 5, 0);
  const rows = summaryRows(s, 600_000);
  const by = Object.fromEntries(rows.map((r) => [r.name, r.value]));
  assert.equal(by["Distance"], "1.2 mi (2.0 km)");
  assert.equal(by["Moving time"], "7 min");
  assert.equal(by["Average speed"], "11 mph (18 km/h)");
  assert.equal(by["Total time"], "10 min");
  assert.equal(by["Climbing"], "66 ft (20 m)");
  assert.equal(summaryRows(statsStart(0), 5000)[0].value, "0 ft (0 m)");
  assert.equal(summaryRows(s, s.movingMs).find((r) => r.name === "Total time"), undefined);
});

test("heights are kept along the ride for the elevation chart, every 30 m or so, from the route's profile", () => {
  const s = ride(statsStart(0), 0, 2000, 5, 0);
  assert.ok(s.elevation.length >= 60 && s.elevation.length <= 70, String(s.elevation.length));
  assert.equal(s.elevation[0].m, 10);
  assert.deepEqual(elevationSpan(s), { lo: 10, hi: 25 });
  for (let i = 1; i < s.elevation.length; i++) assert.ok(s.elevation[i].atM - s.elevation[i - 1].atM >= 30);
  // Off the route, none.
  let off = statsStep(statsStart(0), fix(0, 0), { progressM: 0, off: true }, model, profile);
  off = statsStep(off, fix(600, 120), { progressM: 600, off: true }, model, profile);
  assert.equal(elevationSpan(off), null);
});
