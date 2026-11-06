/**
 * MILE MARKERS ON THE ROUTE. The owner, 2026-11-06: "Put a dot on the route track every mile (or km in the case of
 * metric) and every 5 miles put the mile number in a larger dot." A small white dot every mile (every kilometre in
 * metric, Settings > Display > Units, lib/units.ts) and, every fifth, a larger one with the number in it, along the
 * route's line in Plan, Go and a ride.
 *
 * Counted in the route's own distance (the description's metres, the same the turn list and the totals give), put on
 * the line through measureMap, so the 5 sits where the turn list says five miles. White on a near-black ring reads on
 * every route colour, on the light map and the dark one; the accessibility switch makes the ring and the dots
 * larger. Zoomed out the small dots come off first, then the numbered ones, so a long route is not a string of beads.
 * Not drawn while the route is greyed for a new plan. On the canvas only: the turn list says the distances in words.
 */
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { lineAlong, measureMap } from "./navigate.ts";
import { units, type Units } from "./units.ts";
import { MAP_LABEL_FONT } from "./mapGlyphs.ts";
import { METRES_PER_MILE } from "./format.ts";
import { accessibilityOn } from "../stressStyle.js";

export const ROUTE_MILES_SOURCE_ID = "route-miles";
export const ROUTE_MILE_DOT_LAYER_ID = "route-mile-dot";
export const ROUTE_MILE_BIG_LAYER_ID = "route-mile-big";
export const ROUTE_MILE_NUMBER_LAYER_ID = "route-mile-number";

/** One mile, one kilometre (m). */
export const MILE_M = METRES_PER_MILE;
export const KM_M = 1000;
/** Every this many, the larger dot with the number. */
export const MARKER_EVERY = 5;

/**
 * The zooms the markers show from. A mile is ~50 px apart at zoom 12 in this latitude, ~25 at 11: the small dots
 * from 11 (a kilometre, closer, from 12), the numbered ones from 9 (five miles ~65 px apart at 10, ~33 at 9;
 * five kilometres from 10).
 */
export function markerMinZooms(u: Units = units()): { dot: number; big: number } {
  return u === "metric" ? { dot: 12, big: 10 } : { dot: 11, big: 9 };
}

/** The colours: white dots on a near-black ring, the number in the ring's colour. */
export const MILE_MARK = { fill: "#ffffff", ring: "#1c1a1b", text: "#1c1a1b" };

type MileRoute = Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description">;

/** The point `m` metres along the line (`along` its vertices' metres). */
function pointAt(coordinates: readonly LonLat[], along: ArrayLike<number>, m: number): LonLat {
  let lo = 1;
  let hi = along.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (along[mid] < m) lo = mid + 1;
    else hi = mid;
  }
  const span = along[lo] - along[lo - 1];
  const t = span > 0 ? Math.min(Math.max((m - along[lo - 1]) / span, 0), 1) : 0;
  const [a, b] = [coordinates[lo - 1], coordinates[lo]];
  return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
}

/** The route's length in its own metres: the description's end, else the API's total, else the line's. */
function routeLength(route: MileRoute, lineM: number): number {
  const entries = route.description ?? [];
  const lastTo = entries.length ? Math.max(...entries.map((e) => (Number.isFinite(e.to_m) ? e.to_m : 0))) : 0;
  return lastTo > 0 ? lastTo : route.distance_m > 0 ? route.distance_m : lineM;
}

/**
 * The markers' features: a point at every whole mile (kilometre) short of the finish, with its number `n` and
 * `big` on every fifth. None where the route is null or has no line.
 */
export function routeMileFeatures(route: MileRoute | null | undefined, u: Units = units()) {
  const coordinates = route?.geometry.coordinates ?? [];
  const empty = { type: "FeatureCollection" as const, features: [] as ReturnType<typeof feature>[] };
  if (!route || coordinates.length < 2) return empty;
  const along = lineAlong(coordinates);
  const lineM = along[along.length - 1];
  if (!(lineM > 0)) return empty;
  const toLine = measureMap(route, along);
  const step = u === "metric" ? KM_M : MILE_M;
  const total = routeLength(route, lineM);
  const features: ReturnType<typeof feature>[] = [];
  // A marker right on the finish says nothing the finish flag does not.
  for (let n = 1; n * step < total - 1; n += 1) {
    features.push(feature(pointAt(coordinates, along, Math.min(toLine(n * step), lineM)), n));
  }
  return { type: "FeatureCollection" as const, features };
}

function feature(at: LonLat, n: number) {
  return {
    type: "Feature" as const,
    properties: { n, big: n % MARKER_EVERY === 0 },
    geometry: { type: "Point" as const, coordinates: at },
  };
}

/** The dots' sizes (px): larger in a ride and with the accessibility switch. */
export function markerSizes(ride = false, strong = accessibilityOn()) {
  return {
    dot: strong ? 4 : 3.5,
    ring: strong ? 2 : 1.5,
    big: (ride ? 12 : 10) + (strong ? 1 : 0),
    text: (ride ? 15 : 12) + (strong ? 1 : 0),
  };
}

/** The three layers, bottom to top: small dots, the larger dots, their numbers. */
export function routeMileLayers(sourceId: string = ROUTE_MILES_SOURCE_ID, ride = false, strong = accessibilityOn(), u: Units = units()) {
  const zoom = markerMinZooms(u);
  const size = markerSizes(ride, strong);
  return [
    {
      id: ROUTE_MILE_DOT_LAYER_ID,
      type: "circle" as const,
      source: sourceId,
      minzoom: zoom.dot,
      filter: ["!", ["get", "big"]],
      paint: {
        "circle-radius": size.dot,
        "circle-color": MILE_MARK.fill,
        "circle-stroke-color": MILE_MARK.ring,
        "circle-stroke-width": size.ring,
      },
    },
    {
      id: ROUTE_MILE_BIG_LAYER_ID,
      type: "circle" as const,
      source: sourceId,
      minzoom: zoom.big,
      filter: ["get", "big"],
      paint: {
        "circle-radius": size.big,
        "circle-color": MILE_MARK.fill,
        "circle-stroke-color": MILE_MARK.ring,
        "circle-stroke-width": size.ring,
      },
    },
    {
      id: ROUTE_MILE_NUMBER_LAYER_ID,
      type: "symbol" as const,
      source: sourceId,
      minzoom: zoom.big,
      filter: ["get", "big"],
      layout: {
        "text-field": ["to-string", ["get", "n"]],
        "text-font": [MAP_LABEL_FONT],
        "text-size": size.text,
        // The number always goes with its dot, and the names round it keep clear of it.
        "text-allow-overlap": true,
        "text-ignore-placement": false,
      },
      paint: { "text-color": MILE_MARK.text },
    },
  ];
}

/** Re-sizes the markers for a ride or the accessibility switch, on a map that has them. */
export function applyMileSizes(
  map: { getLayer(id: string): unknown; setPaintProperty(id: string, name: string, value: unknown): void; setLayoutProperty(id: string, name: string, value: unknown): void },
  ride: boolean,
  strong = accessibilityOn(),
): void {
  const size = markerSizes(ride, strong);
  if (map.getLayer(ROUTE_MILE_DOT_LAYER_ID)) {
    map.setPaintProperty(ROUTE_MILE_DOT_LAYER_ID, "circle-radius", size.dot);
    map.setPaintProperty(ROUTE_MILE_DOT_LAYER_ID, "circle-stroke-width", size.ring);
  }
  if (map.getLayer(ROUTE_MILE_BIG_LAYER_ID)) {
    map.setPaintProperty(ROUTE_MILE_BIG_LAYER_ID, "circle-radius", size.big);
    map.setPaintProperty(ROUTE_MILE_BIG_LAYER_ID, "circle-stroke-width", size.ring);
  }
  if (map.getLayer(ROUTE_MILE_NUMBER_LAYER_ID)) map.setLayoutProperty(ROUTE_MILE_NUMBER_LAYER_ID, "text-size", size.text);
}
