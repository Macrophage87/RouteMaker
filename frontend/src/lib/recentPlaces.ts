/**
 * Recent places (Stephen 2026-10-15): tapping the empty search box lists
 * "Your location" and then the last places picked from search, newest first,
 * so a place used before is one tap away. Kept on this device only
 * (localStorage); a refusing store just means no list.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import type { Place } from "./geocode.ts";

export const RECENT_PLACES_KEY = "routemaker.recentPlaces";
export const RECENT_PLACES_MAX = 5;

/** One place, matched across searches by its OSM element, else by name and spot (to about 36 ft (11 m)). */
export function placeKey(place: Place): string {
  if (place.osm_type && place.osm_id) return `${place.osm_type}${place.osm_id}`;
  return `${place.name}|${place.lon.toFixed(4)},${place.lat.toFixed(4)}`;
}

/** The list with `place` first, any earlier copy of it dropped, cut to the most kept. */
export function withRecent(list: readonly Place[], place: Place, max = RECENT_PLACES_MAX): Place[] {
  const key = placeKey(place);
  return [place, ...list.filter((p) => placeKey(p) !== key)].slice(0, max);
}

function isPlace(value: unknown): value is Place {
  if (typeof value !== "object" || value === null) return false;
  const p = value as Record<string, unknown>;
  return (
    typeof p.name === "string" &&
    typeof p.label === "string" &&
    typeof p.kind === "string" &&
    typeof p.lon === "number" &&
    Number.isFinite(p.lon) &&
    typeof p.lat === "number" &&
    Number.isFinite(p.lat)
  );
}

/** The kept list, newest first; empty when nothing is kept or the store refuses or holds something else. */
export function readRecentPlaces(store: KeyValueStore | null = browserStore()): Place[] {
  try {
    const raw = store?.getItem(RECENT_PLACES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isPlace).slice(0, RECENT_PLACES_MAX) : [];
  } catch {
    return [];
  }
}

/** Put `place` at the top of the kept list and return the new list (unchanged in storage if it refuses). */
export function rememberRecentPlace(place: Place, store: KeyValueStore | null = browserStore()): Place[] {
  const next = withRecent(readRecentPlaces(store), place);
  try {
    store?.setItem(RECENT_PLACES_KEY, JSON.stringify(next));
  } catch {
    // Storage refused: the list lasts this visit only.
  }
  return next;
}
