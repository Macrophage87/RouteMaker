/**
 * The routes to choose from at the top of the traffic slider (OWNER-DECISIONS 265):
 * the planner's answer and up to three others, each a whole route body of its own.
 * Nothing scores scenery; the rider judges it from the map, so each is shown with
 * the figures that are not a matter of taste.
 */
import type { RouteResponse } from "./api.ts";
import { formatClimb, formatDistance } from "./format.ts";

/** The answer and its candidates, in rank order (the answer first). */
export function routesOf(answer: RouteResponse | null): RouteResponse[] {
  if (!answer) return [];
  return [answer, ...(answer.candidates ?? [])];
}

/** The route chosen: the answer for index 0 or one out of range. */
export function candidateRoute(answer: RouteResponse | null, index: number): RouteResponse | null {
  if (!answer) return null;
  return routesOf(answer)[index] ?? answer;
}

export interface CandidateStats {
  /** 1 for the answer, then 2, 3, 4. */
  rank: number;
  distanceM: number;
  /** LTS 4 and Avoid. */
  lts4M: number;
  lts3M: number;
  trailM: number;
  red: number;
  orange: number;
  climbM: number;
  effortM: number | null;
}

export function statsOf(route: RouteResponse, rank: number): CandidateStats {
  const stress = route.stress_m ?? {};
  const facility = route.facility_m ?? {};
  const junctions = route.intersections ?? [];
  return {
    rank,
    distanceM: route.distance_m,
    lts4M: (stress["4"] ?? 0) + (stress["5"] ?? 0),
    lts3M: stress["3"] ?? 0,
    trailM: (facility.path ?? 0) + (facility.protected ?? 0),
    red: junctions.filter((j) => j.severity === "red").length,
    orange: junctions.filter((j) => j.severity === "orange").length,
    climbM: route.climb_m,
    effortM: route.effort_m ?? null,
  };
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** One candidate's figures in a sentence, miles first: what its label says. */
export function statsLine(stats: CandidateStats): string {
  const parts = [
    formatDistance(stats.distanceM),
    `${formatDistance(stats.lts4M)} of heavy-traffic roads (LTS 4)`,
    `${formatDistance(stats.lts3M)} of busy roads (LTS 3)`,
    count(stats.red, "very high stress junction", "very high stress junctions"),
    count(stats.orange, "higher stress junction", "higher stress junctions"),
    `${formatDistance(stats.trailM)} on trails and protected lanes`,
    `climb ${formatClimb(stats.climbM)}`,
  ];
  if (stats.effortM !== null) parts.push(`effort equal to ${formatDistance(stats.effortM)} on the flat`);
  return parts.join(", ");
}

/** What a rank is called: the answer is the calmest by the planner's order. */
export function rankName(rank: number): string {
  return rank === 1 ? "Route 1, the calmest" : `Route ${rank}`;
}

/** The rows of the picker, or null where there is only one route (the picker is not shown). */
export function candidateRows(answer: RouteResponse | null): { name: string; line: string }[] | null {
  const routes = routesOf(answer);
  if (routes.length < 2) return null;
  return routes.map((route, i) => ({ name: rankName(i + 1), line: statsLine(statsOf(route, i + 1)) }));
}

/** What a screen reader hears when the rider chooses one, or on arrival with several. */
export function choiceSaid(answer: RouteResponse | null, index: number): string | null {
  const routes = routesOf(answer);
  if (routes.length < 2) return null;
  const at = Math.min(Math.max(index, 0), routes.length - 1);
  return `Route ${at + 1} of ${routes.length}.`;
}
