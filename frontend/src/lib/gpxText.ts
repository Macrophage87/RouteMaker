/** What the GPX section says, and the export's name and description. */
import type { RouteProfile, RouteResponse } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { WHENS, carryingWords, hillsWords, seeksClimbs, stressWords, whenInSentence } from "./dials.ts";
import type { ExportDials, GpxExport } from "./gpx.ts";
import { JOIN_GAP_M, type ImportNote, type ImportedPlan } from "./gpxPlan.ts";
import { presetSaid, type PresetId } from "./presets.ts";
import { gpxDescriptionText } from "./routeDescription.ts";
import { FIDELITY_WITHIN_M, type Fidelity } from "./trackMatch.ts";
import { formatClimb, formatDistance, milesFigure } from "./format.ts";

type ExportedRoute = Pick<
  RouteResponse,
  "preset" | "distance_m" | "climb_m" | "descent_m" | "geometry" | "attribution"
> &
  Partial<Pick<RouteResponse, "dials" | "description" | "description_overview" | "profile">>;

// US units first, metric in brackets (owner decision), in everything the
// file and this section say: the app's one formatter (format.ts).
const mi = milesFigure;

/** "4.7 mi (7.6 km)". */
export const milesText = formatDistance;

/** "266 ft (81 m)". */
export const feetText = formatClimb;

export function exportName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  return `${presetSaid(route.preset)} route, ${milesText(route.distance_m)}`;
}

export function exportFileName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  return `routemaker-${route.preset}-${mi(route.distance_m).replace(".", "_")}mi.gpx`;
}

export function exportDescription(route: Pick<RouteResponse, "preset" | "distance_m" | "climb_m" | "descent_m">): string {
  return (
    `${presetSaid(route.preset)}. ${milesText(route.distance_m)}, ` +
    `climb ${feetText(route.climb_m)}, descent ${feetText(route.descent_m)}. Planned with RouteMaker.`
  );
}

/** The ride type and the sliders the route was planned with, in words (rte/desc). */
export function rideText(route: Pick<RouteResponse, "preset"> & Partial<Pick<RouteResponse, "dials">>): string {
  const head = `Ride type: ${presetSaid(route.preset)}.`;
  const d = route.dials;
  if (!d) return head;
  const when = WHENS.find((w) => w.id === d.when)?.label;
  return (
    `${head} Traffic slider ${d.stress} of 100 (${stressWords(d.stress)}); ` +
    `hills slider ${d.hills} (${hillsWords(d.hills, seeksClimbs(route.preset))})` +
    (when ? `; ride time ${whenInSentence(when)}` : "") +
    (d.carrying ? `; ${carryingWords(d.carrying)}` : "") +
    (d.assist ? "; electric assist" : "") +
    // "Keep to roads, not trails" (OWNER-DECISIONS 463); Mass Ride always keeps to roads, so it is not said there.
    (d.trails_off === true && route.preset !== "mass-ride" ? "; roads only, no trails" : "") +
    "."
  );
}

/**
 * The elevation at each vertex of `line` from the route's profile, for the
 * GPX track's <ele>. The profile is sampled by distance along the route as the
 * router measured it, so each vertex's distance along the line is scaled to
 * the profile's length and the two samples either side of it are interpolated.
 * Null where either of those samples has no elevation (a leg the router had
 * none for), and all null without a profile. The figures are the router's
 * (the same ones the elevation chart draws), in metres, as GPX requires.
 */
export function elevationsAlong(
  line: readonly LonLat[],
  profile: Pick<RouteProfile, "m" | "elevation_m"> | null | undefined,
): (number | null)[] {
  const none = () => line.map(() => null);
  if (!profile || profile.m.length < 2 || profile.m.length !== profile.elevation_m.length || line.length === 0) return none();
  if (!profile.elevation_m.some((e) => e !== null)) return none();
  const along: number[] = [0];
  for (let i = 1; i < line.length; i += 1) along.push(along[i - 1] + haversineM(line[i - 1], line[i]));
  const lineM = along[along.length - 1];
  const first = profile.m[0];
  const profileM = profile.m[profile.m.length - 1] - first;
  const scale = lineM > 0 ? profileM / lineM : 0;
  const out: (number | null)[] = [];
  let j = 0;
  for (const d of along) {
    const at = first + d * scale;
    // Advance to the last sample at or before `at` (the walk only moves forward).
    while (j < profile.m.length - 2 && profile.m[j + 1] <= at) j += 1;
    const m0 = profile.m[j];
    const m1 = profile.m[j + 1];
    const e0 = profile.elevation_m[j];
    const e1 = profile.elevation_m[j + 1];
    if (at <= m0 || m1 <= m0) {
      out.push(e0);
    } else if (at >= m1) {
      out.push(e1);
    } else if (e0 === null || e1 === null) {
      out.push(null);
    } else {
      out.push(e0 + ((e1 - e0) * (at - m0)) / (m1 - m0));
    }
  }
  return out;
}

/**
 * The export of the route shown, planned through `points`. `loop` is
 * whether that route was planned as a loop the rider chose (App's
 * routedLoop, from loop.loopStops; OWNER-DECISIONS 374), not the live toggle
 * and not the API's echoed `dials.loop`, which is also true for a ride that
 * ends on its start with the toggle off; such a ride keeps Start and End.
 * Mass Ride has no loop. `federal` is a Mass Ride's federal-land lines
 * (lib/federalStops.ts federalLines, item 239), carried in the description.
 */
export function exportOf(route: ExportedRoute, points: readonly LonLat[], loop = false, federal: readonly string[] = [], vias: readonly number[] = []): GpxExport {
  const dials: ExportDials | undefined = route.dials
    ? {
        stress: route.dials.stress,
        hills: route.dials.hills,
        when: route.dials.when,
        carrying: route.dials.carrying,
        assist: route.dials.assist === true,
        ...(route.dials.trails_off === true && route.preset !== "mass-ride" ? { trailsOff: true } : {}),
      }
    : undefined;
  return {
    name: exportName(route),
    description: exportDescription(route),
    attribution: route.attribution,
    preset: route.preset,
    ...(dials ? { dials } : {}),
    rideText: rideText(route),
    ...(gpxDescriptionText(route, federal) ? { routeText: gpxDescriptionText(route, federal) } : {}),
    planPoints: points,
    ...(vias.length ? { vias } : {}),
    ...(loop && route.preset !== "mass-ride" ? { loop: true } : {}),
    geometry: route.geometry.coordinates,
    ...(route.profile ? { elevations: elevationsAlong(route.geometry.coordinates, route.profile) } : {}),
  };
}

function percent(share: number): number {
  // Never "100%" for a share that is not all, nor "0%" for one that is not none.
  const p = Math.round(share * 100);
  if (p === 100 && share < 1) return 99;
  if (p === 0 && share > 0) return 1;
  return p;
}

/** Most waypoint names said in the sentence; the rest are counted. */
export const WAYPOINT_NAMES_SAID = 8;

/** "Its 3 named waypoints are marked on the map: Coffee, Water, Summit." The names are the file's, cleaned (gpxPlan.ts). */
export function waypointsShownText(names: readonly string[]): string {
  const said = names.slice(0, WAYPOINT_NAMES_SAID).join(", ");
  const more = names.length > WAYPOINT_NAMES_SAID ? `, and ${names.length - WAYPOINT_NAMES_SAID} more` : "";
  return names.length === 1 ? `Its named waypoint is marked on the map: ${said}.` : `Its ${names.length} named waypoints are marked on the map: ${said}${more}.`;
}

function noteText(note: ImportNote): string {
  switch (note.kind) {
    case "outside":
      return `About ${percent(note.share)}% of it is outside the area this map covers and was left out.`;
    case "joined":
      return `Its ${note.parts} separate parts were joined into one route.`;
    case "far-parts":
      return note.count === 1
        ? `The plan follows its longest part; one other part lies more than ${milesText(JOIN_GAP_M)} from it and was left out.`
        : `The plan follows its longest part; ${note.count} other parts lie more than ${milesText(JOIN_GAP_M)} from it and were left out.`;
    case "waypoints-unused":
      return note.count === 1
        ? "One waypoint was not marked on the map: it has no name, lies outside the area, or is past the most the map marks."
        : `${note.count} waypoints were not marked on the map: they have no name, lie outside the area, or are past the most the map marks.`;
    case "waypoints-shown":
      return waypointsShownText(note.names);
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
        `${named} was a track of ${milesText(plan.referenceM)}; the route follows it, with points taken from its shape to edit.`
      : plan.source === "route"
        ? `${named} opened as a plan of its ${count} route points${plan.preset ? `, as a ${presetSaid(plan.preset)}` : ""}.`
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
        `so it opened as ${presetSaid("default")}. Choose another ride type if you like.`
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

export function fidelityNotice(f: Fidelity, followedAs?: PresetId): FidelityNotice {
  const followed = percent(f.trackCovered);
  const onTrack = percent(f.routeOnTrack);
  const head = `The route follows ${followed}% of the file's track to within ${feetText(FIDELITY_WITHIN_M)}`;
  const close = f.trackCovered >= FIDELITY_WARN_BELOW && f.routeOnTrack >= FIDELITY_WARN_BELOW;
  // The route is the file's own line (core/follow.py): it parts from it only where the ride type cannot ride it.
  if (followedAs) {
    const as = presetSaid(followedAs);
    if (close) return { warn: false, text: `The route follows the file's track, rated for ${as}.` };
    return { warn: true, text: `${head}, rated for ${as}; where the faint line parts from it, the map has no way there for ${as}.` };
  }
  if (close) return { warn: false, text: `${head}.` };
  const extra = f.routeOnTrack < FIDELITY_WARN_BELOW ? `, and ${100 - onTrack}% of the route is off it` : "";
  return {
    warn: true,
    text:
      `${head}${extra}. The faint line is the file's track: drag or add points where the two part, ` +
      "or try another ride type, since each one weighs streets and trails differently.",
  };
}

/**
 * Where a followed file rides against one-way traffic (core/follow.py `against_traffic`): the route follows it there,
 * so it is said, by street, the first three named. Null where there is none.
 */
export function againstTrafficNotice(stretches: readonly { name: string | null; distance_m: number }[] | null | undefined): string | null {
  if (!stretches?.length) return null;
  const said = stretches.slice(0, 3).map((s) => `${s.name ?? "an unnamed street"} (${formatDistance(s.distance_m)})`);
  if (stretches.length > 3) said.push(`${stretches.length - 3} more`);
  const list = said.length > 1 ? `${said.slice(0, -1).join(", ")} and ${said.at(-1)}` : said[0];
  return `The file rides against one-way traffic on ${list}. The route follows it there, so take care.`;
}

/**
 * What fitting took out (gpxPlan.ts, nextFitStep): points the route could
 * reach only by looping round or riding out and back, where the file goes a
 * way the ride type does not ride (a trail on Mass Ride, a one-way against
 * its traffic).
 */
export function prunedNotice(count: number): string {
  const points = count === 1 ? "1 point" : `${count} points`;
  return (
    `Took out ${points} the route could reach only by looping round or riding out and back: ` +
    "the file goes a way this ride type does not ride there, so the route goes its own way."
  );
}
