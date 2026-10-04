/** Sentences the route panel says about a route. */
import type { RouteResponse } from "./api.ts";
import { STRESS_TODAYS_TOP, TARGET_CEILING_RATIO } from "./dials.ts";
import { detour, pathLengthM, type LonLat } from "./geo.ts";
import { loopNote } from "./loop.ts";
import {
  formatClimb,
  formatDistance,
  formatDuration,
  formatExtra,
  formatRoughDistance,
  formatSpeed,
  SEEK_MAX_SPAN_M,
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
export function calmSearchNote(
  route: Pick<RouteResponse, "calm_search" | "dials" | "preset"> & Partial<Pick<RouteResponse, "distance_m">>,
): string | null {
  if (route.preset === "mass-ride" || (route.dials?.stress ?? 0) <= STRESS_TODAYS_TOP) return null;
  const search = route.calm_search;
  const target = search?.target_distance_m;
  const over = overTarget(route);
  const notes: string[] = [];
  if (search?.no_fit === true && target) {
    // No route within the target was found: the calmest one found is answered,
    // flagged (OWNER-DECISIONS 267, 298(2)), and it may be past the ceiling too.
    const ceiling = search.ceiling_m ?? null;
    const length = route.distance_m ?? (over !== null ? target + over : null);
    const pastCeiling = ceiling !== null && length !== null && length > ceiling;
    notes.push(
      pastCeiling
        ? `No route within your target distance of ${formatDistance(target)}, or within ${TARGET_CEILING_RATIO} times it, was found. This is the least stressful one found.`
        : `No route within your target distance of ${formatDistance(target)} was found. This is the least stressful one found.`,
    );
    if (over !== null) notes.push(`It is ${formatDistance(over)} over your target.`);
  } else if (search?.limited === "ceiling") {
    const ceiling = search.ceiling_m;
    notes.push(
      ceiling
        ? `The calmer-route search stopped at the longest distance it allows, ${formatDistance(ceiling)}, so a calmer, longer route may exist.`
        : "The calmer-route search stopped at the longest distance it allows, so a calmer, longer route may exist.",
    );
    if (over !== null) notes.push(`It is ${formatDistance(over)} over your target, to avoid busier roads.`);
  } else {
    const why = search?.limited ? CALM_SEARCH_LIMITS[search.limited] : undefined;
    if (why) notes.push(why);
    // Past the target where the extra miles avoid enough busy road (OWNER-DECISIONS 271);
    // an older API's "target_distance" without `no_fit` says only how far.
    if (over !== null) {
      notes.push(
        search?.limited === "target_distance"
          ? `It is ${formatDistance(over)} over your target.`
          : `It is ${formatDistance(over)} over your target, to avoid busier roads.`,
      );
    }
  }
  if (search?.fitted_at != null && search.fits !== false && target) {
    notes.push(
      `Your target distance of ${formatDistance(target)} is shorter than the calmest route, so this one uses some busier roads to fit.`,
    );
  }
  return notes.length ? notes.join(" ") : null;
}

/**
 * How far past the rider's target distance a route is (metres), or null where it is
 * within it or there is none (OWNER-DECISIONS 271): the answer's in `calm_search`, a
 * candidate's on the route itself.
 */
export function overTarget(route: Pick<RouteResponse, "calm_search" | "over_target_m">): number | null {
  const over = route.calm_search?.over_target_m ?? route.over_target_m ?? null;
  return over !== null && over > 0 ? over : null;
}

/**
 * What a screen reader hears when the route is past the rider's target distance, or
 * null: a sentence of its own, not a colour (OWNER-DECISIONS 271: always flagged).
 */
export function targetSaid(route: Pick<RouteResponse, "calm_search" | "distance_m">): string | null {
  const target = route.calm_search?.target_distance_m;
  const over = overTarget(route);
  if (!target || over === null) return null;
  return `${formatDistance(over)} over your target of ${formatDistance(target)}.`;
}

/**
 * The straight-line span past which the calm search does not run: the API's
 * `core.refine.REFINE_MAX_SPAN_M`, which tests/test_plan_constants.py holds
 * this to. Said as a round figure, as PLAN.md has it: "19 mi (30 km)".
 */
export const CALM_SEARCH_MAX_SPAN_M = 30_000;
// (Trailmaxxing at the top of the slider is not held to it: it plans a longer trip leg by leg, OWNER-DECISIONS 256.)

// "The usual route": the planner's first route for this ride type, before any
// calmer-route search (the a11y review's N2: "the router's own route" was an
// internal term). Hills seeking at the top no longer stops the search
// (OWNER-DECISIONS 298(3)), so there is no "seeking" here.
const CALM_SEARCH_LIMITS: Record<string, string> = {
  time: "The calmer-route search ran out of time, so there may be a calmer route than this one.",
  untraceable: "The calmer-route search could not read this route, so this is the usual route for this ride type.",
  span: `The calmer-route search does not run on trips over ${formatRoughDistance(CALM_SEARCH_MAX_SPAN_M)} in a straight line, so this is the usual route for this ride type.`,
  long_ride: "The calmer-route search does not run on long rides, so this is the usual route for this ride type.",
  split: "The calmer-route search could not cut this long trip into legs, so this is the usual route for this ride type.",
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
 * Which route of several is said (lib/candidates.ts announceHow): `chosen` when the
 * rider picked one of the routes to choose from, `others` on arrival with more than
 * one (how many more there are).
 */
export interface AnnounceHow {
  chosen?: { rank: number; of: number };
  others?: number;
}

/**
 * What a screen reader hears when a route arrives, or when the rider chooses one
 * of the routes to choose from (nothing was planned then, so it is not "Route
 * planned"; the a11y review's N4): the figures, then the detour's tier, the very
 * high stress junctions, the target and the loop when there are any, and on
 * arrival how many other routes there are to choose from (the summary has the rest).
 */
export function announceRoute(route: RouteResponse, points: readonly LonLat[] = [], how: AnnounceHow = {}): string {
  const head = how.chosen ? `Route ${how.chosen.rank} of ${how.chosen.of} chosen: ` : "Route planned: ";
  const figures =
    `${head}${formatDistance(route.distance_m)}, ` +
    `${formatDuration(route.duration_s)} moving time, climb ${formatClimb(route.climb_m)}.`;
  const others = !how.chosen && how.others ? othersSaid(how.others) : null;
  return [figures, detourSaid(route, points), redJunctionsSaid(route), targetSaid(route), loopNote(route), others]
    .filter(Boolean)
    .join(" ");
}

/** "2 other routes to choose from, under Routes to choose from." */
export function othersSaid(others: number): string {
  return `${others} other ${others === 1 ? "route" : "routes"} to choose from, under Routes to choose from.`;
}

/**
 * What the route summary says of the Hills slider's search for climbs, or null where
 * it did not look. "calm_first": at the top of the traffic slider the stress order
 * and the target still decide, and climbing only breaks ties (OWNER-DECISIONS 298(3)).
 */
export function seekNote(seek: RouteResponse["hills_seek"]): string | null {
  if (!seek) return null;
  switch (seek.limited) {
    case "calm_first":
      return "At this Traffic setting, looking for climbs only chooses between equally calm routes, preferring the one that climbs more.";
    case "two_points":
      return "Looking for climbs works on routes with just a start and an end; this one has stops, so it is the fastest route.";
    case "long_ride":
      return `Looking for climbs is done only when the start and end are within ${formatRoughDistance(SEEK_MAX_SPAN_M)} of each other; this is the fastest route.`;
    case "timed_out":
      return "Looking for climbs took too long this time; this is the fastest route.";
  }
  if (seek.chosen === 0) {
    return `None of the ${seek.candidates - 1} alternatives climbed more within the distance allowed; this is the fastest route.`;
  }
  return `Chose a route with ${formatClimb(seek.extra_climb_m)} more climbing for ${formatDistance(seek.extra_distance_m)} more distance, from ${seek.candidates} routes compared.`;
}

/** How long a plan runs before "Still planning" is said, once (the a11y review's SF1). */
export const STILL_PLANNING_AFTER_MS = 3000;

/**
 * What the status line says once a plan has run STILL_PLANNING_AFTER_MS: that it is
 * still going, and at the calm end of the traffic slider (where a plan takes up to
 * half a minute, LONG-CALM) why.
 */
export function stillPlanningSaid(preset: string, dials: { stress: number } | undefined): string {
  const calm = preset !== "mass-ride" && (dials?.stress ?? 0) > STRESS_TODAYS_TOP;
  return calm ? "Still planning. Calm routes at this setting can take up to half a minute." : "Still planning.";
}

/**
 * A point's name in the list: Start, Stop 1, Stop 2, ..., End. In a loop
 * (OWNER-DECISIONS 374) the ride finishes at the start, so the first point is
 * "Start and finish" and every other point is a stop, never the end.
 */
export function pointName(index: number, count: number, loop = false): string {
  if (index === 0) return loop ? LOOP_START_NAME : "Start";
  if (!loop && index === count - 1 && count > 1) return "End";
  return `Stop ${index}`;
}

/** The first point of a loop, where the ride starts and finishes. */
export const LOOP_START_NAME = "Start and finish";
