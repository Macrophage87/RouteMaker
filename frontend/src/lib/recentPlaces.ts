/**
 * Recent places (Stephen 2026-10-15): tapping the empty search box lists
 * "Your location" and then the last places picked from search, newest first,
 * so a place used before is one tap away. Kept on this device only
 * (localStorage), and each for `RECENT_PLACES_DAYS` after it was last picked:
 * an older one is dropped when the list is next read, so the device does not
 * keep a lasting record of where its rider has been going. A refusing store
 * just means no list.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import type { Place } from "./geocode.ts";

export const RECENT_PLACES_KEY = "routemaker.recentPlaces";
export const RECENT_PLACES_MAX = 5;
/** How long a place stays in the list after it was last picked. */
export const RECENT_PLACES_DAYS = 30;
const KEEP_MS = RECENT_PLACES_DAYS * 24 * 60 * 60 * 1000;

/** A kept place with when it was last picked (ms since the epoch); a list from before has none. */
type Kept = Place & { at?: number };
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

function readKept(store: KeyValueStore | null, now: number): Kept[] {
  try {
    const raw = store?.getItem(RECENT_PLACES_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const valid = parsed.filter(isPlace).slice(0, RECENT_PLACES_MAX) as Kept[];
    // A place from a list kept before dates were: its time starts now.
    const dated = valid.map((p) => (typeof p.at === "number" && Number.isFinite(p.at) ? p : { ...p, at: now }));
    const kept = dated.filter((p) => now - (p.at as number) < KEEP_MS);
    if (kept.length !== parsed.length || dated.some((p, i) => p !== valid[i])) writeKept(store, kept);
    return kept;
  } catch {
    return [];
  }
}

function writeKept(store: KeyValueStore | null, list: readonly Kept[]): void {
  try {
    store?.setItem(RECENT_PLACES_KEY, JSON.stringify(list));
  } catch {
    // Storage refused: the list lasts this visit only.
  }
}

function placeOf(kept: Kept): Place {
  const { at: _at, ...place } = kept;
  return place;
}

/**
 * The kept list, newest first, without the places past `RECENT_PLACES_DAYS` (which go from the store too); empty when
 * nothing is kept or the store refuses or holds something else.
 */
export function readRecentPlaces(store: KeyValueStore | null = browserStore(), now: number = Date.now()): Place[] {
  return readKept(store, now).map(placeOf);
}

/** Put `place` at the top of the kept list and return the new list (unchanged in storage if it refuses). */
export function rememberRecentPlace(place: Place, store: KeyValueStore | null = browserStore(), now: number = Date.now()): Place[] {
  const kept = readKept(store, now);
  const next = withRecent(kept, { ...placeOf(place), at: now } as Kept) as Kept[];
  writeKept(store, next);
  return next.map(placeOf);
}
