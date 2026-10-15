/**
 * Setting Home simply (v0.7.0; Stephen 2026-10-15: "Setting home seems complicated. You should be able to set it
 * with a map tap or address search."). Home is set in one of two ways, both with what the app already has:
 *
 * - Search: the place search box (PlaceSearch, variant "home"), in Go's Home sheet (the Home chip, with no Home
 *   yet; "Change Home" under More once there is one) and in Settings, My Go.
 * - The map: press and hold (or right-click) a spot, then "Set as Home" in the road panel's "Use this spot" row,
 *   or "Pick on the map" in the Home sheet, then a tap on the map.
 *
 * Presses to set Home with no Home yet (the owner's targets: 3 or fewer with search, 2 from the map):
 *
 *   before                                        after
 *   search: Home chip (Settings opens, scrolled   search: Home chip, the search box, a result (3)
 *     to My Go), the search box, a result (3)
 *   map: no way                                   map: hold the spot, Set as Home (2);
 *                                                   or Home chip, Pick on the map, the spot (3)
 *
 * Signed in, Home is saved to the account (POST /api/me/go, as before); signed out, on this device (lib/myGo.ts).
 * Every way says "Home set to <name>." through the page's polite region, and none moves the focus.
 */
import type { LonLat } from "./geo.ts";
import { coordinatesText, type GeoResult, type Place } from "./geocode.ts";
import type { Home } from "./myGo.ts";

/** The road panel's "Use this spot" button, and what the Home sheet's map way is called. */
export const SET_AS_HOME_TEXT = "Set as Home";
export const PICK_ON_MAP_TEXT = "Pick on the map";
/** Go's one line while the Home sheet's map way waits for a tap. */
export const HOME_PICK_LINE = "Tap the map where Home is.";
/** The More row's chip, once there is a Home: the same sheet, to change or clear it. */
export const CHANGE_HOME_TEXT = "Change Home";
export const CLEAR_HOME_TEXT = "Clear Home";

/** Said once Home is set, whichever way. */
export function homeSetSaid(home: Home): string {
  return `Home set to ${homeName(home)}.`;
}
export const HOME_CLEARED = "Home cleared.";
export const HOME_PICK_CANCELLED = "Home not changed.";

/** Home's name as shown and said: its label, else its coordinates. */
export function homeName(home: Home): string {
  return home.label.trim() || coordinatesText(home.point);
}

/** A searched place as Home. */
export function homeFromPlace(place: Pick<Place, "lon" | "lat" | "name">): Home {
  return { point: [place.lon, place.lat], label: place.name };
}

/**
 * A spot on the map as Home: named by a name the page already has for it, else the reverse look-up's first
 * answer, else its coordinates. The point is the spot pressed, not the answer's (a house, not the street's middle).
 */
export function homeAtSpot(point: LonLat, known: string | undefined, reverse: GeoResult | null): Home {
  const found = reverse && reverse.ok ? reverse.places[0]?.name : undefined;
  return { point, label: (known || found || coordinatesText(point)).slice(0, 120) };
}
