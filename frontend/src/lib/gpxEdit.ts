/**
 * What opening a GPX file does to the plan besides its points: the ride type
 * it names, the sliders that go with it, and the point names it carries.
 *
 * The ride type is chosen the way the ride-type dialog chooses one
 * (rideTypeDialog.ts, `choose`): its sliders move to where it starts them,
 * and the ride time the rider picked stays. A RouteMaker export also carries
 * the sliders it was planned with (gpx.ts, rte/cmt); those are taken as a
 * link's are (dials.ts, `fitDials`). A file that names a ride type the planner
 * no longer offers opens as Default (gpxPlan.ts, with a note the panel shows).
 * A file from elsewhere names none, and the ride type stays as it is.
 */
import type { RouteResponse } from "./api.ts";
import { fitDials, type Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import type { ImportedPlan } from "./gpxPlan.ts";
import { LOOP_START_NAME } from "./loop.ts";
import type { PresetId } from "./presets.ts";
import { choose } from "./rideTypeDialog.ts";

/** The ride type, its sliders, and the file the plan was opened from. */
export interface Ride {
  preset: PresetId;
  dials: Dials;
  imported: ImportedPlan | null;
}

export function rideAfterImport(
  plan: Pick<ImportedPlan, "preset" | "dials">,
  now: { preset: PresetId; dials: Dials },
): { preset: PresetId; dials: Dials } {
  if (!plan.preset) return { preset: now.preset, dials: now.dials };
  // Whether the ride is a loop is the file's (loop=1 in its sliders), so a
  // loop the page had on before is not carried as the dialog carries it.
  const dials = plan.dials
    ? fitDials(plan.preset, { when: now.dials.when, ...plan.dials })
    : choose(plan.preset, null, { ...now.dials, loop: false });
  return { preset: plan.preset, dials };
}

/** "Start", "Start and finish", "Stop 3", "End": what RouteMaker's own export calls its points, which is no place name. ("Via 3" is what files from before the rename say.) */
function isRoleName(name: string): boolean {
  return name === LOOP_START_NAME || /^(Start|End|Via point|(?:Stop|Via) \d+)$/.test(name);
}

/** The names the file gives its plan points, to show in the list as a search pick's name is. */
export function namesToKeep(plan: Pick<ImportedPlan, "points" | "pointNames">): Array<[LonLat, string]> {
  const kept: Array<[LonLat, string]> = [];
  plan.points.forEach((point, index) => {
    const name = plan.pointNames?.[index]?.trim();
    if (name && !isRoleName(name)) kept.push([point, name]);
  });
  return kept;
}

/**
 * An opened file as it was kept with its route (v0.9.0, "share the exact route"): the kept plan's points, ride type and
 * sliders, and "Follow the file exactly" as the route was followed. The file's names for its points stay only where
 * the points are the file's own. Without a kept route, the file as it opens.
 */
export function asKept(plan: ImportedPlan, at: { points: LonLat[]; preset: PresetId; dials: Dials } | null, answer: RouteResponse | null): ImportedPlan {
  if (!at || !answer || at.points.length < 2) return plan;
  const same = at.points.length === plan.points.length && at.points.every((p, i) => p[0] === plan.points[i][0] && p[1] === plan.points[i][1]);
  return { ...plan, points: at.points, pointNames: same ? plan.pointNames : undefined, preset: at.preset, dials: at.dials, exact: answer.follows_exactly === true };
}
