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
 * - Elevation (the owner, 2026-10-20: "Show elevation too!"): the profile's height where the rider was on the route,
 *   every ELEVATION_STEP_M of the ride's distance, for the summary's chart.
 */
import { formatClimb, formatDistance, formatDuration, formatSpeed } from "./format.ts";
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
/** A height is kept for the chart this often along the ride's distance. */
export const ELEVATION_STEP_M = 30;
/** At most this many heights; past it every other one goes and the step doubles. */
const ELEVATION_MAX = 1000;
/** Along-route progress moving further than this past the straight-line step is a jump, not riding. */
const ALONG_SLACK_M = 60;

export interface RideStats {
  startedAt: number;
  distanceM: number;
  movingMs: number;
  climbM: number;
  /** Metres ridden along the route on each tier. */
  stressM: StressMetres;
  /** Heights along the ride (metres along its distance, metres up), for the chart. */
  elevation: { atM: number; m: number }[];
  /** The last counted fix: where, when, and where along which route. */
  last: { point: LonLat; at: number; progressM: number | null; model: RideModel | null } | null;
}

export function statsStart(now: number): RideStats {
  return { startedAt: now, distanceM: 0, movingMs: 0, climbM: 0, stressM: {}, elevation: [], last: null };
}

/** Walking to a dock (lib/rideTrip.ts): not the ride; the next step starts from the next fix. */
export function statsPause(stats: RideStats): RideStats {
  return stats.last ? { ...stats, last: null } : stats;
}

/** Metres climbed along the profile from `fromM` to `toM` (forward only). */
/** The profile's height `x` metres along the route, or null where it has none. */
export function profileAt(profile: Pick<RouteProfile, "m" | "elevation_m"> | null | undefined, x: number): number | null {
  if (!profile) return null;
  const { m, elevation_m: el } = profile;
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
}

export function profileGain(profile: Pick<RouteProfile, "m" | "elevation_m"> | null | undefined, fromM: number, toM: number): number {
  if (!profile || !(toM > fromM)) return 0;
  const { m, elevation_m: el } = profile;
  const at = (x: number) => profileAt(profile, x);
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
  if (!last) return { ...stats, last: here, elevation: progressM === null ? stats.elevation : withHeight(stats.elevation, stats.distanceM, profileAt(profile, progressM)) };
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
  if (progressM !== null) next.elevation = withHeight(stats.elevation, next.distanceM, profileAt(profile, progressM));
  return next;
}

/** The heights with one more where it is ELEVATION_STEP_M (or the thinned step) past the last; thinned past ELEVATION_MAX. */
function withHeight(heights: RideStats["elevation"], atM: number, m: number | null): RideStats["elevation"] {
  if (m === null) return heights;
  const last = heights[heights.length - 1];
  const step = heights.length > 1 ? Math.max(ELEVATION_STEP_M, (heights[heights.length - 1].atM - heights[0].atM) / ELEVATION_MAX) : ELEVATION_STEP_M;
  if (last && atM - last.atM < step) return heights;
  const next = [...heights, { atM, m }];
  return next.length > ELEVATION_MAX ? next.filter((_, i) => i % 2 === 0 || i === next.length - 1) : next;
}

/** The lowest and highest of the heights kept, or null with fewer than two. */
export function elevationSpan(stats: Pick<RideStats, "elevation">): { lo: number; hi: number } | null {
  if (stats.elevation.length < 2) return null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const h of stats.elevation) {
    lo = Math.min(lo, h.m);
    hi = Math.max(hi, h.m);
  }
  return { lo, hi };
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
