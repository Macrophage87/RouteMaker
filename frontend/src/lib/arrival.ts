/**
 * Arrival clock times on the ride screen (the owner, 2026-10-26: "Add estimated clock time of arrival to the ride."
 * and "Stops too"). The time to go is the route's own (its ride type's flat-road speed scaled by grade, plus the
 * junction delays), read along the line where the API says where it falls: a climb ahead and the junction waits
 * ahead counted where they are (the owner, 2026-10-26: "make sure intersection waits are considered too";
 * navigate.ts secondsAt). That is corrected by how the rider is actually riding against the plan for the same
 * stretch once they have ridden far enough for it to mean something.
 *
 * The correction is the ratio of the plan's seconds for the metres ridden to the seconds it took to ride them. A
 * halt counts up to HALT_CAP_S (a long light or a stop sign the plan allows for), not beyond it: a coffee stop or a
 * chat at a corner says nothing about the pace still to come. Time off route, paused or walking is not counted, and
 * a gap in fixes (a tunnel, the phone asleep) longer than GAP_S is left out. A halt lasts until the rider is LEAVE_M
 * past where it began, so GPS drift at a stop does not start a new allowance.
 */
import type { ToGo } from "./navigate.ts";
import { t } from "./i18n.ts";
import type { When } from "./dials.ts";
import { whenAt } from "./rideTime.ts";

/** A halt counted up to this, in seconds. */
export const HALT_CAP_S = 90;
/** Fixes further apart than this, in seconds, are not one stretch of riding. */
export const GAP_S = 120;
/** Under this many metres a fix to the next is a halt. */
const STILL_M = 2;
/** A halt lasts until the rider is this far past where it began: GPS drift at a stop is not riding off. */
export const LEAVE_M = 15;
/** Further back than this from the last place (or a halt's start) is a new start, not drift. */
const BACK_M = 50;
/** The correction begins after this many metres ridden and is whole by FULL_M. */
export const START_M = 800;
export const FULL_M = 5000;
/** The correction never makes the plan more than twice as fast or as slow. */
const MAX_FACTOR = 2;

export interface PaceTrack {
  /** The plan's seconds for the metres ridden. */
  plannedS: number;
  /** The seconds it took, halts capped. */
  riddenS: number;
  /** Metres ridden. */
  metres: number;
  /** Seconds of the halt now going on, 0 when riding. */
  haltS: number;
  /** The last sample counted from, or null; in a halt, its place is where the halt began. */
  last: { atMs: number; progressM: number; line: string } | null;
}

export function paceStart(): PaceTrack {
  return { plannedS: 0, riddenS: 0, metres: 0, haltS: 0, last: null };
}

export interface PaceSample {
  atMs: number;
  progressM: number | null;
  /** The route line the progress is along: a new one (a re-route) starts the next stretch afresh. */
  line: string;
  /** The plan's even pace on that line, metres a second. */
  paceMs: number | null;
  /**
   * The plan's seconds between two places on that line, hills and junction waits where they are (navigate.ts
   * secondsBetween); absent, at the even pace.
   */
  plan?: (fromM: number, toM: number) => number | null;
  /** On the route and riding: not off route, paused, walking or arrived. */
  riding: boolean;
}

/** The track with one more fix. */
export function paceStep(track: PaceTrack, sample: PaceSample): PaceTrack {
  if (!sample.riding || sample.progressM === null || !(sample.paceMs && sample.paceMs > 0)) return { ...track, haltS: 0, last: null };
  const here = { atMs: sample.atMs, progressM: sample.progressM, line: sample.line };
  const last = track.last;
  const dt = last ? (sample.atMs - last.atMs) / 1000 : 0;
  if (!last || last.line !== sample.line || dt <= 0 || dt > GAP_S || sample.progressM < last.progressM - BACK_M) return { ...track, haltS: 0, last: here };
  const moved = sample.progressM - last.progressM;
  const halted = track.haltS > 0;
  if (moved < (halted ? LEAVE_M : STILL_M)) {
    // Still, or drifting about the halt's place: its seconds up to the cap, the place kept where it began.
    const counted = Math.max(0, Math.min(dt, HALT_CAP_S - track.haltS));
    return { ...track, riddenS: track.riddenS + counted, haltS: track.haltS + dt, last: { ...here, progressM: last.progressM } };
  }
  // Riding off a halt, the seconds since its last counted fix are not all the metres took: those metres count at
  // the plan's pace where that is longer, so the rider is not taken as faster than they are.
  // The plan's seconds for those metres: a climb's more, a junction's wait passed included (a green light quicker
  // than the plan, a red one up to the halt's cap).
  const planned = sample.plan?.(last.progressM, sample.progressM) ?? moved / sample.paceMs;
  return {
    plannedS: track.plannedS + planned,
    riddenS: track.riddenS + (halted ? Math.max(dt, moved / sample.paceMs) : dt),
    metres: track.metres + moved,
    haltS: 0,
    last: here,
  };
}

/** How much faster than the plan the rider is going (above 1 faster, below 1 slower), eased in with distance. */
export function paceFactor(track: PaceTrack): number {
  if (track.metres < START_M || track.riddenS <= 0 || track.plannedS <= 0) return 1;
  const ratio = Math.min(MAX_FACTOR, Math.max(1 / MAX_FACTOR, track.plannedS / track.riddenS));
  const weight = Math.min(1, (track.metres - START_M) / (FULL_M - START_M));
  return 1 + (ratio - 1) * weight;
}

/** The clock time `seconds` from `nowMs`, rounded to the minute, in the device's own 12 or 24 hour clock: "6:42 AM", "18:42". */
export function arrivalClock(nowMs: number, seconds: number, locale?: string): string {
  const at = new Date(Math.round((nowMs + seconds * 1000) / 60_000) * 60_000);
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(at);
}

/**
 * When a planned route ends if the ride starts at `nowMs`, epoch ms, for the route summary's time (Stephen 2026-10-27:
 * "Add the anticipated end time to the starting screen"); null where leaving now is not what was planned or the
 * route's time is not the trip's. Not a transit plan (it waits on its timetable), a bikeshare one (the time leaves out
 * the walks to and from the docks); a Mass Ride's shows as any other's (the 2026-10-28 audit, P6); nor where the ride time chosen
 * (When) is not the time now: "weekend" chosen on a Tuesday, or Night in the morning. "When I'm planning" (null) is now.
 */
export function leaveNowArriveMs(
  route: { duration_s: number; preset?: string; transit?: unknown; bikeshare?: unknown } | null,
  nowMs: number,
  chosen: When | null,
): number | null {
  if (!route || route.transit || route.bikeshare) return null;
  if (chosen !== null && chosen !== whenAt(new Date(nowMs))) return null;
  return nowMs + route.duration_s * 1000;
}

/** That arrival in words: "arrive 8:27 AM" on screen; a screen reader hears it is an estimate, for leaving now. */
export function leaveNowArrival(arriveMs: number, locale?: string): { shown: string; said: string } {
  const time = arrivalClock(arriveMs, 0, locale);
  return { shown: t("arrive {time}", { time }), said: t("arriving about {time} if you leave now", { time }) };
}

/** The time to go, eased to the rider's own pace: each estimate divided by how much faster than the plan they ride. */
export function atPace(togo: ToGo, factor: number): ToGo {
  if (factor === 1) return togo;
  const at = (seconds: number | null) => (seconds === null ? null : seconds / factor);
  return { stop: togo.stop && { ...togo.stop, seconds: at(togo.stop.seconds) }, end: { ...togo.end, seconds: at(togo.end.seconds) } };
}
