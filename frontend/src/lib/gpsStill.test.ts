import { test } from "node:test";
import assert from "node:assert/strict";
import { STILL_MS, stillAtLight } from "./gpsStill.ts";
import { GPS_WEAK_MS, weighFix, type GpsWeakness, type RideFix } from "./navigate.ts";

const LIGHT: [number, number] = [-77.0365, 38.8977];
/** About `m` metres north of the light. */
const north = (m: number): [number, number] => [LIGHT[0], LIGHT[1] + m / 111_320];
const fix = (over: Partial<RideFix>): RideFix => ({ point: LIGHT, accuracyM: 8, speedMs: 0, headingDeg: null, at: 0, ...over });

/** RideMode's weak-GPS step: a still fix restarts the clock as a good one does, then weighFix. Whether the note came. */
function ride(fixes: Array<{ at: number; fix: RideFix }>): boolean {
  let weak: GpsWeakness = { goodAt: 0, weak: false };
  let lastGood: RideFix | null = null;
  let lastGoodAt = 0;
  let said = false;
  for (const { at, fix: f } of fixes) {
    const still = !weak.weak && stillAtLight(lastGood, lastGoodAt, f, at);
    if (f.accuracyM <= 50) {
      lastGood = f;
      lastGoodAt = at;
    }
    if (still) weak = { goodAt: at, weak: false };
    const w = weighFix(weak, f.accuracyM, at);
    weak = { goodAt: w.goodAt, weak: w.weak };
    said ||= w.sayNow;
  }
  return said;
}

test("waiting at a light: rough drifting fixes after a stop never say the GPS is weak", () => {
  const fixes = [{ at: 0, fix: fix({ speedMs: 1.2 }) }];
  // Ninety seconds of 60-120 m Wi-Fi fixes, no speed, drifting up to 40 m: a long DC light.
  for (let t = 5_000; t <= 90_000; t += 5_000) fixes.push({ at: t, fix: fix({ point: north((t / 1000) % 40), accuracyM: 60 + (t % 60), speedMs: null }) });
  assert.equal(ride(fixes), false);
});

test("riding off under rough GPS still says it is weak", () => {
  const fixes = [{ at: 0, fix: fix({ speedMs: 1 }) }];
  // Rough fixes that move: the rider is off again, at about 11 mph.
  for (let t = 2_000; t <= 30_000; t += 2_000) fixes.push({ at: t, fix: fix({ point: north(t / 200), accuracyM: 80, speedMs: 5 }) });
  assert.equal(ride(fixes), true);
});

test("rough GPS while riding at speed is weak GPS, as before", () => {
  const fixes = [{ at: 0, fix: fix({ speedMs: 6 }) }];
  for (let t = 2_000; t <= GPS_WEAK_MS + 4_000; t += 2_000) fixes.push({ at: t, fix: fix({ accuracyM: 80, speedMs: null }) });
  assert.equal(ride(fixes), true);
});

test("a rough fix that has moved off the last good spot is not standing still", () => {
  const last = fix({ speedMs: 0 });
  assert.equal(stillAtLight(last, 0, fix({ point: north(70), accuracyM: 60, speedMs: null }), 10_000), false);
  assert.equal(stillAtLight(last, 0, fix({ point: north(40), accuracyM: 60, speedMs: null }), 10_000), true);
});

test("GPS gone for longer than any light is said in the end, even standing still", () => {
  const last = fix({ speedMs: 0 });
  assert.equal(stillAtLight(last, 0, fix({ accuracyM: 90, speedMs: null }), STILL_MS), true);
  assert.equal(stillAtLight(last, 0, fix({ accuracyM: 90, speedMs: null }), STILL_MS + 1), false);
});

test("a good fix, or no good fix yet, is never taken as standing still", () => {
  assert.equal(stillAtLight(fix({}), 0, fix({ accuracyM: 10 }), 1_000), false);
  assert.equal(stillAtLight(null, 0, fix({ accuracyM: 90, speedMs: null }), 1_000), false);
});

test("braking to a stop holds the clock; rough fixes with a speed, or no speed to go by, do not", () => {
  // About 3.4 mph on the last good fix: braking for the light (the 4 m filter sends no slower fix). Known cost: a
  // walking-pace rider under trees whose rough fixes carry no speed waits for the note too (estimates never run
  // under 2 m/s anyway, ESTIMATE_MIN_SPEED_MS)...
  assert.equal(stillAtLight(fix({ speedMs: 1.5 }), 0, fix({ accuracyM: 100, speedMs: null }), 5_000), true);
  // ...but rough fixes that carry the rider's own speed are riding, not waiting.
  assert.equal(stillAtLight(fix({ speedMs: 1.5 }), 0, fix({ accuracyM: 100, speedMs: 1.4 }), 5_000), false);
  // No speed on the last good fix: nothing says the rider stopped, so weighFix decides as before.
  const fixes = [{ at: 0, fix: fix({ speedMs: null }) }];
  for (let t = 2_000; t <= GPS_WEAK_MS + 4_000; t += 2_000) fixes.push({ at: t, fix: fix({ accuracyM: 120, speedMs: null }) });
  assert.equal(ride(fixes), true);
});
