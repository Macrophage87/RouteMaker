/**
 * THE ROUTE'S OWN STREET NAMES. The owner, 2026-10-25: "Put the name of the road or path on the route itself". Each
 * named stretch of the route description (the API's `description`, kind "stretch") is cut out of the route's line and
 * named along it, in the street names' face, size and halo (stressStyle.js, ROAD_LABEL), a path's in the trail names'
 * purple (TRAIL_LABEL), so the road each part of the route uses can be read off the line in Plan, Go and a ride.
 *
 * The layer sits over the route (MapView), so the base map's name for another street gives way to the route's own; in
 * a ride it goes up with the street names (lib/rideLabelOrder.ts), on top of them, at the ride's 20 px and shortened
 * as they are ("R St NW"). An unnamed way ("unnamed path", "this part of the route") is not named. Not drawn while the
 * route is greyed for a new plan. The names are on the canvas, out of a screen reader's reach; the route description
 * says every one in words.
 */
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { isUnnamed, lineAlong, measureMap } from "./navigate.ts";
import { ROAD_LABEL, TRAIL_LABEL, accessibilityOn, rideRoadLabelField } from "../stressStyle.js";

export const ROUTE_NAME_SOURCE_ID = "route-names";
export const ROUTE_NAME_LAYER_ID = "route-name";

/**
 * A name repeats along its stretch no closer than this (px): far enough apart that a long road is not a string of
 * the same words, near enough that one shows on screen most of the way along it.
 */
export const ROUTE_NAME_SPACING = 320;
/** A stretch shorter than this (m) is left unnamed: too short to hold its name at any zoom the route is ridden at. */
export const ROUTE_NAME_MIN_M = 40;
/** Two stretches of one name that meet (within this, m, of rounding) are named as one. */
const JOIN_GAP_M = 1;
/**
 * The names show from this zoom: zoomed further out a long route's names would cover the town and neighbourhood
 * names along it (the base map names its minor streets from 15 and the major trails from 10).
 */
export const ROUTE_NAME_MIN_ZOOM = 12;

type NameRoute = Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description">;

/** The route's named stretches in the line's own metres: [fromM, toM), the name, and whether it is a path. */
export function namedStretches(route: NameRoute | null | undefined): { fromM: number; toM: number; name: string; path: boolean }[] {
  const entries = route?.description ?? [];
  const coordinates = route?.geometry.coordinates ?? [];
  if (entries.length === 0 || coordinates.length < 2) return [];
  const along = lineAlong(coordinates);
  const toLine = measureMap(route as NameRoute, along);
  const out: { fromM: number; toM: number; name: string; path: boolean }[] = [];
  for (const entry of entries) {
    if (entry.kind !== "stretch" || isUnnamed(entry.street)) continue;
    const name = (entry.street as string).trim();
    const fromM = toLine(entry.from_m);
    const toM = toLine(entry.to_m);
    if (!(toM > fromM)) continue;
    const last = out[out.length - 1];
    // A street that is a path for part of its way keeps the two parts apart, each in its own colour.
    if (last && last.name === name && last.path === (entry.facility === "path") && fromM - last.toM <= JOIN_GAP_M) {
      last.toM = toM;
      continue;
    }
    out.push({ fromM, toM, name, path: entry.facility === "path" });
  }
  return out.filter((s) => s.toM - s.fromM >= ROUTE_NAME_MIN_M);
}

/** The line between `fromM` and `toM` along it (metres from its start, `along` its vertices' metres). */
export function sliceLine(coordinates: readonly LonLat[], along: ArrayLike<number>, fromM: number, toM: number): LonLat[] {
  const at = (m: number): LonLat => {
    let i = 1;
    while (i < along.length - 1 && along[i] < m) i += 1;
    const span = along[i] - along[i - 1];
    const t = span > 0 ? Math.min(Math.max((m - along[i - 1]) / span, 0), 1) : 0;
    const [a, b] = [coordinates[i - 1], coordinates[i]];
    return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
  };
  const out: LonLat[] = [at(fromM)];
  for (let i = 0; i < along.length; i += 1) if (along[i] > fromM && along[i] < toM) out.push(coordinates[i]);
  out.push(at(toM));
  return out;
}

/** The names' features: one line per named stretch, with its `name` and `path` (none where the route is null). */
export function routeNameFeatures(route: NameRoute | null | undefined) {
  const stretches = namedStretches(route);
  const coordinates = route?.geometry.coordinates ?? [];
  const along = stretches.length > 0 ? lineAlong(coordinates) : new Float64Array(0);
  return {
    type: "FeatureCollection" as const,
    features: stretches.map((s) => ({
      type: "Feature" as const,
      properties: { name: s.name, path: s.path },
      geometry: { type: "LineString" as const, coordinates: sliceLine(coordinates, along, s.fromM, s.toM) },
    })),
  };
}

/** The names' text: as written in Plan and Go, shortened in a ride as the street names are ("R St NW"). */
export function routeNameField(ride: boolean): unknown {
  return ride ? rideRoadLabelField(null, ["get", "name"]) : ["get", "name"];
}

/** The names' paint: the street names' grey, a path's in the trail names' purple; darker with the accessibility switch. */
export function routeNamePaint(strong = accessibilityOn()) {
  return {
    "text-color": ["case", ["get", "path"], strong ? TRAIL_LABEL.strongColor : TRAIL_LABEL.color, strong ? ROAD_LABEL.strongColor : ROAD_LABEL.color],
    "text-halo-color": ROAD_LABEL.halo,
    "text-halo-width": strong ? ROAD_LABEL.strongHaloWidth : ROAD_LABEL.haloWidth,
    "text-halo-blur": ROAD_LABEL.haloBlur,
  };
}

/** The names' layer, along the route's line. */
export function routeNameLayer(sourceId: string = ROUTE_NAME_SOURCE_ID, ride = false, strong = accessibilityOn()) {
  return {
    id: ROUTE_NAME_LAYER_ID,
    type: "symbol" as const,
    source: sourceId,
    minzoom: ROUTE_NAME_MIN_ZOOM,
    layout: {
      "symbol-placement": "line" as const,
      "symbol-spacing": ROUTE_NAME_SPACING,
      "text-field": routeNameField(ride),
      "text-font": [ROAD_LABEL.font],
      "text-size": ride ? ROAD_LABEL.rideSize : ROAD_LABEL.size,
      "text-max-angle": TRAIL_LABEL.maxAngle,
      "text-padding": TRAIL_LABEL.padding,
    },
    paint: routeNamePaint(strong),
  };
}
