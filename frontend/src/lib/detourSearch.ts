/**
 * A ride's Detour menu (Ride mode and Roam): what a rider can detour to mid-ride. Stephen, 2026-10-24: "Detours should
 * include food too and anything that a user would search for", then "repair stands too". Before, Ride mode's Detour
 * offered water and restrooms (the owner, 2026-10-10) and Roam's water, restrooms and food.
 *
 * Four buttons, each the three nearest by bike from the rider: Water, Restroom, Food (Find food's places,
 * lib/food.ts) and Repair (repair stands and bike shops, lib/repair.ts). Under them one search box takes anything
 * else: a cuisine or a food place's name ("pizza", "coffee"), which matches Find food's places as Find food does, and
 * any name or address, which goes to the place search (GET /api/geocode, as Where to? asks; "grocery" and "bike shop"
 * there find the nearest such shops, core/geocode.py TAG_SEARCHES). A word for one of the four ("water",
 * "bathroom", "pump") is that button. Both kinds of match are measured by bike together (POST /api/nearest) and
 * the three nearest offered, so a rider choosing a lunch stop sees the nearest by riding, not by name.
 *
 * Privacy (the owner, 2026-10-22: nothing kept on the server): the rider's point goes in the riding-distance
 * request, as it always has for water; the place search gets it rounded to about half a mile (geocode.ts
 * BIAS_ROUNDING_DEG), as Where to?'s does.
 *
 * Plain data in, plain data out, so node --test runs all of it; the menus are RideMode.tsx and RoamMode.tsx.
 */
import { foodTerms, matchesFood, normaliseQuery, type FoodPlace } from "./food.ts";
import { BIAS_ROUNDING_DEG, MIN_QUERY_CHARS, normalQuery, placeType, type GeoResult, type Place } from "./geocode.ts";
import { haversineM, insideCoverage, type LonLat } from "./geo.ts";
import { LOCATION_OUTSIDE } from "./geolocation.ts";
import {
  NEAREST_CANDIDATES,
  findingSaid,
  nearbyShort,
  nearestInStraightLine,
  rankNearest,
  rideLocate,
  searchNearest,
  type Nearby,
  type NearestPlace,
  type NearestResult,
} from "./nearest.ts";
import { repairDetails, repairTitle, type RepairPlace } from "./repair.ts";
import { foodNearestPlaces } from "./roam.ts";
import type { WaterPoint } from "./waterRestrooms.ts";
import { t } from "./i18n.ts";

export type DetourKind = "water" | "restroom" | "food" | "repair";

/** The menu's buttons, in order, with their icons (lib/iconPaths.ts). */
export const DETOUR_CHOICES: ReadonlyArray<{ kind: DetourKind; label: string; icon: "water" | "wc" | "food" | "wrench" }> = [
  { kind: "water", label: "Water", icon: "water" },
  { kind: "restroom", label: "Restroom", icon: "wc" },
  { kind: "food", label: "Food", icon: "food" },
  { kind: "repair", label: "Repair", icon: "wrench" },
];

/** The Detour button's summary (rideStops.detourButtonName lower-cases it). */
export const DETOUR_SUMMARY = t("Water, restroom, food, repair or search");
/** The search box's label and its example words. */
export const DETOUR_SEARCH_LABEL = "Search";
export const DETOUR_SEARCH_HINT = t("Coffee, grocery, address");
export const DETOUR_SEARCH_BUTTON = "Find";

/** What a found list is headed: "Nearest places to eat", "Nearest matches for “pizza”". */
export function detourHeading(kind: DetourKind | "search", query = ""): string {
  if (kind === "water") return "Nearest water";
  if (kind === "restroom") return "Nearest restrooms";
  if (kind === "food") return "Nearest places to eat";
  if (kind === "repair") return "Nearest repair stands and bike shops";
  return `Nearest matches for “${normalQuery(query)}”`;
}

/**
 * Words that ask for one of the buttons: typed in the box, they are that button's search (a "restroom" sent to the
 * place search would find places named Restroom, not the nearest one). Lower case, as normaliseQuery leaves them.
 */
const KIND_WORDS: Readonly<Record<string, DetourKind>> = {
  water: "water",
  "drinking water": "water",
  "water fountain": "water",
  "drinking fountain": "water",
  fountain: "water",
  "bottle filler": "water",
  "bottle refill": "water",
  refill: "water",
  restroom: "restroom",
  restrooms: "restroom",
  "rest room": "restroom",
  bathroom: "restroom",
  bathrooms: "restroom",
  toilet: "restroom",
  toilets: "restroom",
  wc: "restroom",
  loo: "restroom",
  "porta potty": "restroom",
  "porta-potty": "restroom",
  repair: "repair",
  "repair stand": "repair",
  "repair stands": "repair",
  "fix it stand": "repair",
  "fix-it stand": "repair",
  "bike repair": "repair",
  "bicycle repair": "repair",
  pump: "repair",
  "air pump": "repair",
  "bike pump": "repair",
  tools: "repair",
};

/** Find food's words for every place that mean more than food in a general search box: those go to the place search. */
const NOT_ONLY_FOOD = new Set(["all", "any", "anything", "everything"]);

/** The button a typed word stands for, food's general words included ("lunch" is Food); null for anything else. */
export function kindForQuery(query: string): DetourKind | null {
  const q = normaliseQuery(query);
  if (!q) return null;
  if (KIND_WORDS[q]) return KIND_WORDS[q];
  return foodTerms(q).all && !NOT_ONLY_FOOD.has(q) ? "food" : null;
}

/** The repair stands and bike shops as places to ride to, each with its kit or its hours now. */
export function repairNearestPlaces(places: readonly RepairPlace[], at: Date): NearestPlace[] {
  return places.map((p) => ({
    id: p.id,
    // A stop on the way, as water is (nearest.ts stopsOnTheWay); the kind is only a label.
    kind: "water" as const,
    point: [p.lon, p.lat] as LonLat,
    title: repairTitle(p),
    details: repairDetails(p, at),
  }));
}

/** The place search's answers inside the map's area as places to ride to: named, with their type ("Shop."). */
export function searchedPlaces(found: readonly Place[]): NearestPlace[] {
  return found
    .filter((p) => insideCoverage([p.lon, p.lat]))
    .map((p) => {
      const type = placeType(p);
      const where = p.label && p.label !== p.name ? p.label.replace(new RegExp(`^${escapeRegExp(p.name)},\\s*`), "") : "";
      return {
        id: p.osm_type && p.osm_id ? `geo-${p.osm_type}${p.osm_id}` : `geo-${p.lon.toFixed(5)},${p.lat.toFixed(5)}`,
        kind: "water" as const,
        point: [p.lon, p.lat] as LonLat,
        title: p.name,
        details: [`${type}.`, ...(where ? [`${where}.`] : [])],
      };
    });
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Food matches and searched places together, one of each place: a searched place within 50 m (165 ft) of a food
 * place of the same name is that place, and Find food's own (with its cuisine and hours) is kept.
 */
export function mergeCandidates(food: readonly NearestPlace[], searched: readonly NearestPlace[]): NearestPlace[] {
  const same = (a: NearestPlace, b: NearestPlace) =>
    normaliseQuery(a.title) === normaliseQuery(b.title) && haversineM(a.point, b.point) < 50;
  return [...food, ...searched.filter((s) => !food.some((f) => same(f, s)))];
}

/** The place search's point for a ride: the rider's, rounded as Where to?'s bias is (geocode.ts searchBiasPoint). */
export function roundedBias([lon, lat]: LonLat): LonLat | undefined {
  const round = (v: number) => Number((Math.round(v / BIAS_ROUNDING_DEG) * BIAS_ROUNDING_DEG).toFixed(2));
  const near: LonLat = [round(lon), round(lat)];
  // At the area's edge the rounded point can fall just outside it, where the API refuses a bias: then none, as Where to?.
  return insideCoverage(near) ? near : undefined;
}

/** What a detour search needs from the page; each is a function so a test runs it with stand-ins. */
export interface DetourDeps {
  /** Where the rider is (the ride's own fix). */
  here: LonLat;
  water: () => Promise<WaterPoint[] | null>;
  food: () => Promise<FoodPlace[] | null>;
  repair: () => Promise<RepairPlace[] | null>;
  /** The place search (through the page's one geocoding gate), near the rounded point given. */
  geocode: (query: string, near: LonLat | undefined) => Promise<GeoResult>;
  /** How far each place is to ride (requestNearest, on the ride's own settings). */
  request: (from: LonLat, places: readonly NearestPlace[]) => Promise<NearestResult>;
  now?: () => Date;
}

/** What a detour search asks for: a button's kind, or the box's words. */
export type DetourAsk = { kind: DetourKind } | { query: string };

export interface DetourFound {
  kind: DetourKind | "search";
  heading: string;
  items: Nearby[];
  /** The place search's credit, when its answers are in the list (shown under it, as Where to?'s). */
  attribution?: string[];
}

export interface DetourOutcome {
  said: string;
  found?: DetourFound;
}

export const FOOD_NOT_READY = t("The places to eat are unavailable for now; try again shortly.");
export const REPAIR_NOT_READY = t("Repair stands and bike shops are unavailable for now; try again shortly.");
export const SEARCH_TOO_SHORT = `Type at least ${MIN_QUERY_CHARS} letters to search.`;

/** Said as a search starts. */
export function detourFindingSaid(ask: DetourAsk): string {
  const kind = "kind" in ask ? ask.kind : kindForQuery(ask.query);
  if (kind === "water" || kind === "restroom") return findingSaid(kind);
  if (kind === "food") return "Finding the nearest places to eat.";
  if (kind === "repair") return "Finding the nearest repair stands and bike shops.";
  return `Searching for “${normalQuery("query" in ask ? ask.query : "")}”.`;
}

/** The status line once a list is in: how many, of what, and the list's rows, so a voice says them all. */
export function detourFoundSaid(kind: "food" | "repair" | "search", items: readonly Nearby[], query = ""): string {
  const q = `“${normalQuery(query)}”`;
  const [one, many] =
    kind === "food"
      ? ["place to eat", "places to eat"]
      : kind === "repair"
        ? ["repair stand or bike shop", "repair stands and bike shops"]
        : [`match for ${q}`, `matches for ${q}`];
  const lead = items.length === 1 ? `The nearest ${one} by bike.` : `The ${items.length} nearest ${many} by bike, nearest first.`;
  return `${lead} ${items.map(nearbyShort).join(" ")}`;
}

/** Nothing found for a kind, or the box's words. */
export function detourNoneSaid(kind: DetourKind | "search", query = ""): string {
  if (kind === "food") return "No places to eat found nearby.";
  if (kind === "repair") return "No repair stands or bike shops found nearby.";
  return `Nothing near you matches “${normalQuery(query)}”.`;
}

/** Measured by bike and ranked: the three nearest, or what went wrong. */
async function rank(deps: DetourDeps, kind: "food" | "repair" | "search", places: readonly NearestPlace[], query = ""): Promise<DetourOutcome> {
  if (places.length === 0) return { said: detourNoneSaid(kind, query) };
  const candidates = nearestInStraightLine(deps.here, places, NEAREST_CANDIDATES);
  const result = await deps.request(deps.here, candidates);
  if (!result.ok) return { said: `The search failed. ${result.message}` };
  const items = rankNearest(candidates, result.answer);
  if (items.length === 0) return { said: detourNoneSaid(kind, query) };
  return { said: detourFoundSaid(kind, items, query), found: { kind, heading: detourHeading(kind, query), items } };
}

/** Why the place search gave nothing to use. */
function geocodeFailed(result: GeoResult): string {
  if (result.ok) return "";
  if (result.status === 429) return "The place search is busy; try again in a moment.";
  if (result.status === 0) return "The search did not get through. Check your connection and try again.";
  return "The place search is unavailable for now; try again shortly.";
}

/** One detour search, start to end. */
export async function findDetour(deps: DetourDeps, ask: DetourAsk): Promise<DetourOutcome> {
  const query = "query" in ask ? normalQuery(ask.query) : "";
  const kind: DetourKind | null = "kind" in ask ? ask.kind : kindForQuery(query);
  if (kind === null && query.length < MIN_QUERY_CHARS) return { said: SEARCH_TOO_SHORT };
  if (!insideCoverage(deps.here)) return { said: LOCATION_OUTSIDE };
  if (kind === "water" || kind === "restroom") {
    const outcome = await searchNearest({
      kind,
      from: "location",
      locate: async () => rideLocate({ point: deps.here, accuracyM: 0 }),
      start: () => null,
      centre: () => null,
      inside: insideCoverage,
      water: deps.water,
      stations: [],
      request: deps.request,
    });
    return outcome.found
      ? { said: outcome.said, found: { kind, heading: detourHeading(kind), items: outcome.found.items } }
      : { said: outcome.said };
  }
  if (kind === "food") {
    const data = await deps.food();
    if (!data) return { said: FOOD_NOT_READY };
    return rank(deps, "food", foodNearestPlaces(data));
  }
  if (kind === "repair") {
    const data = await deps.repair();
    if (!data) return { said: REPAIR_NOT_READY };
    return rank(deps, "repair", repairNearestPlaces(data, deps.now?.() ?? new Date()));
  }
  // The box's own words: Find food's matches and the place search's answers, measured together.
  const terms = foodTerms(query);
  const [food, searched] = await Promise.all([
    deps.food().catch(() => null),
    deps.geocode(query, roundedBias(deps.here)).catch((): GeoResult => ({ ok: false, status: 0 })),
  ]);
  // A word that means every place ("anything") is not a food search here: only the place search answers it.
  const foodMatches = food && !terms.all ? foodNearestPlaces(food.filter((p) => matchesFood(p, terms))) : [];
  const found = searched.ok ? searchedPlaces(searched.places) : [];
  const places = mergeCandidates(foodMatches, found);
  // Neither answered: say why the place search did not, rather than that nothing matches.
  if (places.length === 0 && !searched.ok) return { said: geocodeFailed(searched) };
  const outcome = await rank(deps, "search", places, query);
  const credited = searched.ok && searched.attribution.length > 0 && outcome.found?.items.some((i) => i.place.id.startsWith("geo-"));
  return credited && outcome.found ? { ...outcome, found: { ...outcome.found, attribution: searched.attribution } } : outcome;
}
