/** Sentences the route panel says about a route. */
import type { RouteResponse } from "./api.ts";
import { detour, pathLengthM, type LonLat } from "./geo.ts";
import { formatClimb, formatDistance, formatDuration, formatExtra, formatSpeed } from "./format.ts";

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
 * The notice for a route far longer than it needs to be, or null.
 *
 * Against the most direct legal route (the API's `detour`, OWNER-DECISIONS 164:
 * "just warn people"): silent within the larger of 1.25 times or 0.33 mi, a note
 * up to 1.5 times ("+1.2 mi to avoid 0.8 mi of LTS 3-4"), a warning above, a
 * strong warning above 2 times; the tiers are src/routemaker/detour.py's. Where
 * the API could not get the direct route in time it compared with the straight
 * line, and the old notice (at least twice as long and 3 km more) is what is
 * said; an API older than this has no `detour` at all and gets the same.
 * Distances rather than a bare ratio, miles first.
 */
export interface DetourView {
  level: "note" | "warning" | "strong";
  text: string;
}

export function detourView(
  route: Pick<RouteResponse, "distance_m" | "preset" | "detour">,
  points: readonly LonLat[],
): DetourView | null {
  const { detour: found } = route;
  if (found === null) return null;
  if (found !== undefined && found.basis === "direct_route" && route.preset !== "mass-ride") {
    if (found.level === null) return null;
    const ratio = found.ratio ?? route.distance_m / Math.max(found.reference_m, 1);
    const head = `This calm route is ${ratio.toFixed(1)}× the direct distance (${formatExtra(found.extra_m)})`;
    const buys =
      found.avoided_m && found.avoided_m > 0 ? `, to avoid ${formatDistance(found.avoided_m)} of LTS 3-4 roads.` : ".";
    if (found.level === "note") return { level: "note", text: `${head}${buys}` };
    const tail =
      found.level === "strong"
        ? " That is more than twice as far. Move the Traffic slider down for a shorter route."
        : " That is longer than most everyday trips. Move the Traffic slider down for a shorter route.";
    return { level: found.level, text: `${head}${buys}${tail}` };
  }
  const text = straightLineNotice(route, points);
  return text === null ? null : { level: "warning", text };
}

function straightLineNotice(route: Pick<RouteResponse, "distance_m" | "preset">, points: readonly LonLat[]): string | null {
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

/** The notice's words alone (`detourView`'s text), or null. */
export function detourNotice(
  route: Pick<RouteResponse, "distance_m" | "preset" | "detour">,
  points: readonly LonLat[],
): string | null {
  return detourView(route, points)?.text ?? null;
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
