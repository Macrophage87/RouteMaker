/**
 * The nearest water, restroom or Metro station by bike. The owner, 2026-10-10:
 * "Have the option to route to the nearest public water source, restroom, or
 * metro stop. Let people choose the three closest."
 *
 * The places are the ones the map already has: public water and restrooms from
 * the water layer's file (lib/waterRestrooms.ts, OpenStreetMap), with the
 * layer's own switches for portable toilets and untreated water; and the Metro
 * stations (lib/railData.ts), each at its bike entrance, the elevator where one
 * is listed, as a station's own End here uses. Metrorail only: MARC's stations
 * are left out.
 *
 * From where the rider is (or the map's center, or the plan's start), the
 * NEAREST_CANDIDATES nearest in straight lines go to the API (POST /api/nearest,
 * core.nearest), which answers how far each is to ride on the ride's own graph
 * and settings; the NEAREST_SHOWN nearest by bike are offered, each with its
 * distance and time, and the rider picks one: Ride here plans a route from where
 * they are to it, and Add as stop puts water or a restroom into the plan. When
 * the router gives no distances the list is by straight line, and says so.
 *
 * Plain data in, plain data out, so node --test runs all of it; the panel is
 * lib/nearestFinder.ts.
 */
import { describeError } from "./api.ts";
import { dialFields, type Dials } from "./dials.ts";
import { formatDistance, formatDuration } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";
import { bikeEntrance, entranceNote, linesLabel, type Station } from "./railStations.ts";
import { waterDetails, waterTitle, type WaterPoint, type WaterPrefs } from "./waterRestrooms.ts";

export type NearestKind = "water" | "restroom" | "metro";

/** The finder's buttons, in order. */
export const NEAREST_KINDS: ReadonlyArray<{ kind: NearestKind; label: string; noun: string; one: string }> = [
  { kind: "water", label: "Nearest water", noun: "water", one: "water" },
  { kind: "restroom", label: "Nearest restroom", noun: "restrooms", one: "restroom" },
  { kind: "metro", label: "Nearest Metro", noun: "Metro stations", one: "Metro station" },
];

/** "restrooms", or with `count` 1, "restroom". */
export const nounOf = (kind: NearestKind, count = 2): string => {
  const entry = NEAREST_KINDS.find((k) => k.kind === kind);
  return (count === 1 ? entry?.one : entry?.noun) ?? kind;
};

/** Water and restrooms can be a stop on the way; a Metro station is where a ride ends. */
export const stopsOnTheWay = (kind: NearestKind): boolean => kind !== "metro";

export interface NearestPlace {
  /** The OSM element ("n123") or the station's id ("metro-…"). */
  id: string;
  kind: NearestKind;
  /** Where a route to it goes. */
  point: LonLat;
  /** What it is, with its name: "Drinking water, Peirce Mill", "Dupont Circle". */
  title: string;
  /** Short sentences after the title: "Bottle filler.", "Red line." */
  details: string[];
}

/**
 * The water layer's points of one kind, as places. Water is drinking water, and
 * untreated water only while the layer's "Untreated water sources" switch is on;
 * restrooms are every type, portable and pit toilets only while that switch is on.
 * The finder lists what the map shows.
 */
export function waterPlaces(points: readonly WaterPoint[], kind: "water" | "restroom", prefs: WaterPrefs): NearestPlace[] {
  const keep =
    kind === "water"
      ? (p: WaterPoint) => p.water === "p" || (p.water === "n" && prefs.untreated)
      : (p: WaterPoint) => p.toilet !== undefined && (p.toilet !== "b" || prefs.basic);
  return points.filter(keep).map((p) => ({
    id: p.id,
    kind,
    point: [p.lon, p.lat],
    title: waterTitle(p),
    details: waterDetails(p),
  }));
}

/** The Metro's stations, each at its bike entrance; MARC-only stations are left out. */
export function metroPlaces(stations: readonly Station[]): NearestPlace[] {
  return stations
    .filter((station) => station.metro.length > 0)
    .map((station) => {
      const entrance = bikeEntrance(station);
      return {
        id: station.id,
        kind: "metro" as const,
        point: entrance.point,
        title: `${station.name} Metro station`,
        details: [`${linesLabel(station.metro)}.`, entranceNote(entrance.kind)],
      };
    });
}

/** How many of the nearest in straight lines are measured by bike: the API's limit (core.nearest.MAX_PLACES) is 10. */
export const NEAREST_CANDIDATES = 8;
/** How many are offered (the owner: "Let people choose the three closest"). */
export const NEAREST_SHOWN = 3;

/** The `n` places nearest `from` in straight lines, nearest first; a tie keeps the given order. */
export function nearestInStraightLine(from: LonLat, places: readonly NearestPlace[], n = NEAREST_CANDIDATES): NearestPlace[] {
  return places
    .map((place, index) => ({ place, index, m: haversineM(from, place.point) }))
    .sort((a, b) => a.m - b.m || a.index - b.index)
    .slice(0, n)
    .map(({ place }) => place);
}

/** What the API answers (core.api.NearestOut). */
export interface NearestAnswer {
  by: "riding" | "straight_line";
  places: Array<{ distance_m: number | null; time_s: number | null }>;
}

export type NearestResult = { ok: true; answer: NearestAnswer } | { ok: false; message: string };

function looksLikeAnswer(value: unknown, count: number): value is NearestAnswer {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<NearestAnswer>;
  return (v.by === "riding" || v.by === "straight_line") && Array.isArray(v.places) && v.places.length === count;
}

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

/**
 * Ask the API how far each place is to ride from `from`, on this ride's preset and dials.
 * Neither the weight nor the loop is sent: the distances use neither. Where the rider is
 * goes only in this request, as any point of a route does (OWNER-DECISIONS 395).
 */
export async function requestNearest(
  from: LonLat,
  places: readonly NearestPlace[],
  preset: PresetId,
  dials: Dials,
  fetchImpl: FetchLike = (url, init) => fetch(url, init),
): Promise<NearestResult> {
  let response: Response;
  try {
    response = await fetchImpl("/api/nearest", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        points: [from, ...places.map((place) => place.point)],
        preset,
        ...dialFields({ ...dials, systemWeightKg: undefined, targetDistanceM: undefined, loop: false }),
      }),
    });
  } catch {
    return { ok: false, message: "The search did not get through. Check your connection and try again." };
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok && looksLikeAnswer(body, places.length)) return { ok: true, answer: body };
  const error = describeError(response.ok ? 500 : response.status, body, response.headers.get("Retry-After"));
  return { ok: false, message: error.message };
}

export interface Nearby {
  place: NearestPlace;
  /** Metres: by bike, or in a straight line when `byBike` is false. */
  distanceM: number;
  /** Riding time, seconds; null in a straight line. */
  timeS: number | null;
  byBike: boolean;
}

/**
 * The `n` nearest by the answer's distances, nearest first; a place the router found
 * no way to is left out. A tie keeps the straight-line order the places were sent in.
 */
export function rankNearest(places: readonly NearestPlace[], answer: NearestAnswer, n = NEAREST_SHOWN): Nearby[] {
  const byBike = answer.by === "riding";
  const out: Array<Nearby & { index: number }> = [];
  places.forEach((place, index) => {
    const cell = answer.places[index];
    const m = cell?.distance_m;
    if (typeof m !== "number" || !Number.isFinite(m)) return;
    const t = cell.time_s;
    out.push({ place, index, distanceM: m, timeS: byBike && typeof t === "number" && Number.isFinite(t) ? t : null, byBike });
  });
  return out
    .sort((a, b) => a.distanceM - b.distanceM || a.index - b.index)
    .slice(0, n)
    .map(({ index: _index, ...rest }) => rest);
}

/** How far, in words: "0.6 mi (1.0 km) by bike, about 4 min" or "0.4 mi (0.6 km) in a straight line". */
export function howFar(item: Nearby): string {
  if (!item.byBike) return `${formatDistance(item.distanceM)} in a straight line`;
  const time = item.timeS === null ? "" : `, about ${formatDuration(item.timeS)}`;
  return `${formatDistance(item.distanceM)} by bike${time}`;
}

/** One line of the list: "Drinking water, Peirce Mill: 0.6 mi (1.0 km) by bike, about 4 min. Bottle filler. Free." */
export function nearbyText(item: Nearby): string {
  return [`${item.place.title}: ${howFar(item)}.`, ...item.place.details].join(" ");
}

export const STRAIGHT_LINE_NOTE = "The router's riding distances were not available, so these are by straight-line distance.";

/** Where the search was from, in words, for the status line. */
export type NearestFrom = "location" | "centre" | "start";
export const FROM_LABEL: Record<NearestFrom, string> = {
  location: "My location",
  centre: "The map's center",
  start: "The start of the plan",
};
const FROM_WORDS: Record<NearestFrom, string> = {
  location: "your location",
  centre: "the map's center",
  start: "the start of the plan",
};

/** The status line once the list is in: how many, of what, from where, and how measured. */
export function foundSaid(kind: NearestKind, from: NearestFrom, items: readonly Nearby[]): string {
  const noun = nounOf(kind);
  if (items.length === 0) return `No ${noun} could be reached by bike from ${FROM_WORDS[from]}.`;
  const how = items[0].byBike ? "by bike" : "in a straight line";
  const lead =
    items.length === 1
      ? `The nearest ${nounOf(kind, 1)} ${how} from ${FROM_WORDS[from]}.`
      : `The ${items.length} nearest ${noun} ${how} from ${FROM_WORDS[from]}, nearest first.`;
  return items[0].byBike ? lead : `${lead} ${STRAIGHT_LINE_NOTE}`;
}

export const findingSaid = (kind: NearestKind): string => `Finding the nearest ${nounOf(kind)}.`;
export const noneKnownSaid = (kind: NearestKind): string => `No ${nounOf(kind)} are on the map to search.`;
export const WATER_NOT_LOADED = "Water and restrooms are unavailable for now; try again shortly.";
