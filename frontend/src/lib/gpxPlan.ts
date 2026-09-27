/**
 * An opened GPX file as a plan the editor can change: at most 25 points
 * inside the coverage box, which the router then joins.
 *
 * PLAN.md, Import: a GPX route with at most 25 route points is routed through
 * those points; a denser route, and any track, is a line to follow. The plan
 * is for map matching on the server (a worker job with a progress endpoint).
 * Signed out, nothing is uploaded and there is no job, so a track becomes a
 * handful of via points chosen from its shape (trackMatch.ts), and the page
 * measures and says how closely the rerouted line follows the file.
 *
 * Chosen by measurement on the fifteen reference routes (PUBLIC-GPX report):
 * the track's 15 most significant corners first, then up to three rounds
 * that each add up to 5 points where the routed line missed the track, while
 * less than 97% of it is followed within 30 m and there is room under 25.
 * Corners beat points placed mid-block between them, and routing-led rounds
 * beat spending all 25 points on shape at once, most on the long trail rides.
 */
export const IMPORT_START_POINTS = 15;
export const REFINE_ROUNDS = 3;
export const REFINE_ADD = 5;
export const REFINE_GOAL = 0.97;
import { COVERAGE_BBOX, MAX_POINTS, haversineM, insideCoverage, type LonLat } from "./geo.ts";
import { PLAN_TYPE_PREFIX, type GpxFile } from "./gpx.ts";
import { isPreset, type PresetId } from "./presets.ts";
import { cumulative, dedupe, fidelity, refineVias, significantIndexes, viaPoints } from "./trackMatch.ts";

/** Most vertices the reference line keeps for drawing and measuring. */
export const REFERENCE_MAX_VERTICES = 5000;
/** Metres the reference line may depart from the file's own line. */
export const REFERENCE_TOLERANCE_M = 2;

export type ImportNote =
  | { kind: "outside"; share: number }
  | { kind: "joined"; parts: number }
  | { kind: "waypoints-unused"; count: number }
  | { kind: "skipped"; count: number }
  | { kind: "dense-route"; count: number };

export interface ImportedPlan {
  points: LonLat[];
  /** The ride type a RouteMaker export names, or null. */
  preset: PresetId | null;
  /** What the points came from. */
  source: "route" | "track" | "waypoints";
  /** The file's line inside the coverage box, simplified for drawing; empty when the file has none. */
  reference: LonLat[];
  /** Length of the file's line inside the coverage box, in metres. */
  referenceM: number;
  name?: string;
  notes: ImportNote[];
}

export class ImportError extends Error {
  readonly code: "empty" | "outside" | "waypoints";
  constructor(code: ImportError["code"], message: string) {
    super(message);
    this.code = code;
    this.name = "ImportError";
  }
}

/** The share of a line, by length, outside the coverage box, and its inside runs. */
export function clipToCoverage(line: readonly LonLat[]): { runs: LonLat[][]; outsideShare: number } {
  const runs: LonLat[][] = [];
  let current: LonLat[] = [];
  let outside = 0;
  let total = 0;
  for (let i = 0; i < line.length; i += 1) {
    const p = line[i];
    if (i > 0) {
      const d = haversineM(line[i - 1], p);
      total += d;
      const mid: LonLat = [(line[i - 1][0] + p[0]) / 2, (line[i - 1][1] + p[1]) / 2];
      if (!insideCoverage(mid)) outside += d;
    }
    if (insideCoverage(p)) {
      current.push(p);
    } else if (current.length) {
      runs.push(current);
      current = [];
    }
  }
  if (current.length) runs.push(current);
  const allOutside = line.length > 0 && runs.length === 0;
  return { runs, outsideShare: total > 0 ? outside / total : allOutside ? 1 : 0 };
}

function referenceOf(line: readonly LonLat[]): LonLat[] {
  if (line.length <= 2) return [...line];
  return significantIndexes(line, REFERENCE_MAX_VERTICES, REFERENCE_TOLERANCE_M).map((i) => line[i]);
}

function presetOf(type: string | undefined): PresetId | null {
  if (!type || !type.startsWith(PLAN_TYPE_PREFIX)) return null;
  const id = type.slice(PLAN_TYPE_PREFIX.length);
  return isPreset(id) ? id : null;
}

export function planFromGpx(file: GpxFile, maxPoints: number = MAX_POINTS): ImportedPlan {
  const notes: ImportNote[] = [];
  if (file.skipped > 0) notes.push({ kind: "skipped", count: file.skipped });

  const trackLine: LonLat[] = [];
  let parts = 0;
  for (const track of file.tracks) {
    for (const segment of track.segments) {
      if (segment.length === 0) continue;
      parts += 1;
      trackLine.push(...segment);
    }
  }
  const route = file.routes.find((r) => r.points.length >= 2);
  const routeLine: LonLat[] = route ? route.points.map((p) => [p.lon, p.lat]) : [];
  const name = file.name ?? file.tracks.find((t) => t.name)?.name ?? route?.name;

  // Where the line to draw and follow comes from: the track, or a route too
  // dense to route through point by point.
  let line = trackLine;
  if (line.length < 2 && route && route.points.length > maxPoints) {
    line = routeLine;
    parts = 1;
    notes.push({ kind: "dense-route", count: route.points.length });
  }
  const clipped = clipToCoverage(dedupe(line));
  const inside = clipped.runs.flat();
  const reference = referenceOf(inside);
  const referenceM = cumulative(inside).at(-1) ?? 0;

  const withTail = (plan: Omit<ImportedPlan, "notes" | "name" | "reference" | "referenceM">): ImportedPlan => {
    if (inside.length >= 2) {
      if (clipped.outsideShare > 0) notes.push({ kind: "outside", share: clipped.outsideShare });
      const joined = parts + clipped.runs.length - 1;
      if (joined > 1) notes.push({ kind: "joined", parts: joined });
    }
    if (plan.source !== "waypoints" && file.waypoints.length) {
      notes.push({ kind: "waypoints-unused", count: file.waypoints.length });
    }
    return { ...plan, reference: inside.length >= 2 ? reference : [], referenceM, ...(name ? { name } : {}), notes };
  };

  // A route of at most 25 points, all inside the area: its points are the plan.
  if (route && route.points.length <= maxPoints && routeLine.every(insideCoverage)) {
    return withTail({ points: routeLine, preset: presetOf(route.type), source: "route" });
  }
  if (inside.length >= 2) {
    const start = Math.min(IMPORT_START_POINTS, maxPoints);
    return withTail({ points: viaPoints(inside, start, "corners"), preset: null, source: "track" });
  }
  // A route partly outside the area and no track: its inside points, in order.
  const routeInside = routeLine.filter(insideCoverage);
  if (routeInside.length >= 2 && routeInside.length <= maxPoints) {
    notes.push({ kind: "outside", share: 1 - routeInside.length / routeLine.length });
    return withTail({ points: routeInside, preset: presetOf(route?.type), source: "route" });
  }
  const waypoints: LonLat[] = file.waypoints.map((p) => [p.lon, p.lat]);
  const waypointsInside = waypoints.filter(insideCoverage);
  if (waypointsInside.length >= 2 && waypointsInside.length <= maxPoints) {
    if (waypointsInside.length < waypoints.length) {
      notes.push({ kind: "outside", share: 1 - waypointsInside.length / waypoints.length });
    }
    return withTail({ points: waypointsInside, preset: null, source: "waypoints" });
  }
  const everything = [...trackLine, ...routeLine, ...waypoints];
  if (everything.length > 0 && !everything.some(insideCoverage)) {
    const [west, south, east, north] = COVERAGE_BBOX;
    throw new ImportError(
      "outside",
      `Nothing in this file is inside the area this map covers (${south}° to ${north}° N, ${-east}° to ${-west}° W).`,
    );
  }
  if (waypointsInside.length > maxPoints) {
    throw new ImportError(
      "waypoints",
      `This file has only waypoints, more than ${maxPoints} of them, and no track or route to say their order.`,
    );
  }
  throw new ImportError("empty", "This file has no track, route or waypoints to plan from.");
}

/**
 * The next round of via points for an imported track, or null when fitting
 * is done: the rounds are used up, the plan is full, or the route already
 * follows enough of the track (or refining finds nothing to add).
 */
export function nextRefinement(
  reference: readonly LonLat[],
  points: readonly LonLat[],
  route: readonly LonLat[],
  roundsDone: number,
  maxPoints: number = MAX_POINTS,
): LonLat[] | null {
  if (roundsDone >= REFINE_ROUNDS || points.length >= maxPoints || reference.length < 2 || route.length < 2) return null;
  if (fidelity(reference, route).trackCovered >= REFINE_GOAL) return null;
  const next = refineVias(reference, points, route, Math.min(REFINE_ADD, maxPoints - points.length));
  return next.length > points.length ? next : null;
}
