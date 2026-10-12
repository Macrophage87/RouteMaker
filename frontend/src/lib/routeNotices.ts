/**
 * The route's warning line (UI-CLEANUP, the owner's choice 5 of 2026-10-11: "Notices are one line each
 * with an icon"): the facility notices (FacilityBreakdown's "notices" part: a traffic-tolerant ride, the
 * metres on roads best avoided, what the hills search found) are counted on the warning line ("+1 more")
 * and listed behind it, as the approved mockup's control table has it. Pure, so the count is tested
 * against the same three conditions FacilityBreakdown shows them on.
 */
import type { RouteResponse } from "./api.ts";
import { avoidMetres } from "./facilityBar.ts";
import { routeWarning } from "./dialsPanel.ts";
import { seekNote, tolerateNote } from "./summary.ts";

/** How many facility notices the route has: the ones FacilityBreakdown part="notices" shows. */
export function facilityNoticeCount(route: Pick<RouteResponse, "preset" | "dials" | "stress_m" | "hills_seek" | "hills_tolerate">): number {
  let count = 0;
  if (routeWarning(route.preset, route.dials)) count += 1;
  if (avoidMetres(route.stress_m) > 0) count += 1;
  if (seekNote(route.hills_seek) ?? tolerateNote(route.hills_tolerate)) count += 1;
  return count;
}

/** The button that shows them: "1 more warning" beside an Avoid notice, else "2 warnings". */
export function warningsLabel(count: number, afterAvoid: boolean): string {
  const noun = count === 1 ? "warning" : "warnings";
  return afterAvoid ? `${count} more ${noun}` : `${count} ${noun}`;
}
