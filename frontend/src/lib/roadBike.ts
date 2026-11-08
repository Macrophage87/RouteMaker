/**
 * Road Bike's own maps (the paved-only graph, `Variant.PAVED`, and its weekend twin,
 * `Variant.PAVED_WEEKEND`): where a router is not running or its map not yet built, the API plans the
 * ride on the map it falls back to (core/routing.py, `twin_fallback`). A weekend ride falls back from
 * the weekend map to the paved-only one, where the car-free parkways are roads with cars again; the
 * paved-only map falls back to the standard map, where gravel is packed gravel and winding trails are
 * not held off. The answer's `variant` says which map answered; this says it to the rider (the
 * v0.18.0 release review; the owner, 2026-11-08, "New weekend graph"). A ride with "Keep to roads,
 * not trails" on rides the roads-only map by choice and is not told.
 */
import type { RouteResponse } from "./api.ts";

export const ROAD_BIKE_NO_PAVED_MAP =
  "Road Bike's paved-only map isn't available, so this route may use packed gravel and winding trails.";

/** Plan shows note lines on one line; this is the one that fits, the whole line is behind it. */
export const ROAD_BIKE_NO_PAVED_MAP_SHORT = "Road Bike map unavailable: may use gravel.";

export const ROAD_BIKE_NO_WEEKEND_MAP =
  "Road Bike's weekend map isn't available, so this route treats car-free parkways such as Beach Drive as roads with cars.";

export const ROAD_BIKE_NO_WEEKEND_MAP_SHORT = "Weekend map unavailable: parkways as roads.";

type Routed = Pick<RouteResponse, "preset" | "variant"> & { dials?: Pick<NonNullable<RouteResponse["dials"]>, "when"> };

/** The warning for a Road Bike route a fallback map answered, with its one-line form, or null. */
export function roadBikeNotice(route: Routed | null | undefined): { text: string; short: string } | null {
  if (!route || route.preset !== "road-bike") return null;
  if (route.variant === "standard") return { text: ROAD_BIKE_NO_PAVED_MAP, short: ROAD_BIKE_NO_PAVED_MAP_SHORT };
  if (route.variant === "paved" && route.dials?.when === "weekend") {
    return { text: ROAD_BIKE_NO_WEEKEND_MAP, short: ROAD_BIKE_NO_WEEKEND_MAP_SHORT };
  }
  return null;
}

/** The warning for a Road Bike route a fallback map answered, or null. */
export function roadBikeNote(route: Routed | null | undefined): string | null {
  return roadBikeNotice(route)?.text ?? null;
}
