/**
 * Standing still is not weak GPS (Stephen, 2026-11-28: "It keeps saying GPS is weak, turn cues paused when waiting at
 * lights"). Stopped at a light, a phone's GPS often sends a few rough fixes (50 m and worse: the fused location drops
 * to Wi-Fi and cell readings once the rider has not moved for a while, and they drift past the 4 m filter). Twelve
 * seconds of them brought up the weak-GPS note (lib/navigate.ts weighFix) though nothing was wrong: no turn is due
 * while the rider waits.
 *
 * A rough fix that still fits a rider standing where the last good fix was keeps the weak-GPS clock as a good fix
 * would: the last good fix had a speed and it was slow (braking or stopped), the rough fix shows no movement of its own, and the last
 * good spot lies inside its accuracy circle. For STILL_MS at most, so GPS that is really gone is said in the end even
 * at a long wait. A rider who rides off under rough GPS sends fixes with a speed, or soon leaves the circle: the clock
 * runs for them from then, and the note comes as before. Our defaults, unmeasured.
 */
import { haversineM } from "./geo.ts";
import { POOR_FIX_M, type RideFix } from "./navigate.ts";

/**
 * The last good fix slower than this (about 4.5 mph): the rider was braking for a light or stopped. Not STOPPED_MS:
 * with the 4 m filter the last fix before a stop is often still rolling at 1-2 m/s. The cost, a walking-pace rider
 * under trees with speedless rough fixes, hears the note late; no estimate runs below this speed either.
 */
export const STILL_LAST_SPEED_MS = 2;
/** A rough fix with a speed under this (about 1 mph), or none at all, shows no movement of its own. */
export const STILL_SPEED_MS = 0.5;
/** For this long after the last good fix at most (a long DC light is 60-120 s; the beats' own limit). */
export const STILL_MS = 180_000;

/**
 * Whether `fix`, a rough one, is a rider still standing at `lastGood`, which came in at `lastGoodAt`; `now` is the
 * same clock. A good fix, or none to go by, is never "still": weighFix decides as before.
 */
export function stillAtLight(lastGood: RideFix | null, lastGoodAt: number, fix: RideFix, now: number): boolean {
  if (!lastGood || !(fix.accuracyM > POOR_FIX_M)) return false;
  if (now - lastGoodAt > STILL_MS) return false;
  // A real speed only: with none, a rider at any speed would pass (review of #1478).
  if (lastGood.speedMs === null || lastGood.speedMs >= STILL_LAST_SPEED_MS) return false;
  if (fix.speedMs !== null && fix.speedMs >= STILL_SPEED_MS) return false;
  return haversineM(lastGood.point, fix.point) <= fix.accuracyM;
}
