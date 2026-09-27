/** What the GPX section says, and the export's name and description. */
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { formatClimb, formatDistance } from "./format.ts";
import type { GpxExport } from "./gpx.ts";
import type { ImportNote, ImportedPlan } from "./gpxPlan.ts";
import { presetLabel } from "./presets.ts";
import { FIDELITY_WITHIN_M, type Fidelity } from "./trackMatch.ts";

type ExportedRoute = Pick<
  RouteResponse,
  "preset" | "distance_m" | "climb_m" | "descent_m" | "geometry" | "attribution"
>;

function km(metres: number): string {
  return (metres / 1000).toFixed(1);
}

export function exportName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  return `${presetLabel(route.preset)} route, ${km(route.distance_m)} km`;
}

export function exportFileName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  return `routemaker-${route.preset}-${km(route.distance_m).replace(".", "_")}km.gpx`;
}

export function exportDescription(route: Pick<RouteResponse, "preset" | "distance_m" | "climb_m" | "descent_m">): string {
  return (
    `${presetLabel(route.preset)}. ${formatDistance(route.distance_m)}, ` +
    `climb ${formatClimb(route.climb_m)}, descent ${formatClimb(route.descent_m)}. Planned with RouteMaker.`
  );
}

/** The export of the route shown, planned through `points`. */
export function exportOf(route: ExportedRoute, points: readonly LonLat[]): GpxExport {
  return {
    name: exportName(route),
    description: exportDescription(route),
    attribution: route.attribution,
    preset: route.preset,
    planPoints: points,
    geometry: route.geometry.coordinates,
  };
}

function percent(share: number): number {
  // Never "100%" for a share that is not all, nor "0%" for one that is not none.
  const p = Math.round(share * 100);
  if (p === 100 && share < 1) return 99;
  if (p === 0 && share > 0) return 1;
  return p;
}

function noteText(note: ImportNote): string {
  switch (note.kind) {
    case "outside":
      return `About ${percent(note.share)}% of it is outside the area this map covers and was left out.`;
    case "joined":
      return `Its ${note.parts} separate parts were joined into one route.`;
    case "waypoints-unused":
      return note.count === 1
        ? "Its waypoint was not used: the planner has no cue points yet."
        : `Its ${note.count} waypoints were not used: the planner has no cue points yet.`;
    case "skipped":
      return note.count === 1
        ? "One point had no usable position and was skipped."
        : `${note.count} points had no usable position and were skipped.`;
    case "dense-route":
      return `Its route has ${note.count} points, more than one plan can take, so it was followed as a track.`;
  }
}

/** Sentences about an opened file: what it became, and anything left out. */
export function importSentences(plan: ImportedPlan): string[] {
  const named = plan.name ? `"${plan.name}"` : "The file";
  const count = plan.points.length;
  const head =
    plan.source === "track"
      ? `${named} was a track of ${km(plan.referenceM)} km; it is now a plan of ${count} points that the planner routes between.`
      : plan.source === "route"
        ? `${named} opened as a plan of its ${count} route points${plan.preset ? `, as a ${presetLabel(plan.preset)}` : ""}.`
        : `${named} had no track or route; its ${count} waypoints are the plan, in the file's order.`;
  return [head, ...plan.notes.map(noteText)];
}

/**
 * Below either share the route is said to differ from the file. Measured on
 * the reference routes (PUBLIC-GPX report): the planner reproduces most
 * tracks at 90% and more; below that there is a stretch the rider will want
 * to look at.
 */
export const FIDELITY_WARN_BELOW = 0.9;

export interface FidelityNotice {
  warn: boolean;
  text: string;
}

export function fidelityNotice(f: Fidelity): FidelityNotice {
  const followed = percent(f.trackCovered);
  const onTrack = percent(f.routeOnTrack);
  const head = `The route follows ${followed}% of the file's track to within ${FIDELITY_WITHIN_M} m`;
  if (f.trackCovered >= FIDELITY_WARN_BELOW && f.routeOnTrack >= FIDELITY_WARN_BELOW) {
    return { warn: false, text: `${head}.` };
  }
  const extra = f.routeOnTrack < FIDELITY_WARN_BELOW ? `, and ${100 - onTrack}% of the route is off it` : "";
  return {
    warn: true,
    text:
      `${head}${extra}. The faint line is the file's track: drag or add points where the two part, ` +
      "or try another ride type, since each one weighs streets and trails differently.",
  };
}
