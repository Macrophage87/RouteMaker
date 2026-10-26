/**
 * Arrival clock times on the ride screen (the owner, 2026-10-26: "Add estimated clock time of arrival to the ride."
 * and "Stops too"). The time to go is the route's own (its ride type's flat-road speed scaled by grade, plus the
 * junction delays: the API's duration over its distance, RideModel.paceMs), corrected by how the rider is actually
 * riding against that plan once they have ridden far enough for it to mean something.
 *
 * The correction is the ratio of the plan's seconds for the metres ridden to the seconds it took to ride them. A
 * halt counts up to HALT_CAP_S (a long light or a stop sign the plan allows for), not beyond it: a coffee stop or a
 * chat at a corner says nothing about the pace still to come. Time off route, paused or walking is not counted, and
 * a gap in fixes (a tunnel, the phone asleep) longer than GAP_S is left out.
 */

/** A halt counted up to this, in seconds. */
export const HALT_CAP_S = 90;
/** Fixes further apart than this, in seconds, are not one stretch of riding. */
export const GAP_S = 120;
/** Under this many metres a fix to the next is a halt. */
const STILL_M = 2;
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
  /** Seconds of the halt now going on. */
  haltS: number;
  /** The last sample counted from, or null. */
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
  /** The plan's pace on that line, metres a second. */
  paceMs: number | null;
  /** On the route and riding: not off route, paused, walking or arrived. */
  riding: boolean;
}

/** The track with one more fix. */
export function paceStep(track: PaceTrack, sample: PaceSample): PaceTrack {
  if (!sample.riding || sample.progressM === null || !(sample.paceMs && sample.paceMs > 0)) return { ...track, haltS: 0, last: null };
  const here = { atMs: sample.atMs, progressM: sample.progressM, line: sample.line };
  const last = track.last;
  const dt = last ? (sample.atMs - last.atMs) / 1000 : 0;
  if (!last || last.line !== sample.line || dt <= 0 || dt > GAP_S || sample.progressM < last.progressM - STILL_M) return { ...track, haltS: 0, last: here };
  const moved = sample.progressM - last.progressM;
  if (moved < STILL_M) {
    // Still: the halt's seconds up to the cap; the place stays the last one, so creeping adds up.
    const counted = Math.max(0, Math.min(dt, HALT_CAP_S - track.haltS));
    return { ...track, riddenS: track.riddenS + counted, haltS: track.haltS + dt, last: { ...here, progressM: last.progressM } };
  }
  return {
    plannedS: track.plannedS + moved / sample.paceMs,
    riddenS: track.riddenS + dt,
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
