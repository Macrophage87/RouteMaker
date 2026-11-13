/**
 * Plan's "Keep to compare" (the backlog's "choose between routes in Plan" item, 2026-11-13; areas/05-plan-experience.md
 * item 2): the rider keeps the route shown, changes the plan, routes again, and reads the two side by side in one small
 * table, with one press to go back to the kept one. Today the dashed line of the route before an update (planFirst.ts)
 * lasts only until the next change, so two candidates could be held only in the rider's head or in two tabs.
 *
 * Only figures that are not a matter of taste (as the routes to choose from, candidates.ts): time, distance, climb,
 * busy roads, stressful junctions, turns, waiting, unpaved and paths. A row where both routes read zero is left out, so
 * the table stays short (Stephen's inverted pyramid: no walls of text). The better side of a row is marked; which is
 * better is plain for each (less is better, except paths).
 */
import type { RouteResponse } from "./api.ts";
import { statsOf, type CandidateStats } from "./candidates.ts";
import { formatClimb, formatDistance, formatDuration } from "./format.ts";
import { t } from "./i18n.ts";

export const KEEP_LABEL = t("Keep to compare");
export const USE_KEPT_LABEL = t("Use kept route");
export const STOP_COMPARING_LABEL = t("Stop comparing");
export const KEPT_HEADING = t("Kept");
export const NOW_HEADING = t("Now");
export const COMPARE_CAPTION = t("Kept route and the route now");
/** Said when the rider keeps the route, and shown as the hint until the next route. */
export const KEPT_SAID = t("Route kept. Change the plan and route again to compare. The kept route stays on the map, dashed.");
export const USED_KEPT_SAID = t("Back to the kept route. The route you had is kept to compare instead.");
export const STOPPED_SAID = t("Stopped comparing.");
/** The route shown is the kept one (just kept, or back to it): nothing to compare yet. */
export const SAME_AS_KEPT = t("This is the kept route. Change the plan and route again to compare.");

/** The plan changed with a route kept: the kept one is dashed on the map until the plan is routed. */
export const EDITED_KEPT_HINT = t("The kept route is dashed on the map. Update the route to compare.");

/** Below this a length reads as 0.0 mi, and below this a wait is not worth a row (as candidates.ts). */
const SAID_M = 80;
const SAID_S = 30;

export interface CompareRow {
  label: string;
  kept: string;
  now: string;
  /** The side that reads better, or null where they read the same or neither is better. */
  better: "kept" | "now" | null;
}

type Figure = {
  label: string;
  value: (s: CandidateStats, r: RouteResponse) => number | null;
  show: (n: number) => string;
  /** The least worth a row and worth calling better: under it both read the same. */
  step: number;
  /** More is better (paths); otherwise less is. */
  more?: boolean;
};

const busyM = (s: CandidateStats) => s.lts3M + s.lts4M;

const FIGURES: readonly Figure[] = [
  { label: t("Time"), value: (_s, r) => r.duration_s, show: (n) => formatDuration(n), step: 60 },
  { label: t("Distance"), value: (s) => s.distanceM, show: (n) => formatDistance(n), step: SAID_M },
  { label: t("Climb"), value: (s) => s.climbM, show: (n) => formatClimb(n), step: 3 },
  { label: t("Busy roads"), value: busyM, show: (n) => formatDistance(n), step: SAID_M },
  { label: t("Heavy traffic"), value: (s) => s.lts4M, show: (n) => formatDistance(n), step: SAID_M },
  { label: t("Stressful junctions"), value: (s) => s.red + s.orange, show: (n) => String(n), step: 1 },
  { label: t("Turns"), value: (s) => s.turns, show: (n) => String(n), step: 1 },
  { label: t("Waiting at lights"), value: (s) => s.waitS, show: (n) => formatDuration(n), step: SAID_S },
  { label: t("Unpaved"), value: (s) => s.unpavedM, show: (n) => formatDistance(n), step: SAID_M },
  { label: t("Paths and protected lanes"), value: (s) => s.trailM, show: (n) => formatDistance(n), step: SAID_M, more: true },
];

/**
 * The table's rows, kept route first. A figure either route lacks (an older API's) or that both read as nothing is
 * left out; Time and Distance always stay.
 */
export function compareRows(kept: RouteResponse, now: RouteResponse): CompareRow[] {
  const a = statsOf(kept, 1);
  const b = statsOf(now, 2);
  const rows: CompareRow[] = [];
  FIGURES.forEach((figure, i) => {
    const x = figure.value(a, kept);
    const y = figure.value(b, now);
    if (x === null || y === null) return;
    if (i > 1 && x < figure.step && y < figure.step) return;
    const diff = figure.more ? x - y : y - x;
    const better = Math.abs(x - y) < figure.step ? null : diff > 0 ? "kept" : "now";
    rows.push({ label: figure.label, kept: figure.show(x), now: figure.show(y), better });
  });
  return rows;
}

/** Whether two routes are the same one (a route put back through the planner is a new object). */
export function sameRoute(a: RouteResponse, b: RouteResponse): boolean {
  return (
    a.distance_m === b.distance_m &&
    a.duration_s === b.duration_s &&
    a.geometry.coordinates.length === b.geometry.coordinates.length
  );
}

/** The better side's cell says so out of sight. */
export const BETTER_SAID = t("better");
