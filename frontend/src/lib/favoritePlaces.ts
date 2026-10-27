/**
 * Favorite places (Stephen 2026-10-26: "For signed in users, allow for favorite destinations"; "just have a
 * favorites replace home"; "Home and if set work would be the top 2 favorites"; "we'd have a popout").
 *
 * Signed in, Go's Home chip is a Favorites chip that pops out the rider's places: Home first, then Work once it is
 * set, then the rest in the order they were added. One tap on a row rides there. Signed out, Home stays its own chip
 * and nothing here applies.
 *
 * Saved to the account only (GET and POST /api/me/places; core.models.MyGo.places), never on the device or in a
 * log, and deleted with the account. Riding to one makes it the plan's destination, so it is in that plan's link, as
 * any destination is. Home stays My Go's (lib/myGo.ts); Work is the one place marked
 * `work`. At most FAVORITE_PLACES_MAX places, Work among them.
 */
import type { LonLat } from "./geo.ts";
import { coordinatesText, type Place } from "./geocode.ts";
import { csrfFromCookie } from "./stressEditor.ts";
import { t } from "./i18n.ts";

export interface FavoritePlace {
  point: LonLat;
  label: string;
  /** The rider's Work: at most one, listed second, after Home. */
  work?: boolean;
}

/** core.api.FAVORITE_PLACES_MAX. */
export const FAVORITE_PLACES_MAX = 20;

export const FAVORITES_TEXT = "Favorites";
export const WORK_TEXT = "Work";
export const SET_HOME_TEXT = t("Set Home");
export const SET_WORK_TEXT = t("Set Work");
export const ADD_FAVORITE_TEXT = t("Add a place");
/** The road panel's "Use this spot" row, beside Set as Home, and the ride summary's for the ride's destination. */
export const SAVE_SPOT_TEXT = t("Save to Favorites");
/** The ride summary's line once its destination is a favorite. */
export const SAVED_TO_FAVORITES = (name: string) => `${name} is in your Favorites.`;
export const EDIT_FAVORITES_TEXT = "Edit";
export const DONE_EDITING_TEXT = "Done";
export const FAVORITES_FULL = `Favorites hold ${FAVORITE_PLACES_MAX} places. Remove one to add another.`;
export const FAVORITES_NOT_SAVED = t("Favorites could not be saved. Try again.");
/** The popout's line while the account's list is read. */
export const FAVORITES_LOADING = t("Loading your favorites…");
/** Before the account's list is read (a save is the whole list, so none goes before then). */
export const FAVORITES_NOT_LOADED = t("Your favorites are still loading. Try again in a moment.");

/** Two points are one place when they round to the same spot (about a metre, as the server keeps them). */
export function samePoint(a: LonLat, b: LonLat): boolean {
  return a[0].toFixed(5) === b[0].toFixed(5) && a[1].toFixed(5) === b[1].toFixed(5);
}

/** A place's name as shown and said: its label, else its coordinates. */
export function favoriteName(place: FavoritePlace): string {
  return place.label.trim() || coordinatesText(place.point);
}

/** A searched place as a favorite. */
export function favoriteFromPlace(place: Pick<Place, "lon" | "lat" | "name">, work = false): FavoritePlace {
  return work ? { point: [place.lon, place.lat], label: place.name, work: true } : { point: [place.lon, place.lat], label: place.name };
}

/** The places an answer holds that make sense, each spot once, at most one Work, cut to the most kept. */
export function parseFavoritePlaces(raw: unknown): FavoritePlace[] {
  const list = raw && typeof raw === "object" ? (raw as { places?: unknown }).places : undefined;
  if (!Array.isArray(list)) return [];
  const out: FavoritePlace[] = [];
  let work = false;
  for (const value of list) {
    if (!value || typeof value !== "object") continue;
    const p = value as { lon?: unknown; lat?: unknown; label?: unknown; work?: unknown };
    if (typeof p.lon !== "number" || typeof p.lat !== "number" || !Number.isFinite(p.lon) || !Number.isFinite(p.lat)) continue;
    const point: LonLat = [p.lon, p.lat];
    if (out.some((f) => samePoint(f.point, point))) continue;
    const label = typeof p.label === "string" ? p.label : "";
    const isWork: boolean = p.work === true && !work;
    work ||= isWork;
    out.push(isWork ? { point, label, work: true } : { point, label });
    if (out.length === FAVORITE_PLACES_MAX) break;
  }
  return out;
}

/** The body POST /api/me/places takes: the whole list. */
export function favoritePlacesBody(places: readonly FavoritePlace[]): { places: { lon: number; lat: number; label: string; work: boolean }[] } {
  return {
    places: places.map((p) => ({ lon: p.point[0], lat: p.point[1], label: (p.label.trim() || coordinatesText(p.point)).slice(0, 120), work: p.work === true })),
  };
}

/** The rider's Work, if set. */
export function workOf(places: readonly FavoritePlace[]): FavoritePlace | null {
  return places.find((p) => p.work) ?? null;
}

/** The places after Home and Work, in the order they were added. */
export function othersOf(places: readonly FavoritePlace[]): FavoritePlace[] {
  return places.filter((p) => !p.work);
}

/**
 * The list with a place added last, or null when it is full. A place already there stays where it is (and
 * keeps being Work if it is).
 */
export function withFavorite(places: readonly FavoritePlace[], place: FavoritePlace): FavoritePlace[] | null {
  if (places.some((p) => samePoint(p.point, place.point))) return [...places];
  if (places.length >= FAVORITE_PLACES_MAX) return null;
  return [...places, { point: place.point, label: place.label }];
}

/**
 * The list with Work set to a place (or with null, cleared): the old Work goes, and the place, if it was already a
 * favorite, becomes Work in its place rather than being listed twice. Null when the list is full.
 */
export function withWork(places: readonly FavoritePlace[], place: FavoritePlace | null): FavoritePlace[] | null {
  const rest = places.filter((p) => !p.work && !(place && samePoint(p.point, place.point)));
  if (!place) return rest;
  if (rest.length >= FAVORITE_PLACES_MAX) return null;
  return [{ point: place.point, label: place.label, work: true }, ...rest];
}

/** The list without a place. */
export function withoutFavorite(places: readonly FavoritePlace[], place: FavoritePlace): FavoritePlace[] {
  return places.filter((p) => !samePoint(p.point, place.point));
}

/** Said once a place is saved, or removed. */
export function favoriteSavedSaid(place: FavoritePlace): string {
  return place.work ? `Work set to ${favoriteName(place)}.` : `${favoriteName(place)} saved to Favorites.`;
}
export function favoriteRemovedSaid(place: FavoritePlace): string {
  return place.work ? "Work cleared." : `${favoriteName(place)} removed from Favorites.`;
}

type Fetch = typeof fetch;

/** GET /api/me/places: the account's places, or null when signed out or unreadable. */
export async function fetchFavoritePlaces(origin: string, get: Fetch = fetch): Promise<FavoritePlace[] | null> {
  try {
    const response = await get(`${origin}/api/me/places`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return null;
    return parseFavoritePlaces(await response.json());
  } catch {
    return null;
  }
}

/** POST /api/me/places: the places as saved, or null when the save failed. */
export async function saveFavoritePlaces(
  origin: string,
  places: readonly FavoritePlace[],
  post: Fetch = fetch,
  cookie = typeof document === "undefined" ? "" : document.cookie,
): Promise<FavoritePlace[] | null> {
  try {
    const token = csrfFromCookie(cookie);
    const response = await post(`${origin}/api/me/places`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: JSON.stringify(favoritePlacesBody(places)),
    });
    if (!response.ok) return null;
    return parseFavoritePlaces(await response.json());
  } catch {
    return null;
  }
}

/**
 * Saves of the whole list, one after another (each POST replaces the account's list, so two in flight could land out
 * of order). Each sends the list as it is when its turn comes; once it answers, if nothing changed meanwhile, the list
 * shown becomes the account's answer, or on a refusal the list the account last confirmed, and `refused` is called.
 */
export function favoritesSaver(
  save: (places: readonly FavoritePlace[]) => Promise<FavoritePlace[] | null>,
  current: () => FavoritePlace[] | null,
  show: (places: FavoritePlace[]) => void,
  refused: () => void,
) {
  let confirmed: FavoritePlace[] = [];
  let queue: Promise<void> = Promise.resolve();
  return {
    /** The account's list, as read. */
    loaded(places: FavoritePlace[]): void {
      confirmed = places;
    },
    /** A change shown: saved in turn. Resolves once this save has answered. */
    changed(): Promise<void> {
      queue = queue.then(async () => {
        const sent = current();
        if (sent === null) return;
        const saved = await save(sent);
        if (saved) confirmed = saved;
        if (current() !== sent) return;
        show(saved ?? confirmed);
        if (!saved) refused();
      });
      return queue;
    },
  };
}
