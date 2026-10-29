/**
 * The Eat sheet's Grocery chip (the owner, 2026-10-28: a "Grocery" chip listing grocery stores and supermarkets
 * nearest the start, in the same rows as the other results). The places to eat (amenity-data/food.json,
 * scripts/build_food.py) hold no shops but farm stands, so the stores come from the geocoder: /api/geocode answers
 * "supermarket" near a point with the places tagged shop=supermarket around it (src/core/geocode.py TAG_SEARCHES),
 * here biased on the route's start. They are listed nearest the start first with P2's sorter (lib/geocode.ts
 * nearestFirst), as FoodResults, so the list, the lettered markers, Show on map, Ride here and Add as stop are the
 * Food sheet's own. The geocoder has no opening hours, so a store's row has none.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import type { FoodPlace, FoodResult } from "./food.ts";
import { normaliseQuery } from "./food.ts";
import { haversineM, insideCoverage, type LonLat } from "./geo.ts";
import { kindPhrase, nearestFirst, type Place } from "./geocode.ts";
import { t } from "./i18n.ts";

/** What the chip asks the geocoder: one of the server's tag searches (shop=supermarket near the bias point). */
export const GROCERY_QUERY = "supermarket";

/** The chip's words, typed into Food or name, search for grocery stores too (English and Spanish), "near me" or not. */
const GROCERY_WORDS: ReadonlySet<string> = new Set([
  "grocery",
  "groceries",
  "grocery store",
  "grocery stores",
  "supermarket",
  "supermarkets",
  "supermercado",
  "supermercados",
]);

export function isGroceryQuery(query: string): boolean {
  return GROCERY_WORDS.has(kindPhrase(normaliseQuery(query)));
}

/** OSM shop values that are a grocery: the server's tag search returns supermarkets; a greengrocer or corner store is one too. */
const GROCERY_SHOPS: ReadonlySet<string> = new Set(["supermarket", "greengrocer", "convenience", "grocery", "food"]);

/** Where the distances are from: the rider's location, the start typed or placed, or (neither known) the map's center. */
export type GroceryFrom = "rider" | "start" | "centre";

/**
 * The stores found, nearest `origin` first (nearestFirst), as the Food sheet's results: in the coverage, shops of a
 * grocery kind only where the geocoder says what the place is, one row per OSM element.
 */
export function groceryResults(places: readonly Place[], origin: LonLat, from: GroceryFrom): FoodResult[] {
  const seen = new Set<string>();
  const out: FoodResult[] = [];
  // No words to rank by name: a store called "… Supermarket" is not put ahead of a nearer one.
  nearestFirst(places, origin, "").forEach((found, i) => {
    if (!insideCoverage([found.lon, found.lat])) return;
    if (found.osm_key && !(found.osm_key === "shop" && GROCERY_SHOPS.has(found.osm_value ?? ""))) return;
    const id = found.osm_type && found.osm_id ? `${found.osm_type.toLowerCase()}${found.osm_id}` : `g${i}`;
    if (seen.has(id)) return;
    seen.add(id);
    const place: FoodPlace = { id, lon: found.lon, lat: found.lat, kind: "g", name: found.name, cuisine: [] };
    const result: FoodResult = { place, fromCentreM: haversineM(origin, [found.lon, found.lat]) };
    if (from === "rider") result.fromRider = true;
    if (from === "start") result.fromStart = true;
    out.push(result);
  });
  return out;
}

export const GROCERY_HEADING = t("Grocery stores");
export const GROCERY_LOOKING = t("Looking for grocery stores…");
export const GROCERY_UNAVAILABLE = t("The grocery store search is unavailable for now; try again shortly.");

/** The status line after the chip: how many, and where from. */
export function groceryFoundSaid(total: number, from: GroceryFrom): string {
  if (total === 0) return t("No grocery stores found near here.");
  const order = from === "rider" ? t("nearest you first") : from === "start" ? t("nearest your start first") : t("nearest the map's center first");
  return total === 1 ? t("1 grocery store, {order}.", { order }) : t("{n} grocery stores, {order}.", { n: total, order });
}
