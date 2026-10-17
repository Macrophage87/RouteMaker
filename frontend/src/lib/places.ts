/**
 * Places to see (v0.7.0, "Points of interest tab, and farm stands as food"). The owner, 2026-10-14: "Could a
 * points of interest tab be planned as well. Let's categorize by things like museums, lighthouses, gardens,
 * farmers markets, etc." Then 13:07 UTC: "Make sure that go stays clean, but they can find it there. Plan can
 * have more complexity."
 *
 * The places are amenity-data/places.json, built from the project's extract by scripts/build_places.py (what
 * counts, by category, is in its docstring). Plan's "Places to see" sheet filters by category and, along a
 * planned route, lists the places within half a mile (0.8 km) of it in riding order, each with its detour;
 * with no route, nearest the map's center first. Go's Sights (behind More) lists the nearest SIGHTS_SHOWN, no
 * filters. The map layer is one switch in Layers, off by default.
 *
 * The detour is food's estimate (lib/food.ts: straight line off the route, there and back, times CIRCUITY).
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { detourOf, projector, type RouteForDetour } from "./food.ts";
import { formatDistance, formatExtra, HALF_MILE, milesFigure } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";

export type PlaceCategory = "museum" | "historic" | "lighthouse" | "garden" | "viewpoint" | "market" | "zoo" | "nature" | "bridge" | "drink";

/**
 * The categories in the build's order: the filter's words, one place's words, and an emoji drawn beside the
 * words (decorative: hidden from screen readers, as the words say it).
 */
export const CATEGORIES: ReadonlyArray<{ id: PlaceCategory; label: string; one: string; emoji: string }> = [
  { id: "museum", label: "Museums and galleries", one: "Museum or gallery", emoji: "🖼️" },
  { id: "historic", label: "Historic sites and monuments", one: "Historic site", emoji: "🏛️" },
  { id: "lighthouse", label: "Lighthouses", one: "Lighthouse", emoji: "🗼" },
  { id: "garden", label: "Gardens and arboretums", one: "Garden", emoji: "🌷" },
  { id: "viewpoint", label: "Viewpoints", one: "Viewpoint", emoji: "🔭" },
  { id: "market", label: "Farmers markets and farm stands", one: "Market or farm stand", emoji: "🍎" },
  { id: "zoo", label: "Zoos, aquariums and nature centers", one: "Zoo or nature center", emoji: "🦁" },
  { id: "nature", label: "Waterfalls and peaks", one: "Waterfall or peak", emoji: "⛰️" },
  { id: "bridge", label: "Covered and notable bridges", one: "Bridge", emoji: "🌉" },
  { id: "drink", label: "Breweries, wineries and cideries", one: "Brewery or winery", emoji: "🍷" },
];
const BY_ID = new Map(CATEGORIES.map((c) => [c.id, c]));

export interface SightPlace {
  /** The OSM element: "n123", "w456" or "r789". */
  id: string;
  lon: number;
  lat: number;
  category: PlaceCategory;
  name: string;
  hours?: string;
  website?: string;
  /** A covered bridge (bridge=covered, the file's "cv"): the Scenic layer draws it by name (lib/scenicLayer.ts). */
  covered?: true;
}

const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value.trim() : undefined);

/** The file's places; an empty list for a file with none yet; null if it is not the file's shape. */
export function parsePlaces(value: unknown): SightPlace[] | null {
  const body = value as { points?: unknown } | null;
  if (!body || !Array.isArray(body.points)) return null;
  const out: SightPlace[] = [];
  for (const raw of body.points as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string") continue;
    const { x: lon, y: lat } = raw;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const category = BY_ID.get(raw.k as PlaceCategory)?.id;
    const name = text(raw.n);
    if (!category || !name) continue;
    const place: SightPlace = { id: raw.id, lon, lat, category, name };
    const hours = text(raw.h);
    if (hours) place.hours = hours;
    const website = text(raw.web);
    if (website && /^https?:\/\//i.test(website)) place.website = website;
    if (raw.cv === 1 && category === "bridge") place.covered = true;
    out.push(place);
  }
  return out;
}

/** Fetch and parse the file; null if it cannot be had (an empty list is "none yet", not a failure). */
export async function loadPlaces(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<SightPlace[] | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    return parsePlaces(await response.json());
  } catch {
    return null;
  }
}

// --- Which and in what order -------------------------------------------------

/** Along a route, places within this of it: half a mile. */
export const ALONG_M = 804.672;
export const ALONG_TEXT = HALF_MILE;
/** Go's Sights: how many. */
export const SIGHTS_SHOWN = 5;
export const PLACES_PAGE = 10;

export interface SightResult {
  place: SightPlace;
  /** Straight line from where the list is from, metres (no route). */
  metres: number;
  /** With a route: where it turns off and the detour there and back. */
  detour?: { alongM: number; offM: number; extraM: number };
}

export type PlaceFilter = PlaceCategory | "all";

/**
 * Plan's list: along a route, the places within ALONG_M of it in riding order; with none, every place nearest
 * `from` first. `filter` keeps one category.
 */
export function placesToSee(places: readonly SightPlace[], from: LonLat, route: RouteForDetour | null, filter: PlaceFilter = "all"): SightResult[] {
  const kept = filter === "all" ? places : places.filter((p) => p.category === filter);
  if (route) {
    const project = projector(route.line);
    const out: SightResult[] = [];
    for (const place of kept) {
      const point: LonLat = [place.lon, place.lat];
      const { offM, alongM } = project(point);
      if (offM > ALONG_M) continue;
      out.push({ place, metres: haversineM(from, point), detour: { alongM, offM, extraM: detourOf(offM, route.speedMps).extraM } });
    }
    return out.sort((a, b) => a.detour!.alongM - b.detour!.alongM || a.place.id.localeCompare(b.place.id));
  }
  return kept
    .map((place) => ({ place, metres: haversineM(from, [place.lon, place.lat]) }))
    .sort((a, b) => a.metres - b.metres || a.place.id.localeCompare(b.place.id));
}

/** Go's Sights: the SIGHTS_SHOWN with the least detour along the route, in riding order; or the nearest to `from`. */
export function sightsForGo(places: readonly SightPlace[], from: LonLat, route: RouteForDetour | null, n = SIGHTS_SHOWN): SightResult[] {
  const all = placesToSee(places, from, route);
  if (!route) return all.slice(0, n);
  return [...all]
    .sort((a, b) => a.detour!.extraM - b.detour!.extraM || a.detour!.alongM - b.detour!.alongM)
    .slice(0, n)
    .sort((a, b) => a.detour!.alongM - b.detour!.alongM);
}

// --- Words -------------------------------------------------------------------

export const categoryOf = (place: SightPlace) => BY_ID.get(place.category)!;

/** How far, short, as Go shows it: "+0.4 mi (0.6 km)" off the route, "On your route", or "0.6 mi (1.0 km) away". */
export function sightHowFar(result: SightResult): string {
  const d = result.detour;
  if (!d) return `${formatDistance(result.metres)} away`;
  if (d.extraM === 0 || milesFigure(d.extraM) === "0.0") return "On your route";
  return formatExtra(d.extraM);
}

/** One place in words: "Point Light. Lighthouse. +0.4 mi (0.6 km) there and back, at 3.1 mi (5.0 km) on your route. Hours: …" */
export function sightText(result: SightResult): string {
  const { place, detour } = result;
  const where = detour
    ? sightHowFar(result) === "On your route"
      ? `On your route at ${formatDistance(detour.alongM)}.`
      : `${sightHowFar(result)} there and back, turning off at ${formatDistance(detour.alongM)} on your route.`
    : `${sightHowFar(result)}.`;
  const parts = [`${place.name}. ${categoryOf(place).one}.`, where];
  if (place.hours) parts.push(`Hours as mapped: ${place.hours}.`);
  return parts.join(" ");
}

export const PLACES_NONE = "No places to see yet: they arrive with the next map data update.";
export const PLACES_UNAVAILABLE = "Places to see are unavailable for now; try again shortly.";
export const PLACES_NOTE = "Detours are estimates; check hours (OpenStreetMap).";

/** The status line for Plan's list. */
export function placesSaid(count: number, filter: PlaceFilter, alongRoute: boolean): string {
  const what = filter === "all" ? "places to see" : CATEGORIES.find((c) => c.id === filter)!.label.toLowerCase();
  if (count === 0) return alongRoute ? `No ${what} within ${ALONG_TEXT} of your route.` : `No ${what} found.`;
  const n = count.toLocaleString("en-US");
  return alongRoute ? `${n} ${what} within ${ALONG_TEXT} of your route, in riding order.` : `${n} ${what}, nearest the map's center first.`;
}

// --- The map's layer (one switch, off by default) -------------------------------------------

export const PLACES_SOURCE_ID = "places-to-see";
export const PLACES_LAYER = "places-to-see";
/**
 * The owner, 2026-10-17: "For places to see, have these shown at a fairly wide zoom, probably as wide as possible."
 * So from the map's widest zoom (MapView's minZoom, 7), as small dots that grow as the map zooms in.
 */
export const PLACES_MIN_ZOOM = 7;
export const PLACES_COLOUR = "#7a2e8e";
export const PLACES_PREF_KEY = "routemaker.placesLayer";

export function placesGeoJson(places: readonly SightPlace[]): object {
  return {
    type: "FeatureCollection",
    features: places.map((p) => ({ type: "Feature", properties: { id: p.id }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } })),
  };
}

/** A purple dot with a white ring: the tap card names the place and its category in words. */
export function placesLayer(): Record<string, unknown> {
  return {
    id: PLACES_LAYER,
    type: "circle",
    source: PLACES_SOURCE_ID,
    minzoom: PLACES_MIN_ZOOM,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], PLACES_MIN_ZOOM, 2.5, 11, 3.5, 15, 6.5],
      "circle-color": PLACES_COLOUR,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], PLACES_MIN_ZOOM, 1, 11, 1.5],
    },
  };
}

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The layer's switch as kept on this device; off when nothing is kept or storage is blocked. */
export function readPlacesLayer(store: Store | null = defaultStore()): boolean {
  try {
    return store?.getItem(PLACES_PREF_KEY) === "on";
  } catch {
    return false;
  }
}

export function savePlacesLayer(on: boolean, store: Store | null = defaultStore()): void {
  try {
    store?.setItem(PLACES_PREF_KEY, on ? "on" : "off");
  } catch {
    // Not kept: the switch still works for this visit.
  }
}
