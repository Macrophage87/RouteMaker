/**
 * A rail station's times, in its card (Stephen, 2026-10-12: "In the metro and marc icons on the map,
 * put either the headways for metro or in the case of MARC when the next train would be in each
 * direction"). Not drawn on the map: said in the station's card when it is tapped, clicked or opened
 * from the keyboard (the road info panel's nearby station), one line per transit line:
 *
 * - a frequent line (Metro, Light RailLink, Metro SubwayLink): "🔴 Red Line: every 8 min, scheduled";
 * - a commuter line (MARC, VRE): its next train each way, "🚆Penn to Baltimore 5:42 pm, to Union
 *   Station 6:10 pm, scheduled";
 * - none left: "no more trains today" (that way), or "no trains today" for a line not running today.
 *
 * Every time is scheduled (the timetable, or Metro's typical one), in Washington's time, as the API
 * gives it (GET /api/transit/station-times; core.transit.station_times). The marks are the shared
 * transitMarks.ts's, aria-hidden: a screen reader hears the words instead ("Red Line every 8
 * minutes, scheduled"). Where the server has no timetable, or does not answer, the card has no times.
 */
import type { StationLineTime, StationTimes } from "./api.ts";
import type { LonLat } from "./geo.ts";
import type { RailVisibility } from "./railStations.ts";
import { lineMark } from "./transitMarks.ts";

/** The word every time carries until live times come (v0.7). */
export const SCHEDULED_WORD = "scheduled";
/** The list's name for a screen reader. */
export const TIMES_LABEL = "Trains, scheduled";
/** How long an answer is kept: the server's own Cache-Control. */
export const TIMES_TTL_MS = 60_000;

/** One line of the card: what shows (aria-hidden, with its emoji) and what a screen reader says. */
export interface TimesRow {
  key: string;
  shown: string;
  spoken: string;
}

/** The lines of the systems the map shows: Metro's with the Metro toggle, MARC's with the MARC one. */
export function shownLines(lines: readonly StationLineTime[], visibility: RailVisibility): StationLineTime[] {
  return lines.filter((line) => (line.system === "Metro" ? visibility.metro : line.system === "MARC" ? visibility.marc : true));
}

/** "Union Station MARC" is "Union Station" in a MARC line's card. */
function place(toward: string, system: string): string {
  const suffix = ` ${system}`;
  return toward.endsWith(suffix) ? toward.slice(0, -suffix.length) : toward;
}

function noneWords(line: StationLineTime): string {
  return line.today ? "no more trains today" : "no trains today";
}

/** The card's lines, one per transit line, in the API's order (its systems, then its routes). */
export function stationTimeRows(lines: readonly StationLineTime[]): TimesRow[] {
  const groups = new Map<string, StationLineTime[]>();
  for (const line of lines) {
    const key = `${line.system}|${line.line}`;
    groups.set(key, [...(groups.get(key) ?? []), line]);
  }
  const rows: TimesRow[] = [];
  for (const [key, group] of groups) {
    const { system, line } = group[0];
    const mark = lineMark(system, line);
    const every = group.find((item) => item.kind === "every" && item.every_min !== null);
    let shownParts: string[];
    let spokenParts: string[];
    if (every && every.every_min !== null) {
      const n = every.every_min;
      shownParts = [`every ${n} min`];
      spokenParts = [`every ${n} ${n === 1 ? "minute" : "minutes"}`];
    } else {
      shownParts = group.map((item) => {
        if (item.kind === "next" && item.toward && item.time) return `to ${place(item.toward, system)} ${item.time}`;
        return item.toward ? `to ${place(item.toward, system)}: ${noneWords(item)}` : noneWords(item);
      });
      spokenParts = shownParts;
    }
    const timed = group.some((item) => item.kind === "every" || item.kind === "next");
    const tail = timed ? `, ${SCHEDULED_WORD}` : "";
    const body = shownParts.join(", ") + tail;
    const said = spokenParts.join(", ") + tail;
    // "🚆Penn" names its line in the mark; "🔴" does not, so the line's name follows it.
    const namedInMark = /[A-Za-z]/.test(mark.mark);
    const startsWithTo = body.startsWith("to ");
    const shown = namedInMark ? `${mark.mark}${startsWithTo ? " " : ": "}${body}` : `${mark.mark} ${mark.spoken}: ${body}`;
    const spoken = `${mark.spoken}${startsWithTo || said.startsWith("every") ? " " : ": "}${said}`;
    rows.push({ key, shown, spoken });
  }
  return rows;
}

type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

function looksLikeTimes(body: unknown): body is StationTimes {
  if (!body || typeof body !== "object") return false;
  const lines = (body as { lines?: unknown }).lines;
  return (
    Array.isArray(lines) &&
    lines.every(
      (l) =>
        l &&
        typeof l.system === "string" &&
        typeof l.line === "string" &&
        (l.kind === "every" || l.kind === "next" || l.kind === "none") &&
        (l.every_min === null || Number.isFinite(l.every_min)) &&
        (l.toward === null || typeof l.toward === "string") &&
        (l.time === null || typeof l.time === "string"),
    )
  );
}

const cache = new Map<string, { atMs: number; value: StationTimes | null }>();

function keyOf(point: LonLat): string {
  return `${point[0].toFixed(5)},${point[1].toFixed(5)}`;
}

/** The URL for a station's times now: the station's own point, so the browser's cache serves a second look. */
export function stationTimesUrl(point: LonLat): string {
  const [lon, lat] = point.map((v) => v.toFixed(5));
  return `/api/transit/station-times?lon=${lon}&lat=${lat}`;
}

/** The times last fetched for a station within the minute, null for a fetch that failed, else undefined. */
export function cachedStationTimes(point: LonLat, nowMs = Date.now()): StationTimes | null | undefined {
  const hit = cache.get(keyOf(point));
  return hit && nowMs - hit.atMs < TIMES_TTL_MS ? hit.value : undefined;
}

/**
 * A station's times now, or null when the server has none (no timetable installed, or no answer):
 * the card then shows no times. Kept for a minute, a failure too, so a card opened again asks once.
 */
export async function requestStationTimes(
  point: LonLat,
  options: { fetchImpl?: FetchLike; signal?: AbortSignal; nowMs?: number } = {},
): Promise<StationTimes | null> {
  const nowMs = options.nowMs ?? Date.now();
  const cached = cachedStationTimes(point, nowMs);
  if (cached !== undefined) return cached;
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  let value: StationTimes | null = null;
  try {
    const response = await fetchImpl(stationTimesUrl(point), { headers: { Accept: "application/json" }, signal: options.signal });
    if (response.ok) {
      const body: unknown = await response.json();
      value = looksLikeTimes(body) ? body : null;
    }
  } catch {
    // An aborted request is not remembered: the next card asks again.
    if (options.signal?.aborted) return null;
  }
  cache.set(keyOf(point), { atMs: nowMs, value });
  return value;
}

/** For tests: forget every answer. */
export function clearStationTimes(): void {
  cache.clear();
}
