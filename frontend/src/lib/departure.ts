/**
 * An infrequent departure on a transit plan (the owner, 2026-10-12: "For stations with infrequent
 * departure such as the MARC, when doing GO, make it clear when the next departure would be and if
 * cutting it close, put a timer"; and "Have it on the route").
 *
 * The API says which departure the trip takes (`transit.departure`, core.transit.departure): when it
 * leaves and from where, when the rider gets there as planned, the time to spare and the one after.
 * Here it becomes words, a countdown and the map's label, as plain functions of the time now so they
 * can be tested without a browser or a clock.
 *
 * The spare time counts down from the plan's moment: a rider who has not set off yet spends it
 * waiting. Under `CLOSE_S` to spare is "cutting it close": the countdown shows. Nothing here is a
 * live region; a screen reader hears the milestones only (`MILESTONES_S`), and a miss.
 */
import type { TimeSource, TransitDeparture } from "./api.ts";

/**
 * The word after every transit time, so a rider knows a timetable from a live time (the owner,
 * 2026-10-12: "Make it clear whether it's a schedule or live."): "7:42 am scheduled". Everything is
 * scheduled until live times arrive (v0.7), when the API says "live".
 */
export function sourceWord(departure: { source?: TimeSource | null }): TimeSource {
  return departure.source ?? "scheduled";
}

/** A departure's clock with its word: "7:42 am scheduled". */
export function departsSaid(departure: Pick<TransitDeparture, "departs" | "source">): string {
  return `${departure.departs} ${sourceWord(departure)}`;
}

/** Less than this to spare is cutting it close: the countdown shows (core.transit.CLOSE_S). */
export const CLOSE_S = 300;
/** Said once each, as the departure comes nearer: 10, 5 and 2 minutes. */
export const MILESTONES_S = [600, 300, 120] as const;

export interface Countdown {
  /** Seconds until the departure. */
  toDepartS: number;
  /** Seconds to spare at the stop, as planned less the time since the plan's moment. */
  spareS: number;
  close: boolean;
  missed: boolean;
}

// When each departure's answer reached this phone, by the phone's own clock (review TB-6).
const arrivedAt = new WeakMap<object, number>();

/** Mark when the plan holding `departure` arrived (requestRoute), so its countdown runs from then. */
export function noteArrived(departure: object, atMs: number): void {
  arrivedAt.set(departure, atMs);
}

/**
 * The countdown at `nowMs`. Counted from when the answer arrived, by the phone's clock, so a phone
 * clock that is wrong does not mark a fresh plan missed nor show spare time for a train gone (review
 * TB-6); the departure is that far after the plan's moment, as the server's clock says. A departure
 * with no arrival noted (one kept from before) is counted against the plan's moment, as before.
 */
export function countdown(departure: Pick<TransitDeparture, "departs_at" | "planned_at" | "spare_s">, nowMs: number): Countdown {
  const departs = Date.parse(departure.departs_at);
  const planned = Date.parse(departure.planned_at);
  const arrived = arrivedAt.get(departure);
  const elapsed = Math.max(0, (nowMs - (arrived ?? planned)) / 1000);
  const spareS = departure.spare_s - elapsed;
  const toDepartS = arrived === undefined ? (departs - nowMs) / 1000 : (departs - planned) / 1000 - elapsed;
  return { toDepartS, spareS, close: spareS < CLOSE_S, missed: spareS < 0 };
}

/** A count of seconds as the timer shows it: "04:09", "1:02:03"; never below zero. */
export function mmss(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}

/** An ISO local time as a clock, "7:36 am", read from the string itself (it carries Washington's offset). */
export function clockOf(iso: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso;
  const hour = Number(match[1]);
  return `${hour % 12 || 12}:${match[2]} ${hour < 12 ? "am" : "pm"}`;
}

function vehicleName(vehicle: string): string {
  const name = vehicle.replace(/^the /, "");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** The departure in words: "MARC Penn Line 7:42 am scheduled from Union Station. You arrive 7:36 am (6 min spare). Next after that: 8:15 am scheduled." */
export function departureText(departure: TransitDeparture): string {
  const from = departure.board_at ? ` from ${departure.board_at}` : "";
  const spare = Math.round(departure.spare_s / 60);
  const next = departure.next ? `Next after that: ${departure.next} ${sourceWord(departure)}.` : "No later one within the hour.";
  return `${vehicleName(departure.vehicle)} ${departsSaid(departure)}${from}. You arrive ${clockOf(departure.arrive_at)} (${spare} min spare). ${next}`;
}

/** The map's label at the boarding stop: the plan's words, or when cutting it close the countdown to the departure and the time to spare. */
export function mapLabel(departure: TransitDeparture, nowMs: number): string {
  const now = countdown(departure, nowMs);
  if (now.missed) return `${departure.system} ${departsSaid(departure)} · missed`;
  if (now.close) return `${departure.system} ${departsSaid(departure)} · in ${mmss(now.toDepartS)} · ${mmss(now.spareS)} spare`;
  return departure.label;
}

/** Within this many pixels of the start or end marker, the label goes to the other side of the stop. */
export const LABEL_CLEAR_PX = 56;

/**
 * Which side of the boarding stop the map's label goes: above it, unless the start or end marker is
 * near and above, then below, so the label never covers them (the owner: "must not collide with the
 * start/stop icons"). Screen pixels, y down.
 */
export function labelSide(board: { x: number; y: number }, ends: ReadonlyArray<{ x: number; y: number }>, clear = LABEL_CLEAR_PX): "above" | "below" {
  let nearest: { x: number; y: number } | null = null;
  let best = clear;
  for (const end of ends) {
    const d = Math.hypot(end.x - board.x, end.y - board.y);
    if (d <= best) {
      best = d;
      nearest = end;
    }
  }
  return nearest && nearest.y <= board.y ? "below" : "above";
}

/** The milestone crossed between two readings of the time to the departure, if any. */
export function milestone(beforeS: number, nowS: number): number | null {
  for (const mark of MILESTONES_S) if (beforeS > mark && nowS <= mark) return mark;
  return null;
}

export function milestoneSaid(departure: Pick<TransitDeparture, "system" | "departs" | "source">, mark: number): string {
  return `${departure.system} ${departsSaid(departure)} leaves in ${mark / 60} minutes.`;
}

export function missedSaid(departure: Pick<TransitDeparture, "system" | "departs" | "source">): string {
  return `You may miss the ${departure.system} ${departsSaid(departure)}. Planning the next departure.`;
}
