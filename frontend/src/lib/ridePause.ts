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
 *   (the share bike's dock, the stay above) going, for HEARTBEAT_STOP_MS at most. It is never a new place, and never
 *   a fix to the weak-GPS clock: a slow rider who loses GPS under trees must still hear so and get the turn list.
 *
 * Pure but for PausedFixes, which keeps one fix: the clocks and positions come in as arguments; nothing is sent.
 */
import { haversineM, type LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import { POOR_FIX_M, type RideFix } from "./navigate.ts";

/** Within this of where the stay began… */
export const STAY_M = 30;
/** …for this long: the ride (arrived) or roam (not moving) pauses. */
export const STAY_MS = 10 * 60_000;
/** While paused, one reading this often. */
export const PAUSE_CHECK_MS = 30_000;
/** A reading's greatest age (a little under PAUSE_CHECK_MS, so each check is a new reading). */
export const PAUSE_READING_AGE_MS = 25_000;
/** A good reading this far (plus its accuracy) from where the pause began: the rider is moving again, so it resumes. */
export const PAUSE_MOVED_M = 30;
/**
 * Only a reading this good counts as a move, from a stay or a pause: indoors a 30-50 m fix drifts that far with the
 * rider sat still, and would resume a pause, or keep one from starting (the owner, 2026-11-01: battery audit).
 */
export const MOVE_GOOD_M = 20;
/** No fix for this long in the app: the last one is given again with the time now. */
export const HEARTBEAT_MS = 5_000;
/**
 * No real fix for this long: no more beats. Stopped that long with no fix, the GPS may as well be lost, and the
 * clocks the beats keep (a dock, the stay) must not run on a place the rider may have left (the owner, 2026-11-01:
 * battery audit).
 */
export const HEARTBEAT_STOP_MS = 60_000;
/**
 * Only after a fix this slow (about 4.5 mph) or with no speed: a rider moving faster who stops getting fixes has more
 * likely lost GPS (a tunnel) than stopped, and the weak-GPS clock must run for them.
 */
export const HEARTBEAT_MAX_SPEED_MS = 2;
/**
 * A last fix this slow is a rider standing still (a red light), not one riding slowly: with the 4 m filter the GPS
 * sends nothing at a light, and a 60-120 s DC light must not bring up the weak-GPS note or the turn list. Their beats
 * also keep the last fix's time and the weak-GPS clock, for up to STOPPED_BEAT_MS (the owner, 2026-11-01: battery
 * audit, "Make sure there's some backup").
 */
export const STOPPED_MS = 0.5;
export const STOPPED_BEAT_MS = 180_000;

/** Where a stay began, and when. */
export interface Stay {
  point: LonLat;
  since: number;
}

/** Whether `fix` shows the rider `m` or more from `spot`: a good fix (MOVE_GOOD_M) beyond `m` plus its own accuracy. */
function movedFrom(spot: LonLat, fix: Pick<RideFix, "point" | "accuracyM">, m: number): boolean {
  return fix.accuracyM <= MOVE_GOOD_M && haversineM(spot, fix.point) > m + fix.accuracyM;
}

/**
 * One place into the stay: the first fit fix (POOR_FIX_M) starts it; only a good one well beyond STAY_M (movedFrom)
 * starts it afresh there, so indoor drift does not keep the pause away. A poor fix changes nothing.
 */
export function stayStep(stay: Stay | null, fix: Pick<RideFix, "point" | "accuracyM" | "at">): Stay | null {
  if (!(fix.accuracyM <= POOR_FIX_M)) return stay;
  if (stay && !movedFrom(stay.point, fix, STAY_M)) return stay;
  return { point: fix.point, since: fix.at };
}

/** Stayed long enough to pause. */
export function stayedLong(stay: Stay | null, now: number, ms: number = STAY_MS): boolean {
  return stay !== null && now - stay.since >= ms;
}

/** A paused ride's reading: whether it says the rider has moved on from `spot` (movedFrom: good, and clear of drift). */
export function movedFromPause(spot: LonLat | null, reading: Pick<RideFix, "point" | "accuracyM">): boolean {
  return spot !== null && movedFrom(spot, reading, PAUSE_MOVED_M);
}

/**
 * The heartbeat's fix: the last real fix with the time `now`, once none has come for HEARTBEAT_MS; null when it is
 * not time, none has come for over HEARTBEAT_STOP_MS, there is none, it was poor, or the rider was moving at speed.
 */
export function heartbeatFix(last: RideFix | null, lastRealAt: number, now: number): RideFix | null {
  if (!last || now - lastRealAt < HEARTBEAT_MS || now - lastRealAt > (stoppedAt(last) ? STOPPED_BEAT_MS : HEARTBEAT_STOP_MS)) return null;
  if (!(last.accuracyM <= POOR_FIX_M)) return null;
  if (last.speedMs !== null && last.speedMs >= HEARTBEAT_MAX_SPEED_MS) return null;
  return { ...last, speedMs: 0, headingDeg: null, at: now };
}

/** The last real fix shows the rider standing still, with a good fix (STOPPED_MS, MOVE_GOOD_M). */
export function stoppedAt(last: RideFix): boolean {
  return last.speedMs !== null && last.speedMs < STOPPED_MS && last.accuracyM <= MOVE_GOOD_M;
}

/**
 * Whether a beat also keeps the GPS clocks (the last fix's time, the weak-GPS clock): only after a stopped rider's
 * good fix, and only within STOPPED_BEAT_MS. A slow rider who loses GPS under trees still hears so (review of #859).
 */
export function beatKeepsGps(last: RideFix | null, lastRealAt: number, now: number): boolean {
  return last !== null && stoppedAt(last) && now - lastRealAt <= STOPPED_BEAT_MS;
}

/*
 * The words of the stay-put pauses (the owner, 2026-11-01: battery audit). Only the app rides on with the screen
 * locked; in a browser the pause lets the screen lock go, the page goes hidden, and the 30 s readings wait for it to be
 * in front again, so riding off with the phone in a pocket would not carry on: there Resume is the way.
 */
const RIDE_STAY_PAUSED_APP = t("Ride paused at your destination to save battery. It carries on when you ride off, or press Resume.");
const RIDE_STAY_PAUSED_BROWSER = t("Ride paused at your destination to save battery. Press Resume to carry on.");
const ROAM_STAY_PAUSED_APP = t("Roam paused to save battery. It carries on when you ride off, or press Resume.");
const ROAM_STAY_PAUSED_BROWSER = t("Roam paused to save battery. Press Resume to carry on.");
/** Said as Roam carries on by itself: the pause was said, so is its end. */
export const ROAM_RESUMED_SAID = t("Roam resumed.");

/** Ride's words for its pause at the destination: `app` is the phone app (lib/nativeShell.ts ridesHidden). */
export function rideStayPausedSaid(app: boolean): string {
  return app ? RIDE_STAY_PAUSED_APP : RIDE_STAY_PAUSED_BROWSER;
}

/** Roam's words for its pause when not moving: `app` as rideStayPausedSaid. */
export function roamStayPausedSaid(app: boolean): string {
  return app ? ROAM_STAY_PAUSED_APP : ROAM_STAY_PAUSED_BROWSER;
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
