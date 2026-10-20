/**
 * The ride's own figures, for the summary shown at End ride (the owner, 2026-10-20: "When ending a ride, perhaps
 * summary stats rather than programming that ride again"). Kept from the ride's fixes, in memory only, as the ride
 * itself is: nothing is stored or sent.
 *
 * - Distance: the straight line between good fixes (POOR_FIX_M), once the rider has moved MOVE_MIN_M from the last
 *   one counted, so GPS wander while stopped adds nothing. A jump faster than MAX_SPEED_MS (a bad fix) is not counted.
 * - Moving time: the time of each counted step ridden at MOVING_MIN_MS or more, each step capped at STEP_MAX_MS so a
 *   gap in the fixes is not all taken as riding.
 * - Climbing: the planned route's elevation profile over the stretch ridden along it (fixes carry no reliable
 *   height); off the route, or across a re-plan, nothing is added.
 * - Traffic stress: the metres ridden along the route on each tier of the stretch the rider was on.
 */
import { FEET_PER_METRE, formatClimb, formatDistance, formatDuration, formatSpeed, spokenClimb, spokenDistance, spokenSpeed } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { POOR_FIX_M, stretchAt, type RideFix, type RideModel, type RideState } from "./navigate.ts";
import type { RouteProfile } from "./api.ts";
import type { StressKey, StressMetres } from "./stressBar.ts";

/** Moved at least this far from the last counted fix before a step counts (GPS wander while stopped). */
export const MOVE_MIN_M = 8;
/** A step faster than this is a bad fix, not riding. */
export const MAX_SPEED_MS = 25;
/** A step slower than this adds distance but not moving time (walking the bike, waiting at a light). */
export const MOVING_MIN_MS = 1;
/** One step adds at most this much moving time. */
export const STEP_MAX_MS = 30_000;
/** Along-route progress moving further than this past the straight-line step is a jump, not riding. */
const ALONG_SLACK_M = 60;

export interface RideStats {
  startedAt: number;
  distanceM: number;
  movingMs: number;
  climbM: number;
  /** Metres ridden along the route on each tier. */
  stressM: StressMetres;
  /** The last counted fix: where, when, and where along which route. */
  last: { point: LonLat; at: number; progressM: number | null; model: RideModel | null } | null;
}

export function statsStart(now: number): RideStats {
  return { startedAt: now, distanceM: 0, movingMs: 0, climbM: 0, stressM: {}, last: null };
}

/** Walking to a dock (lib/rideTrip.ts): not the ride; the next step starts from the next fix. */
export function statsPause(stats: RideStats): RideStats {
  return stats.last ? { ...stats, last: null } : stats;
}

/** Metres climbed along the profile from `fromM` to `toM` (forward only). */
export function profileGain(profile: Pick<RouteProfile, "m" | "elevation_m"> | null | undefined, fromM: number, toM: number): number {
  if (!profile || !(toM > fromM)) return 0;
  const { m, elevation_m: el } = profile;
  const at = (x: number): number | null => {
    for (let i = 1; i < m.length; i++) {
      if (m[i] >= x) {
        const a = el[i - 1];
        const b = el[i];
        if (a === null || b === null) return null;
        const span = m[i] - m[i - 1];
        return span > 0 ? a + ((b - a) * (x - m[i - 1])) / span : b;
      }
    }
    return null;
  };
  const heights: (number | null)[] = [at(fromM)];
  for (let i = 0; i < m.length; i++) if (m[i] > fromM && m[i] < toM) heights.push(el[i]);
  heights.push(at(toM));
  let gain = 0;
  for (let i = 1; i < heights.length; i++) {
    const a = heights[i - 1];
    const b = heights[i];
    if (a !== null && b !== null && b > a) gain += b - a;
  }
  return gain;
}

/** One fix of the ride, after the ride's own step placed it (`state`) on `model`. */
export function statsStep(
  stats: RideStats,
  fix: RideFix,
  state: Pick<RideState, "progressM" | "off">,
  model: RideModel,
  profile: RouteProfile | null | undefined,
): RideStats {
  if (fix.accuracyM > POOR_FIX_M) return stats;
  const progressM = state.off ? null : state.progressM;
  const here = { point: fix.point, at: fix.at, progressM, model };
  const last = stats.last;
  if (!last) return { ...stats, last: here };
  const stepM = haversineM(last.point, fix.point);
  if (stepM < MOVE_MIN_M) return stats;
  const dt = fix.at - last.at;
  if (!(dt > 0) || stepM / (dt / 1000) > MAX_SPEED_MS) return { ...stats, last: here };
  const next: RideStats = { ...stats, last: here, distanceM: stats.distanceM + stepM };
  if (stepM / (dt / 1000) >= MOVING_MIN_MS) next.movingMs = stats.movingMs + Math.min(dt, STEP_MAX_MS);
  // Along the same route, forward, by about the step: its climbing and its stress.
  if (last.model === model && last.progressM !== null && progressM !== null) {
    const along = progressM - last.progressM;
    if (along > 0 && along <= stepM + ALONG_SLACK_M) {
      next.climbM = stats.climbM + profileGain(profile, last.progressM, progressM);
      const tier = stretchAt(model, (last.progressM + progressM) / 2)?.tier ?? null;
      const key = (tier !== null && tier >= 1 && tier <= 5 ? String(Math.round(tier)) : "unknown") as StressKey;
      next.stressM = { ...stats.stressM, [key]: (stats.stressM[key] ?? 0) + stepM };
    }
  }
  return next;
}

export interface RideSummaryRow {
  name: string;
  value: string;
}

/** The summary's rows, US units first with metric in brackets; elapsed time only where it differs from moving time. */
export function summaryRows(stats: RideStats, now: number): RideSummaryRow[] {
  const elapsedS = Math.max(0, (now - stats.startedAt) / 1000);
  const movingS = stats.movingMs / 1000;
  const rows: RideSummaryRow[] = [{ name: "Distance", value: formatDistance(stats.distanceM) }];
  if (movingS >= 30) {
    rows.push({ name: "Moving time", value: formatDuration(movingS) });
    rows.push({ name: "Average speed", value: formatSpeed((stats.distanceM / movingS) * 3.6) });
  }
  if (formatDuration(elapsedS) !== formatDuration(movingS) || movingS < 30) rows.push({ name: "Total time", value: formatDuration(elapsedS) });
  if (Math.round(stats.climbM) >= 1) rows.push({ name: "Climbing", value: formatClimb(stats.climbM) });
  return rows;
}

/** What is said: US units only, as every spoken figure is. "Ride ended. 4.7 miles, 23 minutes moving, 12 miles per hour average." */
export function summarySpoken(stats: RideStats): string {
  if (stats.distanceM < MOVE_MIN_M) return "Ride ended.";
  const movingS = stats.movingMs / 1000;
  const parts = [spokenDistance(stats.distanceM)];
  if (movingS >= 30) {
    const minutes = Math.max(1, Math.round(movingS / 60));
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    const time = hours > 0 ? `${hours} ${hours === 1 ? "hour" : "hours"}${rest ? ` ${rest} ${rest === 1 ? "minute" : "minutes"}` : ""}` : `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
    parts.push(`${time} moving`);
    parts.push(`${spokenSpeed(stats.distanceM / movingS)} average`);
  }
  if (stats.climbM * FEET_PER_METRE >= 10) parts.push(`${spokenClimb(stats.climbM)} of climbing`);
  return `Ride ended. ${parts.join(", ")}.`;
}
