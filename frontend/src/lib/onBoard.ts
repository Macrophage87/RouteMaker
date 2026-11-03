/**
 * Stop by stop on transit (Stephen, 2026-11-02: "stop by stop directions for transit"). Once the ride to a boarding
 * ends, the ride screen follows the train or bus: the stops left, the next one, and "Next stop: Union Station. Get off
 * there." one stop before the rider's, then "Get off here". A bus says to press the stop button.
 *
 * Where the rider is comes from the phone's location, rough fixes too: underground the phone often finds itself by
 * Wi-Fi (Stephen, 2026-11-02: "I often see the location, I believe through wifi"), a few hundred feet out, and Metro
 * stations are half a mile and more apart, so a fix up to ROUGH_FIX_M counts here (turn-by-turn wants POOR_FIX_M).
 * With no fix for STALE_MS, the timetable says where the train should be: the step's scheduled seconds between stops,
 * from when the rider boarded (or, never seen boarding, from the planned wait after reaching the stop). The stops
 * only ever move on, never back.
 */
import type { TransitStep, TransitStop } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import { lineAlong, snap, type RideFix } from "./navigate.ts";

/** The roughest fix that places the rider among the stops: a Wi-Fi fix underground. */
export const ROUGH_FIX_M = 500;
/** No usable fix for this long: the timetable places the train. */
export const STALE_MS = 90_000;
/** Farther than this (or the fix's own accuracy) from the boarding stop and on the line: on board. */
export const BOARDED_M = 400;
/** A stop is reached within this of it along the line (or half the fix's accuracy, if more). */
export const AT_STOP_M = 150;
/** Farther than this (or twice the fix's accuracy) from the line: the fix is not on this ride. */
export const OFF_LINE_M = 600;

/** A transit step to follow: its stops (boarding first, the stop to get off last), its line and way. */
export interface OnBoardLeg {
  stops: TransitStop[];
  /** "Red Line", "bus B10": as the card's badge. */
  line: string;
  toward: string | null;
  bus: boolean;
  /** The planned wait at the boarding stop (seconds), for the timetable's guess at when the rider boarded. */
  waitS: number;
}

export interface OnBoardState {
  /** When following began (the rider reached the boarding stop, or the walk to it ended). */
  since: number;
  /** When the rider was seen on board, or the timetable's guess; null while waiting. */
  boardedAt: number | null;
  /** The last stop reached, by its place in `stops` (0: the boarding stop). */
  at: number;
  /** The last usable fix's time. */
  fixAt: number | null;
  saidNext: boolean;
  saidOff: boolean;
  /** The stop to get off at is reached: the leg is done. */
  done: boolean;
  /** The last rough fix's place, which the next must agree with (byFix's `sure`). */
  pending?: { at: number; boarded: boolean } | null;
}

/** A transit step as one to follow; null without at least two stops (an older API). */
export function onBoardLeg(step: TransitStep): OnBoardLeg | null {
  const stops = step.stops ?? [];
  if (stops.length < 2) return null;
  const line = step.lines.length > 0 ? step.lines.join(" / ") : (step.system ?? "");
  return { stops, line, toward: step.toward ?? null, bus: step.mode === "bus", waitS: step.wait_s };
}

export function onBoardStart(now: number): OnBoardState {
  return { since: now, boardedAt: null, at: 0, fixAt: null, saidNext: false, saidOff: false, done: false };
}

function along(leg: OnBoardLeg): { coordinates: LonLat[]; along: Float64Array } {
  const coordinates = leg.stops.map((s) => s.point);
  return { coordinates, along: lineAlong(coordinates) };
}

/** The fastest a train is taken to go between fixes, for the window a fix is looked for in (metres a second). */
export const TRAIN_MS = 30;
/** The window reaches this far ahead of the last stop reached, plus TRAIN_MS for every second since the last fix. */
const AHEAD_M = 1000;
/** And this far behind it. */
const BEHIND_M = 300;

interface Placed {
  at: number;
  boarded: boolean;
  /** A fix good enough to act on alone; a rougher one moves the stops on only where the one before agrees. */
  sure: boolean;
}

/**
 * Where a fix puts the rider: the last stop reached and whether on board; null for a fix that says nothing here. It is
 * looked for near where the rider was (a window from the last stop reached, growing with the time since the last fix),
 * so a stray Wi-Fi fix far down the line, or on a bus's way back along the same street, is not taken.
 */
function byFix(leg: OnBoardLeg, state: OnBoardState, fix: RideFix, now: number): Placed | null {
  const accuracy = fix.accuracyM > 0 ? fix.accuracyM : 0;
  if (accuracy > ROUGH_FIX_M) return null;
  const line = along(leg);
  const from = line.along[state.at];
  const gapS = Math.max(0, (now - (state.fixAt ?? state.since)) / 1000);
  const found = snap(line, fix.point, from - BEHIND_M, from + AHEAD_M + TRAIN_MS * gapS, 15, from);
  if (!found || found.offM > Math.max(OFF_LINE_M, 2 * accuracy)) return null;
  let at = 0;
  line.along.forEach((m, i) => {
    // A stop is reached within AT_STOP_M of it (half a rough fix's accuracy), never more than 40% of the way from the
    // stop before: stops a block apart are not all reached at once.
    const gap = i > 0 ? m - line.along[i - 1] : Infinity;
    if (m <= found.alongM + Math.min(Math.max(AT_STOP_M, accuracy / 2), 0.4 * gap)) at = i;
  });
  const boarded = at >= 1 || (haversineM(fix.point, leg.stops[0].point) > Math.max(BOARDED_M, accuracy) && found.alongM > 0);
  return { at, boarded, sure: accuracy <= AT_STOP_M };
}

/** Where the timetable puts the train `now`: the last stop it has left or reached. */
function byClock(leg: OnBoardLeg, boardedAt: number, now: number): number {
  const s = (now - boardedAt) / 1000;
  let at = 0;
  leg.stops.forEach((stop, i) => {
    if (stop.after_s <= s) at = i;
  });
  return at;
}

/**
 * A fix (or none: the clock alone, from the ride screen's timer) into the leg. `said`: what the ride says now, in
 * order, through the rider's outputs (the voice, a screen reader). A rough fix alone never brings the stop to get off
 * nearer than two stops: the next one must agree before "Next stop" or "Get off here" is said.
 */
export function onBoardStep(leg: OnBoardLeg, state: OnBoardState, now: number, fix: RideFix | null = null): { state: OnBoardState; said: string[] } {
  if (state.done) return { state, said: [] };
  const next: OnBoardState = { ...state };
  const said: string[] = [];
  const last = leg.stops.length - 1;
  const placed = fix ? byFix(leg, state, fix, now) : null;
  let estimated = false;
  if (placed) {
    next.fixAt = now;
    const pending = state.pending ?? null;
    const agreed = placed.sure || (pending !== null && pending.boarded && placed.boarded);
    const at = placed.sure ? placed.at : pending && agreed ? Math.min(pending.at, placed.at) : Math.min(placed.at, last - 2);
    if (placed.boarded && agreed && next.boardedAt === null) next.boardedAt = now;
    if (next.boardedAt !== null) next.at = Math.max(next.at, at);
    next.pending = placed.sure ? null : { at: placed.at, boarded: placed.boarded };
  } else if (now - (next.fixAt ?? next.since) >= STALE_MS) {
    // No fix that places the rider for a while (underground with no Wi-Fi): the timetable, from the boarding seen,
    // else from the planned wait at the stop, or the last fix there if later (a train missed).
    const planned = next.since + leg.waitS * 1000;
    if (next.boardedAt === null && now - planned >= STALE_MS) next.boardedAt = Math.max(planned, next.fixAt ?? 0);
    if (next.boardedAt !== null) {
      const clock = byClock(leg, next.boardedAt, now);
      if (clock > next.at) {
        next.at = clock;
        estimated = true;
      }
    }
  }
  const off = leg.stops[last].name;
  if (next.boardedAt !== null && next.at >= last - 1 && !next.saidNext && next.at < last) {
    next.saidNext = true;
    if (estimated) said.push(t("Next stop should be {name}, by the timetable. Get off there.", { name: off }));
    else said.push(leg.bus ? t("Next stop: {name}. Press the stop button to get off there.", { name: off }) : t("Next stop: {name}. Get off there.", { name: off }));
  }
  if (next.boardedAt !== null && next.at >= last) {
    next.done = true;
    next.saidNext = true;
    if (!next.saidOff) {
      next.saidOff = true;
      said.push(estimated ? t("{name} should be about now, by the timetable. Get off there.", { name: off }) : t("Get off here: {name}.", { name: off }));
    }
  }
  return { state: next, said };
}

/** The card's lines: the stops still ahead, the next one marked; and how many are left. */
export function onBoardRows(leg: OnBoardLeg, state: OnBoardState): { name: string; passed: boolean; next: boolean; off: boolean }[] {
  const last = leg.stops.length - 1;
  const boarded = state.boardedAt !== null;
  return leg.stops.map((stop, i) => ({
    name: stop.name,
    passed: boarded ? i <= state.at && i < last : false,
    next: boarded && i === state.at + 1,
    off: i === last,
  }));
}

/** "3 stops left" from where the rider is (from the boarding stop while waiting). */
export function stopsLeftText(leg: OnBoardLeg, state: Pick<OnBoardState, "at">): string {
  const left = leg.stops.length - 1 - state.at;
  return left === 1 ? t("1 stop left") : t("{count} stops left", { count: left });
}
