/**
 * Road Bike's own map (the paved-only graph, `Variant.PAVED`): where its router is not running or
 * its map not yet built, the API plans the ride on the standard map, where gravel is packed gravel
 * and winding trails are not held off (core/routing.py, the twin fallback). The answer's `variant`
 * says which map answered; this says it to the rider (the v0.18.0 release review). A ride with
 * "Keep to roads, not trails" on rides the roads-only map by choice and is not told.
 */
import type { RouteResponse } from "./api.ts";

export const ROAD_BIKE_NO_PAVED_MAP =
  "Road Bike's paved-only map isn't available right now, so this route may use packed gravel and winding trails. Try again later.";

/** The warning for a Road Bike route the standard map answered, or null. */
export function roadBikeNote(route: Pick<RouteResponse, "preset" | "variant"> | null | undefined): string | null {
  if (!route || route.preset !== "road-bike") return null;
  return route.variant === "standard" ? ROAD_BIKE_NO_PAVED_MAP : null;
}
