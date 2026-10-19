/**
 * The routes to choose from at the top of the traffic slider (OWNER-DECISIONS 265):
 * the planner's answer and up to three others, each a whole route body of its own.
 * Nothing scores scenery; the rider judges it from the map, so each is shown with
 * the figures that are not a matter of taste.
 */
import type { RouteResponse } from "./api.ts";
import { formatClimb, formatDistance } from "./format.ts";
import { NEIGHBOUR_NAME } from "./neighbours.ts";
import { overTarget, type AnnounceHow } from "./summary.ts";

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
  /** How far past the rider's target distance it is, or null (within it, or none set). */
  overTargetM: number | null;
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
    overTargetM: overTarget(route),
  };
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Below this (metres) a length reads as 0.0 mi, and is left out of the line. */
const SAID_AS_ZERO_M = 80;

/**
 * One candidate's figures in a sentence, miles first: the radio's description
 * (its name has the distance). A figure that is zero is left out (the a11y
 * review's SF2: "0 higher stress junctions" is read on every arrow press).
 * "Heavy-traffic or best-avoided roads" is LTS 4 and Avoid together.
 */
export function statsLine(stats: CandidateStats): string {
  const parts: string[] = [];
  if (stats.overTargetM !== null) parts.push(`${formatDistance(stats.overTargetM)} over your target`);
  if (stats.lts4M >= SAID_AS_ZERO_M) parts.push(`${formatDistance(stats.lts4M)} of heavy-traffic or best-avoided roads`);
  if (stats.lts3M >= SAID_AS_ZERO_M) parts.push(`${formatDistance(stats.lts3M)} of busy roads`);
  if (stats.red > 0) parts.push(count(stats.red, "very high stress junction", "very high stress junctions"));
  if (stats.orange > 0) parts.push(count(stats.orange, "higher stress junction", "higher stress junctions"));
  if (stats.trailM >= SAID_AS_ZERO_M) parts.push(`${formatDistance(stats.trailM)} on trails and protected lanes`);
  if (stats.climbM > 0) parts.push(`climb ${formatClimb(stats.climbM)}`);
  if (stats.effortM !== null) parts.push(`effort equal to ${formatDistance(stats.effortM)} on the flat`);
  return parts.join(", ");
}

/**
 * Whether `first` is the calmest of `all` by the figures the line says: no other
 * has less heavy-traffic road, fewer very high stress junctions, less busy road or
 * fewer higher stress junctions. The answer is first by the planner's whole order,
 * which also weighs distance, so it is not always the calmest (the spec review's NIT1).
 */
export function calmestOf(first: CandidateStats, all: readonly CandidateStats[]): boolean {
  return all.every(
    (other) =>
      other.lts4M >= first.lts4M && other.red >= first.red && other.lts3M >= first.lts3M && other.orange >= first.orange,
  );
}

/** What a rank is called, always ending in a separator: "Route 2:", or "Route 1, the calmest:" where it is. */
export function rankName(rank: number, calmest = false): string {
  return rank === 1 && calmest ? "Route 1, the calmest:" : `Route ${rank}:`;
}

/** "0.4 mi (0.6 km) more than Route 1", "... less than Route 1", or "the same distance as Route 1". */
export function distanceAgainstFirst(distanceM: number, firstM: number): string {
  const diff = distanceM - firstM;
  if (Math.abs(diff) < SAID_AS_ZERO_M) return "the same distance as Route 1";
  return `${formatDistance(Math.abs(diff))} ${diff > 0 ? "more" : "less"} than Route 1`;
}

export interface CandidateRow {
  /** The radio's name: rank, distance, and for the others the difference from Route 1. */
  name: string;
  /** Its description: the full figures. */
  line: string;
}

/** The rows of the picker, or null where there is only one route (the picker is not shown). */
export function candidateRows(answer: RouteResponse | null): CandidateRow[] | null {
  const routes = routesOf(answer);
  if (routes.length < 2) return null;
  const stats = routes.map((route, i) => statsOf(route, i + 1));
  // Go's More direct and Calmer (lib/neighbours.ts) are named for what they are, with their tradeoff as the line, and
  // are not weighed for "the calmest" (they are another setting's routes). With only them, Route 1 is the rider's own.
  const own = stats.filter((_s, i) => !routes[i].neighbour);
  const calmest = calmestOf(stats[0], own);
  const yours = own.length === 1;
  return stats.map((s, i) => {
    const neighbour = routes[i].neighbour;
    if (neighbour) return { name: NEIGHBOUR_NAME[neighbour.kind], line: neighbour.line };
    const distance = formatDistance(s.distanceM);
    const name =
      i === 0
        ? `${yours ? YOUR_SETTING : rankName(1, calmest)} ${distance}`
        : `${rankName(s.rank)} ${distance}, ${distanceAgainstFirst(s.distanceM, stats[0].distanceM)}`;
    return { name, line: statsLine(s) };
  });
}

/** The rider's own route's name where the others are only More direct and Calmer. */
export const YOUR_SETTING = "Your setting:";

/** The hint the group is described by, read once on entering it: the target only where one is set. */
export function candidatesHint(answer: RouteResponse | null): string {
  const target = answer?.calm_search?.target_distance_m;
  const routes = routesOf(answer);
  // Left out only where every other route is More direct or Calmer.
  const calm = !(routes.length > 1 && routes.slice(1).every((r) => r.neighbour));
  const first = !calm
    ? ""
    : target
      ? "Each is about as calm as the first, and no further over your target distance. "
      : "Each is about as calm as the first. ";
  const notch = routes.some((r) => r.neighbour) ? `${NEIGHBOURS_HINT} ` : "";
  return `${first}${notch}The map shows the one chosen, and the route description below follows it.`;
}

/** What More direct and Calmer are, in the group's hint (read once, on entering the group). */
export const NEIGHBOURS_HINT =
  "More direct is planned more traffic tolerant than your traffic setting, and Trailmaxxed at the calmest setting. Choosing one rides it and keeps your setting.";

/**
 * How the route is announced (summary.ts announceRoute): chosen by the rider ("Route 2
 * of 3 chosen: ..."), or on arrival with how many others there are to choose from.
 */
export function announceHow(answer: RouteResponse | null, index: number, chosen: boolean): AnnounceHow {
  const routes = routesOf(answer);
  if (routes.length < 2) return {};
  const at = Math.min(Math.max(index, 0), routes.length - 1);
  if (!chosen) return { others: routes.length - 1 };
  const neighbour = routes[at].neighbour;
  return { chosen: { rank: at + 1, of: routes.length, ...(neighbour ? { name: NEIGHBOUR_NAME[neighbour.kind] } : {}) } };
}
