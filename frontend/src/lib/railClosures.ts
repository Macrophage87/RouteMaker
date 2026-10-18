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
import type { ClosedStation, StationAlert } from "./api.ts";
import { haversineM } from "./geo.ts";
import { visibleLines, type RailVisibility, type Station, type StationBadges } from "./railStations.ts";

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
 * WMATA's badges, keyed by the map's station ids (the owner, 2026-10-18: "Put a little notice marker on
 * all the stations that have alerts", "For elevator out, use an X'd out elevator icon"): each to the
 * nearest station with Metro lines within MATCH_M.
 */
export function matchAlerts(stations: readonly Station[], alerts: readonly StationAlert[]): ReadonlyMap<string, StationBadges> {
  const out = new Map<string, StationBadges>();
  for (const item of alerts) {
    let best: Station | null = null;
    let bestM = MATCH_M;
    for (const station of stations) {
      if (station.metro.length === 0) continue;
      const m = haversineM(station.point, [item.lon, item.lat]);
      if (m <= bestM) {
        best = station;
        bestM = m;
      }
    }
    if (!best) continue;
    const had = out.get(best.id);
    out.set(best.id, { alert: item.alert || had?.alert === true, elevatorOut: item.elevator_out || had?.elevatorOut === true });
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

/**
 * A station's badges with the alert added where its Metro is closed but it is not struck through, as at
 * Union Station with MARC still running: the map then still says something is wrong there.
 */
export function withMetroClosed(badges: StationBadges | null, station: Station, visibility: RailVisibility, closures: RailClosures): StationBadges | null {
  if (!closures.get(station.id)?.metro || closedReason(station, visibility, closures) !== null) return badges;
  if (!visibleLines(station, visibility).some((line) => line !== "penn")) return badges;
  return { alert: true, elevatorOut: badges?.elevatorOut === true };
}

/** The map's label for a closed station: words, so colour is not the only cue. */
export function closedLabel(name: string): string {
  return `${name} (closed)`;
}

/**
 * How often the page asks again while in view: WMATA's closures and badges change within the day (the
 * server keeps its reading a minute), and the timetable's day turns over at midnight and 3 am.
 */
export const RAIL_STATUS_MS = 5 * 60_000;

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

/** The answer's badges, the well-formed ones; none from an older server that sends no list. */
function alertsOf(body: unknown): StationAlert[] {
  const alerts = (body as { alerts?: unknown }).alerts;
  if (!Array.isArray(alerts)) return [];
  return alerts.filter(
    (a): a is StationAlert =>
      !!a &&
      typeof a.name === "string" &&
      typeof a.alert === "boolean" &&
      typeof a.elevator_out === "boolean" &&
      Number.isFinite(a.lon) &&
      Number.isFinite(a.lat),
  );
}

export interface RailStatus {
  stations: ClosedStation[];
  alerts: StationAlert[];
}

/**
 * Today's closed stations and WMATA's badges, or null when the server has no timetables or does not
 * answer: nothing is greyed, and the caller asks again later (a failure is not "no station closed today").
 */
export async function requestClosures(options: { fetchImpl?: FetchLike; signal?: AbortSignal } = {}): Promise<RailStatus | null> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  try {
    const response = await fetchImpl("/api/transit/closures", { headers: { Accept: "application/json" }, signal: options.signal });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return looksLikeClosures(body) ? { stations: body.stations, alerts: alertsOf(body) } : null;
  } catch {
    return null;
  }
}
