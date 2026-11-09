/**
 * Find food's places (amenity-data/food.json), fetched once for the whole page: the Eat sheet, Ride's Detour and Roam
 * menus, the tapped spot's card and the search box's food words (lib/placeFood.ts) share one load. A load that failed
 * is asked again next time.
 */
import { loadFood, type FoodPlace } from "../lib/food.ts";
// food.json is a committed snapshot, as climbs.json, refreshed with scripts/build_food.py and committed. `no-inline`, as
// climbs.json: an inlined data: URL is refused by the edge's connect-src 'self'. Its own hashed file under /assets/ also
// lets the service worker leave it out of the precache (swCore.mjs LAZY_ASSET).
import foodUrl from "../amenity-data/food.json?url&no-inline";

let load: Promise<FoodPlace[] | null> | null = null;

export function sharedFood(): Promise<FoodPlace[] | null> {
  if (!load) {
    load = loadFood(foodUrl).then((data) => {
      if (!data) load = null;
      return data;
    });
  }
  return load;
}
