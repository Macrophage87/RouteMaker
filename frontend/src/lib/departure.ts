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
import { clockLocale, t } from "./i18n.ts";

/** The region's own clock: a departure is at the station's time, whatever the phone's zone (lib/arrival.ts arrivalClock too). */
export const ZONE = "America/New_York";

/**
 * The word after every transit time, so a rider knows a timetable from a live time (the owner,
 * 2026-10-12: "Make it clear whether it's a schedule or live."): "7:42 AM scheduled". Everything is
 * scheduled until live times arrive (v0.7), when the API says "live". In the language in force; the
 * API's own word is never shown.
 */
export function sourceWord(departure: { source?: TimeSource | null }): string {
  return departure.source === "live" ? t("live") : t("scheduled");
}

/** The places every sentence about a departure fills: its system, its clock and whether that is the timetable's. */
function departs(departure: Pick<TransitDeparture, "system" | "departs_at" | "source">): { system: string; time: string; source: string } {
  return { system: departure.system, time: clockOf(departure.departs_at), source: sourceWord(departure) };
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

const CLOCKS = new Map<string, Intl.DateTimeFormat>();

/**
 * An ISO time as the station's clock (Washington's time, whatever the phone's zone), in the phone's own 12 or 24
 * hour clock where it reads the app's language (lib/i18n.ts clockLocale, as lib/arrival.ts arrivalClock):
 * "7:36 AM", "19:36".
 */
export function clockOf(iso: string, locale: string | undefined = clockLocale()): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return iso;
  const key = locale ?? "";
  let format = CLOCKS.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(locale, { timeZone: ZONE, hour: "numeric", minute: "2-digit" });
    CLOCKS.set(key, format);
  }
  return format.format(at);
}

const WALL_CLOCKS = new Map<string, Intl.DateTimeFormat>();

/**
 * A time the API wrote in English words ("7:42 am", "12:05 pm": core.transit clock, where a step has no ISO time) on
 * the phone's own clock, as clockOf shows one: "7:42 AM", "19:42". Anything else comes back as it was.
 */
export function wallClockOf(text: string, locale: string | undefined = clockLocale()): string {
  const m = /^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$/i.exec(text.trim());
  if (!m) return text;
  const hour12 = Number(m[1]);
  const minute = Number(m[2]);
  if (hour12 < 1 || hour12 > 12 || minute > 59) return text;
  const hour = (hour12 % 12) + (m[3].toLowerCase() === "p" ? 12 : 0);
  const key = locale ?? "";
  let format = WALL_CLOCKS.get(key);
  if (!format) {
    // The time as written, on no zone's clock: UTC in and out.
    format = new Intl.DateTimeFormat(locale, { timeZone: "UTC", hour: "numeric", minute: "2-digit" });
    WALL_CLOCKS.set(key, format);
  }
  return format.format(Date.UTC(2000, 0, 1, hour, minute));
}

/**
 * The server's vehicle ("the MARC Penn Line", "bus B10", src/core/transitdata/systems.json "words") as the sentence
 * names it: a train by its own name, a bus as "Bus B10" in the language in force.
 */
export function vehicleName(vehicle: string): string {
  const bus = /^bus (.+)$/i.exec(vehicle);
  if (bus) return t("Bus {name}", { name: bus[1] });
  const name = vehicle.replace(/^the /, "");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/**
 * The departure in words, each sentence whole in the language in force: "MARC Penn Line 7:42 AM scheduled from Union
 * Station. You arrive 7:36 AM (6 min spare). Next after that: 8:15 AM scheduled." Its times are the API's ISO times
 * on the phone's clock, never the API's English ones.
 */
export function departureText(departure: TransitDeparture): string {
  const words = {
    vehicle: vehicleName(departure.vehicle),
    time: clockOf(departure.departs_at),
    source: sourceWord(departure),
    stop: departure.board_at ?? "",
    arrival: clockOf(departure.arrive_at),
    minutes: Math.round(departure.spare_s / 60),
  };
  const first = departure.board_at
    ? t("{vehicle} {time} {source} from {stop}. You arrive {arrival} ({minutes} min spare).", words)
    : t("{vehicle} {time} {source}. You arrive {arrival} ({minutes} min spare).", words);
  const next = departure.next_at
    ? t("Next after that: {time} {source}.", { time: clockOf(departure.next_at), source: sourceWord(departure) })
    : t("No later one within the hour.");
  return `${first} ${next}`;
}

/** The map's label at the boarding stop: the departure and its time to spare, or when cutting it close the countdown to it and the time to spare. */
export function mapLabel(departure: TransitDeparture, nowMs: number): string {
  const now = countdown(departure, nowMs);
  if (now.missed) return t("{system} {time} {source} · missed", departs(departure));
  if (now.close) return t("{system} {time} {source} · in {count} · {spare} spare", { ...departs(departure), count: mmss(now.toDepartS), spare: mmss(now.spareS) });
  return t("{system} {time} {source} · {minutes} min spare", { ...departs(departure), minutes: Math.round(departure.spare_s / 60) });
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

export function milestoneSaid(departure: Pick<TransitDeparture, "system" | "departs_at" | "source">, mark: number): string {
  return t("{system} {time} {source} leaves in {minutes} minutes.", { ...departs(departure), minutes: mark / 60 });
}

export function missedSaid(departure: Pick<TransitDeparture, "system" | "departs_at" | "source">): string {
  return t("You may miss the {system} {time} {source}. Planning the next departure.", departs(departure));
}
