/**
 * Rail stations closed for the day, on the map (the owner, 2026-10-12: "If a station is closed, put a
 * strike through and grey it out on the map"; refined: only a station with no service all day - a
 * weekend or holiday its line does not run, or a planned all-day closure in the published timetable -
 * not one outside its hours on a day it runs).
 *
 * The API says which (GET /api/transit/closures, core.transit.closed_stations), by system, name and
 * point. Here they are matched to the map's stations (railStations.ts): a Metro closure to the nearest
 * station with Metro lines, a MARC one to the nearest Penn Line station, each within MATCH_M. A station
 * that two systems serve (Union Station, New Carrollton) is closed only when every system it shows is.
 * Colour is never the only cue: the icon is struck through and the name reads "(closed)", and the
 * station's card and lists say "Camden Station, closed: no MARC weekend service".
 */
import type { ClosedStation } from "./api.ts";
import { haversineM } from "./geo.ts";
import { visibleLines, type RailVisibility, type Station } from "./railStations.ts";

/** A closure further than this from every station of its system is not one the map draws. */
export const MATCH_M = 400;

/** Per station id, the reason each of its systems is closed. */
export interface StationClosure {
  metro?: string;
  marc?: string;
}
export type RailClosures = ReadonlyMap<string, StationClosure>;

export const NO_CLOSURES: RailClosures = new Map();

function systemOf(closed: Pick<ClosedStation, "system">): "metro" | "marc" | null {
  if (closed.system === "Metro") return "metro";
  if (closed.system === "MARC") return "marc";
  return null;
}

/** The closures the API gave, keyed by the map's station ids. */
export function matchClosures(stations: readonly Station[], closed: readonly ClosedStation[]): RailClosures {
  const out = new Map<string, StationClosure>();
  for (const item of closed) {
    const system = systemOf(item);
    if (!system) continue;
    let best: Station | null = null;
    let bestM = MATCH_M;
    for (const station of stations) {
      if (system === "metro" ? station.metro.length === 0 : !station.penn) continue;
      const m = haversineM(station.point, [item.lon, item.lat]);
      if (m <= bestM) {
        best = station;
        bestM = m;
      }
    }
    if (!best) continue;
    out.set(best.id, { ...out.get(best.id), [system]: item.reason });
  }
  return out;
}

/**
 * Why a station is closed with the toggles as they are, or null when it is open: every system it
 * shows must be closed ("no MARC weekend service"; two systems' reasons joined by "and").
 */
export function closedReason(station: Station, visibility: RailVisibility, closures: RailClosures): string | null {
  const closure = closures.get(station.id);
  if (!closure) return null;
  const lines = visibleLines(station, visibility);
  if (lines.length === 0) return null;
  const reasons: string[] = [];
  if (lines.some((line) => line !== "penn")) {
    if (!closure.metro) return null;
    reasons.push(closure.metro);
  }
  if (lines.includes("penn")) {
    if (!closure.marc) return null;
    reasons.push(closure.marc);
  }
  return reasons.join(" and ");
}

/** The map's label for a closed station: words, so colour is not the only cue. */
export function closedLabel(name: string): string {
  return `${name} (closed)`;
}

function washingtonParts(nowMs: number): { day: Date; hour: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(nowMs));
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { day: new Date(Date.UTC(get("year"), get("month") - 1, get("day"))), hour: get("hour") };
}

/** The service day a closure list is for, in Washington: before 3 am it is still the day before. */
export function serviceDayOf(nowMs: number): string {
  const { day, hour } = washingtonParts(nowMs);
  if (hour < 3) day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

/**
 * When the closure list is asked again: at 3 am, when the service day turns over, and at midnight
 * too, since from then a station whose line runs on the new date is not closed (its first train is
 * on its card; core.transit.closed_stations).
 */
export function closuresDayOf(nowMs: number): string {
  const { day } = washingtonParts(nowMs);
  return `${serviceDayOf(nowMs)} ${day.toISOString().slice(0, 10)}`;
}

type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

function looksLikeClosures(body: unknown): body is { service_day: string; stations: ClosedStation[] } {
  if (!body || typeof body !== "object") return false;
  const stations = (body as { stations?: unknown }).stations;
  return (
    Array.isArray(stations) &&
    stations.every(
      (s) =>
        s &&
        typeof s.name === "string" &&
        typeof s.system === "string" &&
        typeof s.reason === "string" &&
        Number.isFinite(s.lon) &&
        Number.isFinite(s.lat),
    )
  );
}

/**
 * Today's closed stations, or null when the server has no timetables or does not answer: nothing
 * is greyed, and the caller asks again later (a failure is not "no station closed today").
 */
export async function requestClosures(options: { fetchImpl?: FetchLike; signal?: AbortSignal } = {}): Promise<ClosedStation[] | null> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  try {
    const response = await fetchImpl("/api/transit/closures", { headers: { Accept: "application/json" }, signal: options.signal });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return looksLikeClosures(body) ? body.stations : null;
  } catch {
    return null;
  }
}
