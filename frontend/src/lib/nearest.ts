/**
 * The nearest water, restroom or Metro station by bike. The owner, 2026-10-10:
 * "Have the option to route to the nearest public water source, restroom, or
 * metro stop. Let people choose the three closest."
 *
 * The places are the ones the map already has: drinking water and restrooms of
 * every type from the water layer's file (lib/waterRestrooms.ts, OpenStreetMap;
 * untreated water is left out: a rider asking for water wants to drink it); and the Metro
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
import { detourOf, projector, type RouteForDetour } from "./food.ts";
import { formatDistance, formatDuration, formatExtra, milesFigure } from "./format.ts";
import { MAX_POINTS, haversineM, type LonLat } from "./geo.ts";
import { LOCATE_MESSAGES, LOCATION_OUTSIDE, type Fix, type LocateResult } from "./geolocation.ts";
import { twoPointsOnly, type PresetId } from "./presets.ts";
import { entranceNote, stationEntrance, linesLabel, type Station } from "./railStations.ts";
import { waterDetails, waterTitle, type WaterPoint } from "./waterRestrooms.ts";
import { t } from "./i18n.ts";

export type NearestKind = "water" | "restroom" | "metro";

/** The finder's buttons, in order. */
export const NEAREST_KINDS: ReadonlyArray<{ kind: NearestKind; label: string; noun: string; one: string }> = [
  // Short, under the sheet's "Nearest" heading (the owner, 2026-10-18: "reduce the verbosity").
  { kind: "water", label: t("Water"), noun: t("water"), one: t("water") },
  { kind: "restroom", label: t("Restroom"), noun: t("restrooms"), one: t("restroom") },
  { kind: "metro", label: t("Metro"), noun: t("Metro stations"), one: t("Metro station") },
];

/** "restrooms", or with `count` 1, "restroom". */
export const nounOf = (kind: NearestKind, count = 2): string => {
  const entry = NEAREST_KINDS.find((k) => k.kind === kind);
  return (count === 1 ? entry?.one : entry?.noun) ?? kind;
};

/** Water and restrooms can be a stop on the way; a Metro station is where a ride ends. */
export const stopsOnTheWay = (kind: NearestKind): boolean => kind !== "metro";

export interface NearestPlace {
  /** The OSM element ("n123"), the station's id ("metro-…") or a bikeshare dock's ("dock-…"). */
  id: string;
  /** A bikeshare dock is Ride mode's dock button's own (lib/rideDock.ts), not one of the finder's kinds. */
  kind: NearestKind | "dock";
  /** Where a route to it goes. */
  point: LonLat;
  /** What it is, with its name: "Drinking water, Peirce Mill", "Dupont Circle". */
  title: string;
  /** Its own name alone, where it has one ("Peirce Mill"): a ride's detour rows lead with it. */
  name?: string;
  /** Short sentences after the title: "Bottle filler.", "Red line." */
  details: string[];
}

/**
 * The water layer's points of one kind, as places. Water is drinking water only:
 * untreated water (to filter or treat first) is on the map for riders who carry a
 * filter, but "the nearest water" should be water to drink. Restrooms are every type,
 * each titled with its type (flush, portable or pit, not mapped), so the rider
 * chooses; the layer's switches, hidden while the layer is off, play no part.
 */
export function waterPlaces(points: readonly WaterPoint[], kind: "water" | "restroom"): NearestPlace[] {
  const keep = kind === "water" ? (p: WaterPoint) => p.water === "p" : (p: WaterPoint) => p.toilet !== undefined;
  return points.filter(keep).map((p) => ({
    id: p.id,
    kind,
    point: [p.lon, p.lat],
    title: waterTitle(p),
    ...(p.name ? { name: p.name } : {}),
    details: waterDetails(p),
  }));
}

/**
 * The Metro's stations, each at its bike entrance, or on foot its entrance nearest `from` (walkEntrance); MARC-only
 * stations are left out.
 */
export function metroPlaces(
  stations: readonly Station[],
  closedReason: (station: Station) => string | null = () => null,
  onFoot = false,
  from: LonLat | null = null,
): NearestPlace[] {
  return stations
    .filter((station) => station.metro.length > 0)
    .map((station) => {
      const entrance = stationEntrance(station, onFoot, from);
      return {
        id: station.id,
        kind: "metro" as const,
        point: entrance.point,
        // A station closed for the day says so: "X Metro station, closed: no Metro service today".
        title: closedReason(station) ? `${station.name} Metro station, closed: ${closedReason(station)}` : `${station.name} Metro station`,
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
        // A Bikeshare or transit plan takes exactly two points (and Bikeshare its own bike fields); the way to the
        // nearest place is ridden like the default ride type (no dock walk, no bike choice).
        ...(twoPointsOnly(preset)
          ? {
              preset: "default",
              ...dialFields({
                ...dials,
                bike: undefined,
                ending: undefined,
                pickupStation: undefined,
                dropoffStation: undefined,
                systemWeightKg: undefined,
                ridingSpeedKmh: undefined,
                targetDistanceM: undefined,
                loop: false,
              }),
            }
          : {
              preset,
              ...dialFields({ ...dials, systemWeightKg: undefined, ridingSpeedKmh: undefined, targetDistanceM: undefined, loop: false }),
            }),
      }),
    });
  } catch {
    return { ok: false, message: t("The search did not get through. Check your connection and try again.") };
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
  /** With a route shown: the estimated detour off it there and back (lib/food.ts) and where to turn off. */
  detour?: { alongM: number; extraM: number; extraS: number };
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

/** The `n` places with the least estimated detour off the route, least first; a tie (several on it) nearest `from` first. */
export function leastDetour(from: LonLat, places: readonly NearestPlace[], route: RouteForDetour, n = NEAREST_SHOWN): Nearby[] {
  const project = projector(route.line);
  return places
    .map((place) => {
      const { offM, alongM } = project(place.point);
      const { extraM, extraS } = detourOf(offM, route.speedMps);
      return { place, m: haversineM(from, place.point), item: { place, distanceM: extraM, timeS: null, byBike: false, detour: { alongM, extraM, extraS } } as Nearby };
    })
    .sort((a, b) => a.item.detour!.extraM - b.item.detour!.extraM || a.m - b.m)
    .slice(0, n)
    .map(({ item }) => item);
}

/** How far, in words: "0.6 mi (1.0 km) by bike, about 4 min" or "0.4 mi (0.6 km) in a straight line". */
export function howFar(item: Nearby): string {
  const d = item.detour;
  if (d) {
    if (d.extraM === 0 || milesFigure(d.extraM) === "0.0") return t("on your route at {at}", { at: formatDistance(d.alongM) });
    return t("{extra} detour, about {time}, turning off at {at}", { extra: formatExtra(d.extraM), time: formatDuration(d.extraS), at: formatDistance(d.alongM) });
  }
  if (!item.byBike) return t("{distance} in a straight line", { distance: formatDistance(item.distanceM) });
  const time = item.timeS === null ? "" : t(", about {time}", { time: formatDuration(item.timeS) });
  return t("{distance} by bike{time}", { distance: formatDistance(item.distanceM), time });
}

/** One line of the list: "Drinking water, Peirce Mill: 0.6 mi (1.0 km) by bike, about 4 min. Bottle filler. Free." */
export function nearbyText(item: Nearby): string {
  return [nearbyShort(item), ...item.place.details].join(" ");
}

/** The row shown: the place and how far; its details are one tap away (the owner, 2026-10-18: "a wall of text"). */
export function nearbyShort(item: Nearby): string {
  return `${item.place.title}: ${howFar(item)}.`;
}

/**
 * A ride's detour row as shown (the UI review, 2026-10-28): the place's own name where it has one, how far, and
 * whether it is ahead on the route or behind: "Peirce Mill · 0.5 mi (0.8 km) ahead". `side` is null where it cannot be
 * told. Screen readers keep nearbyText's whole line.
 */
export function detourRowShown(item: Nearby, side: "ahead" | "behind" | null): string {
  const place = item.place.name || item.place.title;
  const distance = formatDistance(item.distanceM);
  if (side === "ahead") return t("{place} · {distance} ahead", { place, distance });
  if (side === "behind") return t("{place} · {distance} behind", { place, distance });
  return `${place} · ${distance}`;
}

export const STRAIGHT_LINE_NOTE = t("The router's riding distances were not available, so these are by straight-line distance.");

/** Where the search was from, in words, for the status line. */
export type NearestFrom = "location" | "centre" | "start";
export const FROM_LABEL: Record<NearestFrom, string> = {
  location: t("My location"),
  centre: t("The map's center"),
  start: t("The start of the plan"),
};
const FROM_WORDS: Record<NearestFrom, string> = {
  location: t("your location"),
  centre: t("the map's center"),
  start: t("the start of the plan"),
};

/** The status line once the list is in: how many, of what, from where, how measured, and the nearest. */
export function foundSaid(kind: NearestKind, from: NearestFrom, items: readonly Nearby[]): string {
  const noun = nounOf(kind);
  if (items[0]?.detour)
    return items.length === 1
      ? t("The {one} with the least detour off your route.", { one: nounOf(kind, 1) })
      : t("The {count} {noun} with the least detour off your route, least first.", { count: items.length, noun });
  if (items.length === 0) return t("No {noun} could be reached by bike from {from}.", { noun, from: FROM_WORDS[from] });
  const how = items[0].byBike ? t("by bike") : t("in a straight line");
  const lead =
    items.length === 1
      ? t("The nearest {one} {how} from {from}.", { one: nounOf(kind, 1), how, from: FROM_WORDS[from] })
      : t("The {count} nearest {noun} {how} from {from}, nearest first.", { count: items.length, noun, how, from: FROM_WORDS[from] });
  // The nearest is the list's first row, so the line does not say it again.
  return items[0].byBike ? lead : `${lead} ${STRAIGHT_LINE_NOTE}`;
}

export const findingSaid = (kind: NearestKind): string => t("Finding the nearest {noun}.", { noun: nounOf(kind) });
export const noneKnownSaid = (kind: NearestKind): string => t("No {noun} on the map to search.", { noun: nounOf(kind) });
export const WATER_NOT_LOADED = t("Water and restrooms are unavailable for now; try again shortly.");
export const LOCATION_BUSY = t("Your location is already being found; try again in a moment.");
export const STILL_SEARCHING = t("Still searching.");
export const NEAREST_STALE = t("The ride or where to search from changed during the search; search again.");

// --- While riding (Ride mode, RideMode.tsx) ---

// What a ride's Detour menu offers (water, restrooms, food, repair and a search box) is lib/detourSearch.ts.
export const DETOUR_HELP =
  t("Detour here re-plans the ride from where you are through that place and on along the rest of the ride.");
export const NO_FIX_YET = t("Your position is not known yet; wait for GPS and try again.");

/**
 * The ride's position as a look-up's answer, for searchNearest: the last good fix, else the last fix;
 * none yet is "unavailable". No new look-up: Ride mode's one watch already has it.
 */
export function rideLocate(fix: { point: LonLat; accuracyM: number } | null | undefined): LocateResult {
  return fix ? { ok: true, fix: { point: fix.point, accuracyM: fix.accuracyM } } : { ok: false, reason: "unavailable" };
}

/**
 * A re-plan's points with the detour put first: from here, to the place, then on through what was left.
 * `replanned` is navigate.replanPoints's answer, which starts at the rider.
 */
export function detourPoints(replanned: readonly LonLat[], place: LonLat): LonLat[] | null {
  // A route takes at most MAX_POINTS points; with the stops left already at the cap there is no room.
  if (replanned.length >= MAX_POINTS) return null;
  return [replanned[0], place, ...replanned.slice(1)];
}

/** Said when a detour has no room: the route already has as many stops as one can take. */
export const DETOUR_FULL = t("This route already has {count} points, so no detour can be added.", { count: MAX_POINTS });
/** Said when Detour here is pressed while a new route is already being found. */
export const DETOUR_BUSY = t("A new route is already being found; try again in a moment.");

/** What a search needs from the page; each is a function so a test runs the search with stand-ins. */
export interface SearchDeps {
  kind: NearestKind;
  from: NearestFrom;
  /** One location look-up; "busy" while another (Use my location's) is under way. */
  locate: () => Promise<LocateResult | "busy">;
  /** The plan's start, or null with no points. */
  start: () => LonLat | null;
  /** The map's center, or null before the map is there. */
  centre: () => LonLat | null;
  inside: (point: LonLat) => boolean;
  /** The water layer's points, loaded if they are not yet; null if they cannot be. */
  water: () => Promise<WaterPoint[] | null>;
  stations: readonly Station[];
  /** Why a station is closed today, or null (railClosures.ts): a closed one says so in the list. */
  closedReason?: (station: Station) => string | null;
  /** The ride reaches places on foot (presets.ts, endsOnFoot): a station's nearest entrance, not its elevator. */
  onFoot?: () => boolean;
  /**
   * The route shown, if any: then the list is the places with the least detour off it, by the same estimate as
   * Find food's, with no router call (the owner, 2026-10-18: "if on a route we'd want to sort by miles of detour
   * too", "Same for the other detour types").
   */
  route?: RouteForDetour | null;
  request: (from: LonLat, places: readonly NearestPlace[]) => Promise<NearestResult>;
}

export interface Found {
  kind: NearestKind;
  items: Nearby[];
  /** Where it was searched from: Ride here plans from here. */
  origin: LonLat;
  from: NearestFrom;
}

/** What came of a search: the status line, the list if there is one, and the location fix if one was taken. */
export interface SearchOutcome {
  said: string;
  found?: Found;
  fix?: Fix;
}

/** One search, start to end: where from, which places, the nearest in straight lines, then by bike. */
export async function searchNearest(deps: SearchDeps): Promise<SearchOutcome> {
  const { kind, from } = deps;
  let origin: LonLat | null;
  let fix: Fix | undefined;
  if (from === "location") {
    const result = await deps.locate();
    if (result === "busy") return { said: LOCATION_BUSY };
    if (!result.ok) return { said: LOCATE_MESSAGES[result.reason] };
    fix = result.fix;
    origin = fix.point;
  } else {
    origin = from === "start" ? deps.start() : deps.centre();
  }
  const withFix = (outcome: SearchOutcome): SearchOutcome => (fix ? { ...outcome, fix } : outcome);
  if (origin === null) return { said: t("There is nowhere to search from yet.") };
  if (!deps.inside(origin)) {
    return withFix({ said: from === "location" ? LOCATION_OUTSIDE : t("That spot is outside the area this map covers.") });
  }
  let places: NearestPlace[];
  if (kind === "metro") {
    places = metroPlaces(deps.stations, deps.closedReason, deps.onFoot?.() === true, origin);
  } else {
    const data = await deps.water();
    if (!data) return withFix({ said: WATER_NOT_LOADED });
    places = waterPlaces(data, kind);
  }
  if (places.length === 0) return withFix({ said: noneKnownSaid(kind) });
  if (deps.route) {
    const items = leastDetour(origin, places, deps.route);
    return withFix({ said: foundSaid(kind, from, items), found: { kind, items, origin, from } });
  }
  const candidates = nearestInStraightLine(origin, places);
  const result = await deps.request(origin, candidates);
  if (!result.ok) return withFix({ said: t("The search failed. {why}", { why: result.message }) });
  const items = rankNearest(candidates, result.answer);
  return withFix({ said: foundSaid(kind, from, items), found: { kind, items, origin, from } });
}
