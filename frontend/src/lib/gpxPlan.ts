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
import { PLAN_TYPE_PREFIX, parseDialsComment, type GpxFile, type GpxRoute } from "./gpx.ts";
import { DEFAULT_PRESET, isPreset, type PresetId } from "./presets.ts";
import { isCarrying, isWhen, type Dials } from "./dials.ts";
import { cumulative, dedupe, fidelity, refineVias, significantIndexes, viaPoints } from "./trackMatch.ts";

/** Most vertices the reference line keeps for drawing and measuring. */
export const REFERENCE_MAX_VERTICES = 5000;
/** Metres the reference line may depart from the file's own line. */
export const REFERENCE_TOLERANCE_M = 2;
/**
 * Largest gap, in metres, between one part of a file's line and the next that
 * is still joined into one line: half a mile (805 m). A GPS dropout under a
 * bridge or a paused recording resumes close by; a gap wider than this is a
 * different ride, or the far side of a stretch outside the coverage box, and
 * following the straight jump across it as track froze the page (PLAN.md, the
 * GPX far-apart-parts import fix).
 */
export const JOIN_GAP_M = 805;

export type ImportNote =
  | { kind: "outside"; share: number }
  | { kind: "joined"; parts: number }
  /** Parts lying more than JOIN_GAP_M from the part followed, left out rather than joined to it. */
  | { kind: "far-parts"; count: number }
  | { kind: "waypoints-unused"; count: number }
  | { kind: "skipped"; count: number }
  | { kind: "dense-route"; count: number }
  /** The file names a RouteMaker ride type the planner no longer offers; it opens as Default. */
  | { kind: "preset-gone"; id: string };

export interface ImportedPlan {
  points: LonLat[];
  /** The ride type a RouteMaker export names (Default for one no longer offered), or null. */
  preset: PresetId | null;
  /** The sliders a RouteMaker export was planned with, as far as the file says them; checked by fitDials. */
  dials?: Partial<Dials>;
  /** The names the file gives the plan's points, index for index (undefined where it gives none). */
  pointNames?: Array<string | undefined>;
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

/**
 * The part of a file's line the plan follows. Each segment is clipped to the
 * coverage box; the pieces that leaves, in the file's order, are joined while
 * each starts within JOIN_GAP_M of where the one before it ended. Of the
 * joined runs the longest is followed, and the pieces of the rest are counted
 * as left out (leftOut counts those runs, not their pieces): joining them
 * would draw a straight jump across the gap and follow it as track. A
 * one-point piece joins its neighbours like any other (some apps write a
 * segment per point), but a run that is one point on its own is no line and
 * neither followed nor counted. outsideShare is the share of the file's
 * length outside the box, the gaps between segments not counted.
 */
export function followedPart(lines: readonly (readonly LonLat[])[]): {
  pieces: LonLat[][];
  leftOut: number;
  outsideShare: number;
} {
  const pieces: LonLat[][] = [];
  let outside = 0;
  let total = 0;
  let anyPoint = false;
  for (const segment of lines) {
    if (segment.length) anyPoint = true;
    const kept = dedupe(segment);
    const clipped = clipToCoverage(kept);
    const length = cumulative(kept).at(-1) ?? 0;
    total += length;
    outside += clipped.outsideShare * length;
    pieces.push(...clipped.runs);
  }
  const chains: LonLat[][][] = [];
  for (const piece of pieces) {
    const last = chains.at(-1);
    const end = last?.at(-1)?.at(-1);
    if (last && end && haversineM(end, piece[0]) <= JOIN_GAP_M) last.push(piece);
    else chains.push([piece]);
  }
  // A run that is a lone point (a track grazing the box) is no line to follow.
  const runsToFollow = chains.filter((chain) => dedupe(chain.flat()).length >= 2);
  let best: LonLat[][] = [];
  let bestM = -1;
  for (const chain of runsToFollow) {
    const m = cumulative(chain.flat()).at(-1) ?? 0;
    if (m > bestM) {
      best = chain;
      bestM = m;
    }
  }
  const allOutside = anyPoint && pieces.length === 0;
  return {
    pieces: best,
    leftOut: Math.max(0, runsToFollow.length - 1),
    outsideShare: total > 0 ? outside / total : allOutside ? 1 : 0,
  };
}

function referenceOf(line: readonly LonLat[]): LonLat[] {
  if (line.length <= 2) return [...line];
  return significantIndexes(line, REFERENCE_MAX_VERTICES, REFERENCE_TOLERANCE_M).map((i) => line[i]);
}

/**
 * The ride type and sliders a RouteMaker export's route names. A ride type
 * the planner no longer offers is Default, with a note; its sliders were that
 * ride type's, so they are not kept.
 */
function rideOf(route: GpxRoute | undefined, notes: ImportNote[]): Pick<ImportedPlan, "preset" | "dials"> {
  const type = route?.type;
  if (!type || !type.startsWith(PLAN_TYPE_PREFIX)) return { preset: null };
  const id = type.slice(PLAN_TYPE_PREFIX.length);
  if (!isPreset(id)) {
    notes.push({ kind: "preset-gone", id });
    return { preset: DEFAULT_PRESET };
  }
  const fields = parseDialsComment(route?.cmt);
  if (!fields) return { preset: id };
  const dials: Partial<Dials> = {};
  const stress = Number(fields.stress);
  const hills = Number(fields.hills);
  if (fields.stress !== undefined && Number.isFinite(stress)) dials.stress = stress;
  if (fields.hills !== undefined && Number.isFinite(hills)) dials.hills = hills;
  if (isWhen(fields.when)) dials.when = fields.when;
  if (isCarrying(fields.carrying)) dials.carrying = fields.carrying;
  if (fields.assist === "1") dials.assist = true;
  // A loop the rider chose (OWNER-DECISIONS 374): without it the last stop would open as the end.
  if (fields.loop === "1") dials.loop = true;
  // "Keep to roads, not trails" (OWNER-DECISIONS 463): without it the plan would reopen on trails.
  if (fields.trailsoff === "1") dials.trailsOff = true;
  return { preset: id, dials };
}

export function planFromGpx(file: GpxFile, maxPoints: number = MAX_POINTS): ImportedPlan {
  const notes: ImportNote[] = [];
  if (file.skipped > 0) notes.push({ kind: "skipped", count: file.skipped });

  const segments: LonLat[][] = [];
  for (const track of file.tracks) {
    for (const segment of track.segments) {
      if (segment.length > 0) segments.push(segment);
    }
  }
  const trackLine: LonLat[] = segments.flat();
  const route = file.routes.find((r) => r.points.length >= 2);
  const routeLine: LonLat[] = route ? route.points.map((p) => [p.lon, p.lat]) : [];
  const name = file.name ?? file.tracks.find((t) => t.name)?.name ?? route?.name;

  // Where the line to draw and follow comes from: the track, or a route too
  // dense to route through point by point.
  let lines = segments;
  if (trackLine.length < 2 && route && route.points.length > maxPoints) {
    lines = [routeLine];
    notes.push({ kind: "dense-route", count: route.points.length });
  }
  const followed = followedPart(lines);
  const inside = followed.pieces.flat();
  const reference = referenceOf(inside);
  const referenceM = cumulative(inside).at(-1) ?? 0;

  const withTail = (plan: Omit<ImportedPlan, "notes" | "name" | "reference" | "referenceM">): ImportedPlan => {
    if (inside.length >= 2) {
      if (followed.outsideShare > 0) notes.push({ kind: "outside", share: followed.outsideShare });
      if (followed.pieces.length > 1) notes.push({ kind: "joined", parts: followed.pieces.length });
      if (followed.leftOut > 0) notes.push({ kind: "far-parts", count: followed.leftOut });
    }
    if (plan.source !== "waypoints" && file.waypoints.length) {
      notes.push({ kind: "waypoints-unused", count: file.waypoints.length });
    }
    return { ...plan, reference: inside.length >= 2 ? reference : [], referenceM, ...(name ? { name } : {}), notes };
  };

  // A route of at most 25 points, all inside the area: its points are the plan.
  if (route && route.points.length <= maxPoints && routeLine.every(insideCoverage)) {
    return withTail({
      points: routeLine,
      ...rideOf(route, notes),
      pointNames: route.points.map((p) => p.name),
      source: "route",
    });
  }
  if (inside.length >= 2) {
    const start = Math.min(IMPORT_START_POINTS, maxPoints);
    return withTail({ points: viaPoints(inside, start, "corners"), preset: null, source: "track" });
  }
  // A route partly outside the area and no track: its inside points, in order.
  const routeInside = routeLine.filter(insideCoverage);
  if (routeInside.length >= 2 && routeInside.length <= maxPoints) {
    notes.push({ kind: "outside", share: 1 - routeInside.length / routeLine.length });
    const names = (route?.points ?? []).filter((p) => insideCoverage([p.lon, p.lat])).map((p) => p.name);
    return withTail({ points: routeInside, ...rideOf(route, notes), pointNames: names, source: "route" });
  }
  const waypoints: LonLat[] = file.waypoints.map((p) => [p.lon, p.lat]);
  const waypointsInside = waypoints.filter(insideCoverage);
  if (waypointsInside.length >= 2 && waypointsInside.length <= maxPoints) {
    if (waypointsInside.length < waypoints.length) {
      notes.push({ kind: "outside", share: 1 - waypointsInside.length / waypoints.length });
    }
    const names = file.waypoints.filter((p) => insideCoverage([p.lon, p.lat])).map((p) => p.name);
    return withTail({ points: waypointsInside, preset: null, pointNames: names, source: "waypoints" });
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
