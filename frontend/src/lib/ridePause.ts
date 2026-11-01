/**
 * The battery pauses of Ride and Roam, and the app's heartbeat (the owner, 2026-11-01: battery audit).
 *
 * - Staying put: arrived (Ride), or not moving (Roam), within STAY_M for STAY_MS, the continuous watch stops, as a
 *   long page hide stops it, and Resume is offered.
 * - While paused (the owner, 2026-11-01: "During a pause maybe check on a much longer interval, such as every 30s rather
 *   than stopping outright"): one reading every PAUSE_CHECK_MS; one good reading more than PAUSE_MOVED_M from where the
 *   pause began resumes by itself, as Resume does. In a browser that reading is a one-shot; in the app the native watch
 *   runs on (PausedFixes, below), since a new one restarts the location service, which Android 14+ refuses from the
 *   background.
 * - The heartbeat: the app's GPS sends a fix only once the rider has moved NATIVE_DISTANCE_FILTER_M (lib/nativeShell.ts),
 *   so a stopped rider gets none. The last fix, given the time now, keeps the checks that count time standing still
 *   (the share bike's dock, the weak-GPS clock, the stay above) going. It is never a new place: nothing is placed on
 *   the line, and nothing is taken as off route, from it.
 *
 * Pure but for PausedFixes, which keeps one fix: the clocks and positions come in as arguments; nothing is sent.
 */
import { haversineM, type LonLat } from "./geo.ts";
import { POOR_FIX_M, type RideFix } from "./navigate.ts";

/** Within this of where the stay began… */
export const STAY_M = 30;
/** …for this long: the ride (arrived) or roam (not moving) pauses. */
export const STAY_MS = 10 * 60_000;
/** While paused, one reading this often. */
export const PAUSE_CHECK_MS = 30_000;
/** A reading's greatest age (a little under PAUSE_CHECK_MS, so each check is a new reading). */
export const PAUSE_READING_AGE_MS = 25_000;
/** A good reading this far from where the pause began: the rider is moving again, so it resumes. */
export const PAUSE_MOVED_M = 30;
/** No fix for this long in the app: the last one is given again with the time now. */
export const HEARTBEAT_MS = 5_000;
/**
 * Only after a fix this slow (about 4.5 mph) or with no speed: a rider moving faster who stops getting fixes has more
 * likely lost GPS (a tunnel) than stopped, and the weak-GPS clock must run for them.
 */
export const HEARTBEAT_MAX_SPEED_MS = 2;

/** Where a stay began, and when. */
export interface Stay {
  point: LonLat;
  since: number;
}

/** One good place into the stay: within STAY_M keeps it; further starts afresh there. A poor fix changes nothing. */
export function stayStep(stay: Stay | null, fix: Pick<RideFix, "point" | "accuracyM" | "at">): Stay | null {
  if (!(fix.accuracyM <= POOR_FIX_M)) return stay;
  if (stay && haversineM(stay.point, fix.point) <= STAY_M) return stay;
  return { point: fix.point, since: fix.at };
}

/** Stayed long enough to pause. */
export function stayedLong(stay: Stay | null, now: number, ms: number = STAY_MS): boolean {
  return stay !== null && now - stay.since >= ms;
}

/** A paused ride's reading: whether it says the rider has moved on from `spot` (a good reading only). */
export function movedFromPause(spot: LonLat | null, reading: Pick<RideFix, "point" | "accuracyM">): boolean {
  if (!spot || !(reading.accuracyM <= POOR_FIX_M)) return false;
  return haversineM(spot, reading.point) > PAUSE_MOVED_M;
}

/**
 * The heartbeat's fix: the last real fix with the time `now`, once none has come for HEARTBEAT_MS; null when it is
 * not time, there is none, it was poor, or the rider was moving at speed.
 */
export function heartbeatFix(last: RideFix | null, lastRealAt: number, now: number): RideFix | null {
  if (!last || now - lastRealAt < HEARTBEAT_MS) return null;
  if (!(last.accuracyM <= POOR_FIX_M)) return null;
  if (last.speedMs !== null && last.speedMs >= HEARTBEAT_MAX_SPEED_MS) return null;
  return { ...last, speedMs: 0, headingDeg: null, at: now };
}

/**
 * The app's paused watch (the owner, 2026-11-01: battery audit). The app has no one-shot reading: each would start a
 * native watch, so restart the location foreground service, which Android 14+ refuses while the app is in the
 * background (the phone is usually locked by then), and riding off would never resume. So the watch runs on through
 * the pause and its fixes are only held here, nothing drawn or said; every PAUSE_CHECK_MS the latest one is taken as
 * that check's one reading (movedFromPause). With the 4 m filter a rider standing still sends none, so none is taken.
 */
export class PausedFixes {
  private latest: RideFix | null = null;

  /** A fix from the watch while paused: kept in place of the last, nothing else. */
  hold(fix: RideFix): void {
    this.latest = fix;
  }

  /** This check's reading: the latest fix since the last check, or null; each is taken once. */
  take(): RideFix | null {
    const fix = this.latest;
    this.latest = null;
    return fix;
  }

  /** A new pause starts with none held. */
  clear(): void {
    this.latest = null;
  }
}
