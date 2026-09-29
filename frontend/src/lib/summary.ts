/** Sentences the route panel says about a route. */
import type { RouteResponse } from "./api.ts";
import { detour, pathLengthM, type LonLat } from "./geo.ts";
import { formatClimb, formatDistance, formatDuration, formatSpeed } from "./format.ts";

/**
 * The pace the moving time assumes, derived from the answer itself (distance
 * over duration), so it cannot drift from what the API planned with. Mass Ride
 * is planned at parade pace (src/core/presets.py: 6 mph).
 */
export function paceText(route: Pick<RouteResponse, "distance_m" | "duration_s" | "preset">): string | null {
  if (!(route.distance_m > 0) || !(route.duration_s > 0)) return null;
  const kmh = route.distance_m / 1000 / (route.duration_s / 3600);
  const text = `about ${formatSpeed(kmh)}`;
  return route.preset === "mass-ride" ? `parade pace, ${text}` : text;
}

/**
 * The notice for a route far longer than the straight lines between its
 * points, or null. Distances rather than a ratio ("122.5x" was false
 * precision). The Mass Ride cause is worded as the plan frames it and makes no
 * finding about any bridge: that preset keeps to roadways and skips trails and
 * sidepaths, and several river crossings here are open to bikes only on a
 * sidepath.
 */
export function detourNotice(route: Pick<RouteResponse, "distance_m" | "preset">, points: readonly LonLat[]): string | null {
  if (!detour(points, route.distance_m).flagged) return null;
  const head = `This route is ${formatDistance(route.distance_m)} for points ${formatDistance(pathLengthM(points))} apart in straight lines.`;
  if (route.preset === "mass-ride") {
    return (
      `${head} Mass Ride keeps to roadways and skips trails and sidepaths, and many river crossings ` +
      "here are open to bikes only on their sidepath, so it can go a long way round. " +
      "Moving a point, or another ride type, may give a shorter route."
    );
  }
  return `${head} There may be no direct connection nearby; moving a point may help.`;
}

/** What a screen reader hears when a route arrives. */
export function announceRoute(route: RouteResponse): string {
  return (
    `Route planned: ${formatDistance(route.distance_m)}, ` +
    `${formatDuration(route.duration_s)} moving time, climb ${formatClimb(route.climb_m)}.`
  );
}

/** A point's name in the list: Start, Via 1, Via 2, ..., End. */
export function pointName(index: number, count: number): string {
  if (index === 0) return "Start";
  if (index === count - 1 && count > 1) return "End";
  return `Via ${index}`;
}
