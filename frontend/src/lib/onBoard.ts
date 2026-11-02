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

/** Where a fix puts the rider: the last stop reached and whether on board; null for a fix that says nothing here. */
function byFix(leg: OnBoardLeg, fix: RideFix): { at: number; boarded: boolean } | null {
  const accuracy = fix.accuracyM > 0 ? fix.accuracyM : 0;
  if (accuracy > ROUGH_FIX_M) return null;
  const line = along(leg);
  const found = snap(line, fix.point);
  if (!found || found.offM > Math.max(OFF_LINE_M, 2 * accuracy)) return null;
  const reach = Math.max(AT_STOP_M, accuracy / 2);
  let at = 0;
  line.along.forEach((m, i) => {
    if (m <= found.alongM + reach) at = i;
  });
  const boarded = haversineM(fix.point, leg.stops[0].point) > Math.max(BOARDED_M, accuracy) && found.alongM > 0;
  return { at, boarded };
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
 * order, through the rider's outputs (the voice, a screen reader).
 */
export function onBoardStep(leg: OnBoardLeg, state: OnBoardState, now: number, fix: RideFix | null = null): { state: OnBoardState; said: string[] } {
  if (state.done) return { state, said: [] };
  const next: OnBoardState = { ...state };
  const said: string[] = [];
  const placed = fix ? byFix(leg, fix) : null;
  let estimated = false;
  if (placed) {
    next.fixAt = now;
    if (placed.boarded && next.boardedAt === null) next.boardedAt = now;
    if (next.boardedAt !== null) next.at = Math.max(next.at, placed.at);
  } else if (now - (next.fixAt ?? next.since) >= STALE_MS) {
    // No fix that places the rider for a while (underground with no Wi-Fi): the timetable, from the boarding seen,
    // else from the planned wait at the stop.
    if (next.boardedAt === null && now - next.since >= leg.waitS * 1000 + STALE_MS) next.boardedAt = next.since + leg.waitS * 1000;
    if (next.boardedAt !== null) {
      const clock = byClock(leg, next.boardedAt, now);
      if (clock > next.at) {
        next.at = clock;
        estimated = true;
      }
    }
  }
  const last = leg.stops.length - 1;
  const off = leg.stops[last].name;
  if (next.boardedAt !== null && next.at >= last - 1 && !next.saidNext && next.at < last) {
    next.saidNext = true;
    said.push(leg.bus ? t("Next stop: {name}. Press the stop button to get off there.", { name: off }) : t("Next stop: {name}. Get off there.", { name: off }));
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
