/** What the GPX section says, and the export's name and description. */
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { WHENS, carryingWords, hillsWords, stressWords } from "./dials.ts";
import type { ExportDials, GpxExport } from "./gpx.ts";
import type { ImportNote, ImportedPlan } from "./gpxPlan.ts";
import { presetLabel } from "./presets.ts";
import { gpxDescriptionText } from "./routeDescription.ts";
import { FIDELITY_WITHIN_M, type Fidelity } from "./trackMatch.ts";
import { formatClimb, formatDistance, milesFigure } from "./format.ts";

type ExportedRoute = Pick<
  RouteResponse,
  "preset" | "distance_m" | "climb_m" | "descent_m" | "geometry" | "attribution"
> &
  Partial<Pick<RouteResponse, "dials" | "description" | "description_overview">>;

// US units first, metric in brackets (owner decision), in everything the
// file and this section say: the app's one formatter (format.ts).
const mi = milesFigure;

/** "4.7 mi (7.6 km)". */
export const milesText = formatDistance;

/** "266 ft (81 m)". */
export const feetText = formatClimb;

export function exportName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  return `${presetLabel(route.preset)} route, ${milesText(route.distance_m)}`;
}

export function exportFileName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  return `routemaker-${route.preset}-${mi(route.distance_m).replace(".", "_")}mi.gpx`;
}

export function exportDescription(route: Pick<RouteResponse, "preset" | "distance_m" | "climb_m" | "descent_m">): string {
  return (
    `${presetLabel(route.preset)}. ${milesText(route.distance_m)}, ` +
    `climb ${feetText(route.climb_m)}, descent ${feetText(route.descent_m)}. Planned with RouteMaker.`
  );
}

/** The ride type and the sliders the route was planned with, in words (rte/desc). */
export function rideText(route: Pick<RouteResponse, "preset"> & Partial<Pick<RouteResponse, "dials">>): string {
  const head = `Ride type: ${presetLabel(route.preset)}.`;
  const d = route.dials;
  if (!d) return head;
  const when = WHENS.find((w) => w.id === d.when)?.label;
  return (
    `${head} Traffic slider ${d.stress} of 100 (${stressWords(d.stress)}); ` +
    `hills slider ${d.hills} (${hillsWords(d.hills)})` +
    (when ? `; ride time ${when.toLowerCase()}` : "") +
    (d.carrying ? `; ${carryingWords(d.carrying)}` : "") +
    (d.assist ? "; electric assist" : "") +
    "."
  );
}

/** The export of the route shown, planned through `points`. */
export function exportOf(route: ExportedRoute, points: readonly LonLat[]): GpxExport {
  const dials: ExportDials | undefined = route.dials
    ? {
        stress: route.dials.stress,
        hills: route.dials.hills,
        when: route.dials.when,
        carrying: route.dials.carrying,
        assist: route.dials.assist === true,
      }
    : undefined;
  return {
    name: exportName(route),
    description: exportDescription(route),
    attribution: route.attribution,
    preset: route.preset,
    ...(dials ? { dials } : {}),
    rideText: rideText(route),
    ...(gpxDescriptionText(route) ? { routeText: gpxDescriptionText(route) } : {}),
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
    case "preset-gone":
      return `Its ride type "${note.id}" is no longer offered.`;
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
      ? // No count: fitting adds points after this is said (GpxPanel), and the list shows them.
        `${named} was a track of ${milesText(plan.referenceM)}; the plan follows it through points taken from its shape.`
      : plan.source === "route"
        ? `${named} opened as a plan of its ${count} route points${plan.preset ? `, as a ${presetLabel(plan.preset)}` : ""}.`
        : `${named} had no track or route; its ${count} waypoints are the plan, in the file's order.`;
  return [head, ...plan.notes.filter((note) => note.kind !== "preset-gone").map(noteText)];
}

/**
 * The notice for a file whose ride type the planner no longer offers: it
 * opened as Default instead (gpxPlan.ts). Shown as a notice, not a hint.
 */
export function presetNotice(plan: Pick<ImportedPlan, "notes">): string | null {
  for (const note of plan.notes) {
    if (note.kind === "preset-gone") {
      return (
        `This file was planned as "${note.id}", a ride type RouteMaker no longer offers, ` +
        `so it opened as ${presetLabel("default")}. Choose another ride type if you like.`
      );
    }
  }
  return null;
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
  const head = `The route follows ${followed}% of the file's track to within ${feetText(FIDELITY_WITHIN_M)}`;
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
