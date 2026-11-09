/**
 * Food words in the search box (Stephen 2026-11-09: "Is it possible for the search box to also do a more general search
 * like "grocery stores" or "tacos"?"). The place search finds places by name, so "tacos" found only places named Taco;
 * the Eat sheet's places (amenity-data/food.json, lib/food.ts) know each one's cuisine. A query that is a word for food
 * ("tacos", "pizza", "coffee", "crab", "chinese food", "lunch") lists the places to eat that match it, nearest first,
 * ahead of the place search's own rows, as Ride's Detour box does (lib/detourSearch.ts). A name or an address
 * ("Safeway", "Satay Club") is a place search only, as before. Grocery stores stay the server's (core/geocode.py
 * TAG_SEARCHES). No new control: the same box, the same rows.
 *
 * Plain data in, plain data out, so node --test runs all of it; the box is PlaceSearch.tsx.
 */
import { ALL_FOOD_WORDS, CUISINE_WORDS, FOOD_SYNONYMS, foodKindText, foodTerms, matchesFood, normaliseQuery, type FoodKind, type FoodPlace } from "./food.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { kindPhrase, type Place } from "./geocode.ts";

/** How many places to eat lead the list: the rest of the box's rows still show under them. */
export const FOOD_ROWS = 5;

/** Words for food in general that mean more than food in a place search ("all", "anything"). */
const NOT_ONLY_FOOD = new Set(["all", "any", "anything", "everything"]);
/** Words after a cuisine that only say "a place for it": "chinese food", "pizza places", "taco spot". */
const PLACE_TAILS = ["food", "restaurant", "restaurants", "place", "places", "spot", "spots", "shop", "shops", "joint", "joints"];

const singulars = (word: string): string[] => {
  const out = [word];
  if (word.endsWith("es") && word.length > 4) out.push(word.slice(0, -2));
  if (word.endsWith("s") && !word.endsWith("ss") && word.length > 3) out.push(word.slice(0, -1));
  return out;
};

const isCuisine = (words: string): boolean =>
  singulars(words).some((w) => w in FOOD_SYNONYMS || CUISINE_WORDS.has(w)) || CUISINE_WORDS.has(words);

/** The food words a query is, as Find food reads them ("chinese food" is "chinese"), or null for a name or an address. */
export function foodWords(query: string): string | null {
  const q = kindPhrase(normaliseQuery(query));
  if (!q) return null;
  if (ALL_FOOD_WORDS.has(q)) return NOT_ONLY_FOOD.has(q) ? null : q;
  if (isCuisine(q)) return q;
  for (const tail of PLACE_TAILS) {
    if (q.endsWith(` ${tail}`)) {
      const head = q.slice(0, -tail.length - 1);
      if (isCuisine(head)) return head;
    }
  }
  return null;
}

/** The OSM tag each kind of place to eat is mapped with (scripts/build_food.py), so the row's type is "Food and drink". */
const KIND_TAG: Record<FoodKind, [string, string]> = {
  r: ["amenity", "restaurant"],
  f: ["amenity", "fast_food"],
  c: ["amenity", "cafe"],
  i: ["amenity", "ice_cream"],
  p: ["amenity", "pub"],
  b: ["amenity", "biergarten"],
  fc: ["amenity", "food_court"],
  fs: ["shop", "farm"],
  m: ["amenity", "marketplace"],
  g: ["shop", "supermarket"],
};

const OSM_TYPE = { n: "N", w: "W", r: "R" } as const;

/** A place to eat as a search row: its name, and what it is ("Restaurant: mexican") where the label says where. */
export function foodPlaceRow(place: FoodPlace): Place {
  const [key, value] = KIND_TAG[place.kind];
  const type = OSM_TYPE[place.id.charAt(0) as keyof typeof OSM_TYPE];
  const id = Number(place.id.slice(1));
  return {
    name: place.name,
    label: `${place.name}, ${foodKindText(place)}`,
    lon: place.lon,
    lat: place.lat,
    kind: "food",
    osm_type: type ?? null,
    osm_id: type && Number.isSafeInteger(id) ? id : null,
    osm_key: key,
    osm_value: value,
  };
}

/**
 * The places to eat a food word finds, nearest `near` first, at most FOOD_ROWS; none for a query that is not a food
 * word, before the places have loaded, or with no point to measure from.
 */
export function foodRows(query: string, places: readonly FoodPlace[] | null, near: LonLat | undefined): Place[] {
  const words = foodWords(query);
  if (words === null || !places || !near) return [];
  const terms = foodTerms(words);
  return places
    .filter((p) => matchesFood(p, terms))
    .map((p) => ({ p, m: haversineM(near, [p.lon, p.lat]) }))
    .sort((a, b) => a.m - b.m)
    .slice(0, FOOD_ROWS)
    .map(({ p }) => foodPlaceRow(p));
}

/** The place search's rows without those that are a place to eat already listed (the same name within 50 m, 165 ft). */
export function withoutFoodRows(found: readonly Place[], food: readonly Place[]): Place[] {
  const same = (a: Place, b: Place) =>
    normaliseQuery(a.name) === normaliseQuery(b.name) && haversineM([a.lon, a.lat], [b.lon, b.lat]) < 50;
  return found.filter((f) => !food.some((p) => same(p, f)));
}
