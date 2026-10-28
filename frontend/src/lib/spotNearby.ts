/**
 * Go's card for a tapped spot (Stephen, 2026-10-28: "For routing, on a click instead of showing the road, show the
 * address and what's near"; then "Let them show all on the map so you can select them" and "Maybe just show that in
 * most cases. For restaurants and the like, label them"): the spot's address from the reverse geocoder, the big Route
 * here, and one line, "5 places nearby, shown on the map". The places are pins on the map: a named place (a
 * restaurant, a café, a bike shop, a place to see, a Metro station) with its name beside its icon, water, a restroom
 * or a repair stand with its icon alone. A pin opens the place's own card (lib/stopCard.ts), never a route by itself.
 * The same places are a list behind the card's folded List, for a screen reader and the keyboard.
 *
 * The places are the ones the map already has (no new API): drinking water and restrooms (lib/waterRestrooms.ts),
 * Find food's places (lib/food.ts), repair stands and bike shops (lib/repair.ts), places to see (lib/places.ts) and
 * the Metro's stations (lib/nearest.ts metroPlaces). Distances are straight lines from the spot: the list is what is
 * near, not a plan. Variety first: the nearest of each kind within a mile, nearest first, then the next nearest of
 * any kind while the list is short. Plain data in, plain data out, so node --test runs all of it; the card is
 * GoSpotDialog.tsx and the pins app/spotPins.ts.
 */
import { foodHoursText, foodKindText, type FoodPlace } from "./food.ts";
import { formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import type { GeoResult } from "./geocode.ts";
import type { IconName } from "./iconPaths.ts";
import { metroPlaces, waterPlaces, type NearestPlace } from "./nearest.ts";
import { categoryOf, type SightPlace } from "./places.ts";
import { repairDetails, type RepairPlace } from "./repair.ts";
import type { Station } from "./railStations.ts";
import type { StopCardWords } from "./stopCard.ts";
import { REPAIR_CAUTION } from "./stopWords.ts";
import type { WaterPoint } from "./waterRestrooms.ts";
import { t } from "./i18n.ts";

export type SpotKind = "food" | "water" | "restroom" | "repair" | "metro" | "sight";

/** A place the card may offer: its name and kind for the list and the pin, and its card's words at a distance. */
export interface SpotPlace {
  id: string;
  kind: SpotKind;
  point: LonLat;
  /** The list's bold text: the place's own name, else what it is ("Drinking water"). */
  name: string;
  /** What it is, short ("Café", "Restroom", "Metro: Red line"); "" where the name already says it. */
  kindText: string;
  /** The pin's label, its own name (a restaurant, a shop, a sight, a station); null for an icon alone (water). */
  label: string | null;
  /** The pin's icon (lib/iconPaths.ts). */
  icon: IconName;
  /** The card's words (lib/stopCard.ts), with how far from the spot as its last fact. */
  words: (far: string, at: Date) => StopCardWords;
}

export interface SpotRow extends SpotPlace {
  /** Straight line from the spot, metres. */
  metres: number;
}

/** How far the card looks: a mile (1.6 km), a short ride from the spot. */
export const SPOT_NEAR_M = 1609;
/** How many places at most (Stephen hates clutter). */
export const SPOT_MAX = 6;
/** Below this many kinds found, the next nearest of any kind fill the list up to it. */
export const SPOT_MIN = 4;

export const NEARBY_HEADING = t("Nearby");
export const FINDING_ADDRESS = t("Finding the address…");
export const DROPPED_PIN = t("Dropped pin");
export const NOTHING_NEAR = t("Nothing useful within a mile.");
export const NEARBY_LOADING = t("Looking for places nearby…");
export const ROAD_INFO_TEXT = t("Road info");
/** The folded list's button: the same places as the pins, for a screen reader and the keyboard. */
export const SPOT_LIST_TEXT = t("List");

const KIND_SHORT: Record<SpotKind, string> = {
  food: t("Food"),
  water: t("Water"),
  restroom: t("Restroom"),
  repair: t("Repair"),
  metro: "Metro",
  sight: t("Place to see"),
};

/** The card's one line: "5 places nearby, shown on the map." */
export function spotCountLine(count: number): string {
  return count === 1 ? t("1 place nearby, shown on the map.") : t("{count} places nearby, shown on the map.", { count });
}

/** The card's line for how far: "0.2 mi (0.3 km) from the spot you tapped." */
export function spotFarLine(metres: number): string {
  return t("{distance} from the spot you tapped.", { distance: formatDistance(metres) });
}

/** How far the spot is from the rider, in a straight line: "2.1 mi (3.4 km) away"; "" with no location. */
export function spotAwayText(spot: LonLat, here: LonLat | null | undefined): string {
  return here ? t("{distance} away", { distance: formatDistance(haversineM(here, spot)) }) : "";
}

/** A row's or a pin's name in full, as a screen reader says it: "Peet's Coffee, Café, 0.2 mi (0.3 km)". */
export function spotRowName(row: SpotRow): string {
  return [row.name, row.kindText, formatDistance(row.metres)].filter(Boolean).join(", ");
}

const fromNearest = (kind: SpotKind, p: NearestPlace, kindText: string, icon: IconName, labelled: boolean): SpotPlace => ({
  id: p.id,
  kind,
  point: p.point,
  name: p.name ?? p.title,
  kindText: p.name ? kindText : "",
  label: labelled ? (p.name ?? null) : null,
  icon,
  words: (far) => ({ title: p.title, lines: [...p.details, far] }),
});

/** Drinking water and restrooms, as the nearest finder has them (untreated water left out): icons alone. */
export function waterSpotPlaces(points: readonly WaterPoint[]): SpotPlace[] {
  return [
    ...waterPlaces(points, "water").map((p) => fromNearest("water", p, KIND_SHORT.water, "water", false)),
    ...waterPlaces(points, "restroom").map((p) => fromNearest("restroom", p, KIND_SHORT.restroom, "wc", false)),
  ];
}

export function foodSpotPlaces(places: readonly FoodPlace[]): SpotPlace[] {
  return places.map((place) => ({
    id: place.id,
    kind: "food" as const,
    point: [place.lon, place.lat] as LonLat,
    name: place.name || foodKindText(place),
    kindText: place.name ? foodKindText(place) : "",
    label: place.name || null,
    icon: "food" as const,
    words: (far: string, at: Date) => {
      const hours = foodHoursText(place, at);
      return { title: place.name || foodKindText(place), lines: [`${foodKindText(place)}.`, ...(hours ? [hours] : []), far], website: place.website };
    },
  }));
}

/** A bike shop is labelled with its name; a repair stand is its icon alone. */
export function repairSpotPlaces(places: readonly RepairPlace[]): SpotPlace[] {
  return places.map((place) => {
    const kind = place.kind === "stand" ? t("Repair stand") : t("Bike shop");
    return {
      id: place.id,
      kind: "repair" as const,
      point: [place.lon, place.lat] as LonLat,
      name: place.name || kind,
      kindText: place.name ? kind : "",
      label: place.kind === "shop" ? (place.name ?? null) : null,
      icon: "wrench" as const,
      words: (far: string, at: Date) => ({
        title: place.name ? `${kind}, ${place.name}` : kind,
        lines: [...repairDetails(place, at), far, REPAIR_CAUTION],
        website: place.website,
      }),
    };
  });
}

export function sightSpotPlaces(places: readonly SightPlace[]): SpotPlace[] {
  return places.map((place) => ({
    id: place.id,
    kind: "sight" as const,
    point: [place.lon, place.lat] as LonLat,
    name: place.name,
    kindText: categoryOf(place).one,
    label: place.name || null,
    icon: "star" as const,
    words: (far: string) => ({ title: place.name, lines: [`${categoryOf(place).one}.`, far], website: place.website }),
  }));
}

/** The Metro's stations, each at its bike entrance, labelled with the station's name; "Metro: Red line" in the list. */
export function metroSpotPlaces(stations: readonly Station[], closedReason?: (station: Station) => string | null): SpotPlace[] {
  return metroPlaces(stations, closedReason).map((p) => {
    const station = stations.find((s) => s.id === p.id);
    const lines = p.details[0]?.replace(/\.$/, "") ?? "";
    return fromNearest("metro", { ...p, name: station?.name ?? p.title }, lines ? `Metro: ${lines}` : "Metro", "train", true);
  });
}

/**
 * The places for `from`: the nearest of each kind within `withinM`, nearest first, up to `max`; where fewer than `min`
 * are found that way, the next nearest of any kind fill it up to `min`. A tie keeps the given order.
 */
export function spotNearby(from: LonLat, places: readonly SpotPlace[], withinM = SPOT_NEAR_M, max = SPOT_MAX, min = SPOT_MIN): SpotRow[] {
  const near = places
    .map((place, index) => ({ place, index, metres: haversineM(from, place.point) }))
    .filter((p) => p.metres <= withinM)
    .sort((a, b) => a.metres - b.metres || a.index - b.index);
  const firsts: typeof near = [];
  const seen = new Set<SpotKind>();
  for (const p of near) {
    if (seen.has(p.place.kind)) continue;
    seen.add(p.place.kind);
    firsts.push(p);
  }
  const chosen = firsts.slice(0, max);
  for (const p of near) {
    if (chosen.length >= Math.min(min, max)) break;
    if (!chosen.includes(p)) chosen.push(p);
  }
  return chosen.sort((a, b) => a.metres - b.metres || a.index - b.index).map(({ place, metres }) => ({ ...place, metres }));
}

/** The card's heading and the line under it, from the reverse geocoder's answer. */
export interface SpotAddress {
  /** The address or the nearest named place ("Connecticut Avenue Northwest", "Near White House"); never coordinates. */
  heading: string;
  /** The rest of its label ("Dupont Circle, Washington"), or "". */
  area: string;
}

/**
 * The address for the card: the geocoder's first answer, its "near White House" given a capital; where it has none
 * or failed, `fallback` (a name the page already has for the spot, a street), else "Dropped pin". Never lat/lon.
 */
export function spotAddress(result: GeoResult | null, fallback?: string | null): SpotAddress {
  const place = result && result.ok ? result.places[0] : undefined;
  const name = place?.name.trim();
  if (!place || !name) return { heading: fallback?.trim() || DROPPED_PIN, area: "" };
  const label = place.label.trim();
  const rest = label === name ? "" : label.startsWith(`${name}, `) ? label.slice(name.length + 2) : label;
  return { heading: `${name.charAt(0).toUpperCase()}${name.slice(1)}`, area: rest };
}
