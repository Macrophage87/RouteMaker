/** Sentences the route panel says about a route. */
import type { RouteResponse } from "./api.ts";
import { STRESS_TODAYS_TOP } from "./dials.ts";
import { detour, pathLengthM, type LonLat } from "./geo.ts";
import {
  formatClimb,
  formatDistance,
  formatDuration,
  formatExtra,
  formatRoughDistance,
  formatSpeed,
} from "./format.ts";

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
 * up to 1.5 times ("+1.2 mi (1.9 km), to avoid 0.8 mi of busy roads"), a warning above, a
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
  route: Pick<RouteResponse, "distance_m" | "preset" | "detour" | "dials">,
  points: readonly LonLat[],
): DetourView | null {
  const { detour: found } = route;
  if (found === null) return null;
  if (found !== undefined && found.basis === "direct_route" && route.preset !== "mass-ride") {
    if (found.level === null) return null;
    const ratio = found.ratio ?? route.distance_m / Math.max(found.reference_m, 1);
    // "Calm" only where the rider asked for the calm detour (above the old top
    // of the slider); a route at Default that is long for other reasons is just
    // "this route".
    const calm = (route.dials?.stress ?? 0) > STRESS_TODAYS_TOP;
    const head = `This ${calm ? "calm " : ""}route is ${ratioText(ratio, found.level)}× the direct distance, ${formatExtra(found.extra_m)}`;
    const buys =
      found.avoided_m && found.avoided_m > 0
        ? `, to avoid ${formatDistance(found.avoided_m)} of busy roads (LTS 3-4).`
        : ".";
    if (found.level === "note") return { level: "note", text: `${head}${buys}` };
    const tail =
      found.level === "strong"
        ? " That is more than twice as far. Move the Traffic slider down for a shorter route."
        : " That is more than 1.5 times the direct route. Move the Traffic slider down for a shorter route.";
    return { level: found.level, text: `${head}${buys}${tail}` };
  }
  const text = straightLineNotice(route, points);
  return text === null ? null : { level: "warning", text };
}

/**
 * The ratio as the notice says it: to one decimal, or to two where one would
 * read as the very threshold the next sentence says it is beyond ("1.5× ...
 * more than 1.5 times", review r2).
 */
function ratioText(ratio: number, level: DetourView["level"]): string {
  const short = ratio.toFixed(1);
  const threshold = level === "strong" ? "2.0" : level === "warning" ? "1.5" : null;
  return short === threshold ? ratio.toFixed(2) : short;
}

/**
 * Plain words for a calmer-route search the rider asked for (Traffic above
 * the old top of the slider) that did not run, or stopped before it was done
 * (the API's `calm_search.limited`, core.refine), or null where there is
 * nothing to say: it ran to its end, or was not asked for.
 */
export function calmSearchNote(route: Pick<RouteResponse, "calm_search" | "dials" | "preset">): string | null {
  if (route.preset === "mass-ride" || (route.dials?.stress ?? 0) <= STRESS_TODAYS_TOP) return null;
  const limited = route.calm_search?.limited;
  const why = limited ? CALM_SEARCH_LIMITS[limited] : undefined;
  return why ?? null;
}

/**
 * The straight-line span past which the calm search does not run: the API's
 * `core.refine.REFINE_MAX_SPAN_M`, which tests/test_plan_constants.py holds
 * this to. Said as a round figure, as PLAN.md has it: "19 mi (30 km)".
 */
export const CALM_SEARCH_MAX_SPAN_M = 30_000;

const CALM_SEARCH_LIMITS: Record<string, string> = {
  time: "The calmer-route search ran out of time, so there may be a calmer route than this one.",
  untraceable: "The calmer-route search could not read this route, so it is the router's own.",
  span: `The calmer-route search does not run on trips over ${formatRoughDistance(CALM_SEARCH_MAX_SPAN_M)} in a straight line, so this is the router's own route.`,
  long_ride: "The calmer-route search does not run on long rides, so this is the router's own route.",
  seeking: "The calmer-route search does not run while the Hills slider looks for climbs.",
};

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
  route: Pick<RouteResponse, "distance_m" | "preset" | "detour" | "dials">,
  points: readonly LonLat[],
): string | null {
  return detourView(route, points)?.text ?? null;
}

/**
 * The detour notice as a screen reader hears it with the route: its tier in a
 * word and how much longer, in a sentence (a11y review of integrate-2, 4.1.3:
 * a rider moving the slider to the top was not told the route is 2.4 times the
 * direct distance). "times", not "×", which is read as "multiplication sign".
 * The notice itself, with its advice, is in the summary.
 */
export function detourSaid(
  route: Pick<RouteResponse, "distance_m" | "preset" | "detour" | "dials">,
  points: readonly LonLat[],
): string | null {
  const view = detourView(route, points);
  if (view === null) return null;
  const found = route.detour;
  if (found && found.basis === "direct_route" && route.preset !== "mass-ride" && found.level !== null) {
    const ratio = found.ratio ?? route.distance_m / Math.max(found.reference_m, 1);
    const tier = { note: "Note", warning: "Warning", strong: "Strong warning" }[found.level];
    return `${tier}: ${ratioText(ratio, found.level)} times the direct distance, ${formatDistance(found.extra_m)} longer.`;
  }
  // The straight-line notice: its first sentence says it.
  return `Warning: ${view.text.split(". ")[0].replace(/^This/, "this").replace(/\.$/, "")}.`;
}

/** "2 very high stress junctions", or null when there are none (or the API did not say). */
export function redJunctionsSaid(route: Pick<RouteResponse, "intersections">): string | null {
  const red = (route.intersections ?? []).filter((junction) => junction.severity === "red").length;
  if (red === 0) return null;
  return `${red} very high stress ${red === 1 ? "junction" : "junctions"}.`;
}

/**
 * What a screen reader hears when a route arrives: the figures, then the
 * detour's tier and the very high stress junctions when there are any, and
 * nothing more (the summary has the rest).
 */
export function announceRoute(route: RouteResponse, points: readonly LonLat[] = []): string {
  const figures =
    `Route planned: ${formatDistance(route.distance_m)}, ` +
    `${formatDuration(route.duration_s)} moving time, climb ${formatClimb(route.climb_m)}.`;
  return [figures, detourSaid(route, points), redJunctionsSaid(route)].filter(Boolean).join(" ");
}

/** A point's name in the list: Start, Stop 1, Stop 2, ..., End. */
export function pointName(index: number, count: number): string {
  if (index === 0) return "Start";
  if (index === count - 1 && count > 1) return "End";
  return `Stop ${index}`;
}
