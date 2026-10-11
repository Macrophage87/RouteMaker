/**
 * Find food: a map search for places to eat by cuisine or name. The owner, 2026-10-11
 * (FOOD-SEARCH in the v0.5.0 plan): "Is it possible to use photon to search for things like
 * cuisine types? Like if I wanted to search for a midride crab restaurant or pizza place."; then
 * "Mostly let's do a map search for it. People are willing to detour for good food."
 *
 * The places are amenity-data/food.json, built from the project's own OpenStreetMap extract by
 * scripts/build_food.py (what counts is in its docstring): restaurants, fast food, cafes, ice
 * cream, pubs, beer gardens and food courts, each with its name, its `cuisine` list and, where
 * mapped, opening hours and website. No ratings: there is no open source for them, and Google's
 * data is never copied. The file is fetched the first time the rider searches.
 *
 * A search matches the rider's words against each place's name and cuisine, widened by a short
 * list of words that mean the same food (FOOD_SYNONYMS: "crab" finds seafood places too). The
 * results are the matches in the map's view, or in the whole area when the rider asks; with a
 * route shown, each says its detour, the extra distance and time to ride there and back to the
 * route, and the list is sorted by it, with no distance cap. Without a route, by distance from
 * the map's center.
 *
 * The detour is an estimate, worked out here with no router call, so a search over hundreds of
 * places is instant and costs the server nothing: the straight-line distance from the place to
 * the nearest spot on the route (a flat projection, as waterAlongRoute's), doubled (there and
 * back) and multiplied by CIRCUITY, as streets are rarely straight; the time is that distance at
 * the route's own average speed (its distance over its time). "Circuity, the ratio of network to
 * Euclidean distances": Giacomin and Levinson, "Road network circuity in metropolitan areas",
 * Environment and Planning B 42(6), 2015, doi:10.1068/b130131p
 * (<https://experts.umn.edu/en/publications/road-network-circuity-in-metropolitan-areas/>, read
 * 2026-10-11), who also found short trips more circuitous than long ones, hence a factor on the
 * high side for a short hop off the route.
 *
 * Plain data in, plain data out, so node --test runs all of it; the panel is lib/foodFinder.ts
 * and the map's markers are at the end of this file.
 */
import { formatDistance, formatDuration, formatExtra } from "./format.ts";
import type { LonLat } from "./geo.ts";

export type FoodKind = "r" | "f" | "c" | "i" | "p" | "b" | "fc";

export interface FoodPlace {
  /** The OSM element: "n123", "w456" or "r789". */
  id: string;
  lon: number;
  lat: number;
  kind: FoodKind;
  name: string;
  /** OSM's `cuisine` values, lower case with "_" for spaces ("ice_cream"), in the mapped order. */
  cuisine: string[];
  hours?: string;
  website?: string;
}

const KINDS: readonly FoodKind[] = ["r", "f", "c", "i", "p", "b", "fc"];

export const KIND_LABEL: Record<FoodKind, string> = {
  r: "Restaurant",
  f: "Fast food",
  c: "Cafe",
  i: "Ice cream",
  p: "Pub",
  b: "Beer garden",
  fc: "Food court",
};

// --- The file ------------------------------------------------------------

const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value.trim() : undefined);

/** The file's places; an empty list for a file with none yet; null if it is not the file's shape. */
export function parseFood(value: unknown): FoodPlace[] | null {
  const body = value as { points?: unknown } | null;
  if (!body || !Array.isArray(body.points)) return null;
  const out: FoodPlace[] = [];
  for (const raw of body.points as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string") continue;
    const { x: lon, y: lat } = raw;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const kind = KINDS.find((k) => k === raw.k);
    const name = text(raw.n);
    if (!kind || !name) continue;
    const cuisine = (text(raw.c) ?? "")
      .split(";")
      .map((c) => c.trim().toLowerCase())
      .filter(Boolean);
    const place: FoodPlace = { id: raw.id, lon, lat, kind, name, cuisine };
    const hours = text(raw.h);
    if (hours) place.hours = hours;
    const website = text(raw.web);
    // A web address only: the list makes it a link.
    if (website && /^https?:\/\//i.test(website)) place.website = website;
    out.push(place);
  }
  return out;
}

/** Fetch and parse the file; null if it cannot be had (an empty list is "no data yet", not a failure). */
export async function loadFood(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<FoodPlace[] | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    return parseFood(await response.json());
  } catch {
    return null;
  }
}

// --- Matching ------------------------------------------------------------

/**
 * Words that mean more than their own cuisine value, for the owner to confirm or extend: each
 * word (singular, lower case) finds places whose cuisine is any of its values, and "kind:x"
 * finds every place of that kind (a cafe for "coffee", whatever its cuisine says). A word not
 * listed still finds its own cuisine value and any name holding it. OSM's common cuisine values
 * are on <https://wiki.openstreetmap.org/wiki/Key:cuisine> (read 2026-10-11).
 */
export const FOOD_SYNONYMS: Readonly<Record<string, readonly string[]>> = {
  crab: ["crab", "seafood"],
  seafood: ["seafood", "crab", "fish", "oyster", "lobster", "fish_and_chips"],
  fish: ["fish", "seafood", "fish_and_chips"],
  oyster: ["oyster", "seafood"],
  lobster: ["lobster", "seafood"],
  pizza: ["pizza"],
  burger: ["burger"],
  hamburger: ["burger"],
  bbq: ["barbecue", "bbq"],
  barbecue: ["barbecue", "bbq"],
  taco: ["tacos", "taco", "mexican", "tex-mex"],
  sushi: ["sushi", "japanese"],
  ramen: ["ramen", "noodle", "japanese"],
  noodle: ["noodle", "ramen", "pho"],
  pho: ["pho", "vietnamese"],
  sandwich: ["sandwich", "sub", "deli"],
  sub: ["sub", "sandwich"],
  deli: ["deli", "sandwich"],
  bagel: ["bagel"],
  donut: ["donut"],
  doughnut: ["donut"],
  breakfast: ["breakfast", "brunch"],
  brunch: ["brunch", "breakfast"],
  chicken: ["chicken", "fried_chicken", "wings"],
  wing: ["wings", "chicken"],
  coffee: ["coffee_shop", "coffee", "kind:c"],
  cafe: ["kind:c", "coffee_shop"],
  "ice cream": ["ice_cream", "frozen_yogurt", "gelato", "kind:i"],
  gelato: ["gelato", "ice_cream"],
  "frozen yogurt": ["frozen_yogurt", "ice_cream"],
  beer: ["kind:p", "kind:b"],
  pub: ["kind:p", "kind:b"],
  bakery: ["bakery", "pastry"],
  pastry: ["pastry", "bakery"],
  dessert: ["dessert", "ice_cream", "frozen_yogurt", "cake", "donut"],
  vegan: ["vegan"],
  vegetarian: ["vegetarian", "vegan"],
};

/** Lower case, punctuation but ' & - dropped, spaces squeezed: "  Crab-House! " is "crab-house". */
export function normaliseQuery(query: string): string {
  return query
    .toLowerCase()
    .replace(/[^\p{L}\p{N}'&\- ]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** "crabs" is "crab", "sandwiches" "sandwich", "taco" "taco"; "fries" and the like stay as typed too. */
function singulars(word: string): string[] {
  const out = [word];
  if (word.endsWith("es") && word.length > 4) out.push(word.slice(0, -2));
  if (word.endsWith("s") && !word.endsWith("ss") && word.length > 3) out.push(word.slice(0, -1));
  return out;
}

export interface FoodTerms {
  /** The words as typed, normalised, for the name. */
  text: string;
  /** Cuisine values that match. */
  cuisines: Set<string>;
  /** Kinds that match whatever their cuisine. */
  kinds: Set<FoodKind>;
}

/** What a query finds: its own words for names, and its cuisine values and kinds with the synonyms. */
export function foodTerms(query: string): FoodTerms | null {
  const q = normaliseQuery(query);
  if (!q) return null;
  const cuisines = new Set<string>();
  const kinds = new Set<FoodKind>();
  for (const form of singulars(q)) {
    cuisines.add(form.replace(/ /g, "_"));
    for (const value of FOOD_SYNONYMS[form] ?? []) {
      if (value.startsWith("kind:")) {
        const kind = KINDS.find((k) => k === value.slice(5));
        if (kind) kinds.add(kind);
      } else cuisines.add(value);
    }
  }
  return { text: q, cuisines, kinds };
}

/** Whether a place matches: its name holds the words, or a cuisine value (or a part of one) or its kind is one asked for. */
export function matchesFood(place: FoodPlace, terms: FoodTerms): boolean {
  if (terms.kinds.has(place.kind)) return true;
  if (normaliseQuery(place.name).includes(terms.text)) return true;
  // "fried_chicken" is chicken; "seafood" is not "food" (a part, not a substring).
  return place.cuisine.some((c) => terms.cuisines.has(c) || c.split("_").some((part) => terms.cuisines.has(part)));
}

// --- Where -----------------------------------------------------------------

/** west, south, east, north. */
export type Bounds = readonly [number, number, number, number];

export const inBounds = (place: FoodPlace, [west, south, east, north]: Bounds): boolean =>
  place.lon >= west && place.lon <= east && place.lat >= south && place.lat <= north;

const M_PER_DEG_LAT = 111_320;

/** Straight-line metres, flat (plenty inside the coverage box for sorting and a figure in words). */
function flatM(a: LonLat, b: LonLat): number {
  const kx = M_PER_DEG_LAT * Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180);
  return Math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * M_PER_DEG_LAT);
}

/** Streets over the straight line for a short hop off the route; see the file's comment. */
export const CIRCUITY = 1.4;
/** Below this the place is on the route: no detour. 50 ft (15 m), as the water list's. */
export const ON_ROUTE_M = 15;

export interface RouteForDetour {
  line: readonly LonLat[];
  /** The route's own average speed, metres a second. */
  speedMps: number;
}

/** The route's line and average speed, or null when there is no usable route. */
export function routeForDetour(route: { geometry: { coordinates: LonLat[] }; distance_m: number; duration_s: number } | null): RouteForDetour | null {
  if (!route || route.geometry.coordinates.length < 2 || !(route.duration_s > 0) || !(route.distance_m > 0)) return null;
  return { line: route.geometry.coordinates, speedMps: route.distance_m / route.duration_s };
}

/** The nearest spot on the line to each point: how far off (metres) and how far along the route that spot is. */
export function projector(line: readonly LonLat[]): (point: LonLat) => { offM: number; alongM: number } {
  let lat0 = 0;
  for (const [, lat] of line) lat0 += lat / line.length;
  const kx = M_PER_DEG_LAT * Math.cos((lat0 * Math.PI) / 180);
  const xy = line.map(([lon, lat]) => [lon * kx, lat * M_PER_DEG_LAT] as const);
  const cumulative: number[] = [0];
  for (let i = 1; i < xy.length; i += 1) cumulative.push(cumulative[i - 1] + Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]));
  return ([lon, lat]) => {
    const px = lon * kx;
    const py = lat * M_PER_DEG_LAT;
    let best = Infinity;
    let alongM = 0;
    for (let i = 1; i < xy.length; i += 1) {
      const [ax, ay] = xy[i - 1];
      const [bx, by] = xy[i];
      const dx = bx - ax;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      if (d < best) {
        best = d;
        alongM = cumulative[i - 1] + t * Math.sqrt(len2);
      }
    }
    return { offM: best, alongM };
  };
}

/** The estimated detour for a place `offM` off the route: there and back on streets, at the route's speed. */
export function detourOf(offM: number, speedMps: number): { extraM: number; extraS: number } {
  if (offM < ON_ROUTE_M) return { extraM: 0, extraS: 0 };
  const extraM = 2 * offM * CIRCUITY;
  return { extraM, extraS: speedMps > 0 ? extraM / speedMps : 0 };
}

export interface FoodResult {
  place: FoodPlace;
  /** From the map's center, straight line, metres (the sort without a route). */
  fromCentreM: number;
  /** With a route: the detour and where on the route to turn off. */
  detour?: { offM: number; alongM: number; extraM: number; extraS: number };
}

export type FoodScope = "view" | "area";

export interface FoodSearch {
  query: string;
  scope: FoodScope;
  /** The map's view (scope "view"). */
  bounds: Bounds | null;
  centre: LonLat;
  route: RouteForDetour | null;
}

/** Every match, sorted: by detour with a route (then by where on the route), else by distance from the center. */
export function searchFood(places: readonly FoodPlace[], search: FoodSearch): FoodResult[] {
  const terms = foodTerms(search.query);
  if (!terms) return [];
  const bounds = search.scope === "view" ? search.bounds : null;
  const project = search.route ? projector(search.route.line) : null;
  const out: FoodResult[] = [];
  for (const place of places) {
    if (bounds && !inBounds(place, bounds)) continue;
    if (!matchesFood(place, terms)) continue;
    const point: LonLat = [place.lon, place.lat];
    const result: FoodResult = { place, fromCentreM: flatM(search.centre, point) };
    if (project && search.route) {
      const { offM, alongM } = project(point);
      result.detour = { offM, alongM, ...detourOf(offM, search.route.speedMps) };
    }
    out.push(result);
  }
  return out.sort((a, b) =>
    a.detour && b.detour
      ? a.detour.extraM - b.detour.extraM || a.detour.alongM - b.detour.alongM || a.place.id.localeCompare(b.place.id)
      : a.fromCentreM - b.fromCentreM || a.place.id.localeCompare(b.place.id),
  );
}

// --- Words ---------------------------------------------------------------

/** "Restaurant: seafood, crab", "Ice cream", "Fast food: fried chicken". */
export function foodKindText(place: FoodPlace): string {
  const cuisine = place.cuisine.map((c) => c.replace(/_/g, " ")).join(", ");
  return cuisine ? `${KIND_LABEL[place.kind]}: ${cuisine}` : KIND_LABEL[place.kind];
}

/** How far, in words: the detour with a route, else the distance from the center. */
export function foodHowFar(result: FoodResult): string {
  const d = result.detour;
  if (!d) return `${formatDistance(result.fromCentreM)} from the map's center in a straight line.`;
  const at = formatDistance(d.alongM);
  if (d.extraM === 0) return `On your route at ${at}.`;
  return `Detour about ${formatExtra(d.extraM)} and ${formatDuration(d.extraS)} there and back, turning off at ${at} on your route.`;
}

/** One result in words, as the list shows it and a screen reader reads it. */
export function foodText(result: FoodResult): string {
  const parts = [`${result.place.name}. ${foodKindText(result.place)}.`, foodHowFar(result)];
  if (result.place.hours) parts.push(`Hours as mapped: ${result.place.hours}.`);
  return parts.join(" ");
}

export const FOOD_PAGE = 10;
export const NO_FOOD_DATA = "No food data yet: the places to eat arrive with the next map data update.";
export const FOOD_NOT_LOADED = "The places to eat are unavailable for now; try again shortly.";
export const FOOD_EMPTY_QUERY = "Type a food or a name to search for, such as crab, pizza or coffee.";
export const FOOD_DETOUR_NOTE =
  `Detours are estimates: the straight-line distance off your route, there and back, times ${CIRCUITY} for the streets, at your route's average speed. ` +
  "From OpenStreetMap: check the hours before you count on them. No ratings.";

/** The status line after a search. */
export function foodFoundSaid(query: string, scope: FoodScope, total: number, shown: number, sortedByDetour: boolean): string {
  const where = scope === "view" ? "in the map view" : "in the whole area";
  const q = `“${normaliseQuery(query)}”`;
  if (total === 0) return `No places match ${q} ${where}.${scope === "view" ? " Try Search the whole area, or move the map." : ""}`;
  const count = `${total.toLocaleString("en-US")} ${total === 1 ? "place matches" : "places match"} ${q} ${where}`;
  const order = sortedByDetour ? "least detour first" : "nearest the map's center first";
  const showing = shown < total ? ` Showing the first ${shown}.` : "";
  return `${count}, ${order}.${showing}`;
}

export const foodMoreSaid = (shown: number, total: number): string => `Showing ${shown} of ${total.toLocaleString("en-US")}.`;

// --- The map's markers -----------------------------------------------------

// The results' map markers are the lettered places' buttons (lib/letteredPlaces.ts, MapView `lettered`),
// lettered as the list: the owner's lettered places of 2026-10-11 (they were a numbered circle layer).
