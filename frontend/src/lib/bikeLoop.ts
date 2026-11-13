/**
 * A bike loop from a start and a distance (the improvement backlog of 2026-11-12, item 5; Stephen picked "Plan only
 * for now"): with Make it a loop on and only the start placed, Plan asks for a distance and POST /api/route/loop-shapes
 * answers two or three shapes (core/bike_loop.py), each with its miles, climb and share of quiet riding. Picking one
 * plans it as an ordinary loop: the start, the shape's two corners as via points, and the start again, so saving,
 * sharing, Send to Garmin and a ride's re-plan treat it as any other loop.
 *
 * The shapes' figures are the router's own way round each one, before the plan's search: said as "about". The
 * distance the box starts with, 20 mi (32 km), is our default, unmeasured; the last one asked for is kept on this
 * device.
 */
import type { Dials } from "./dials.ts";
import { closureFields } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { METRES_PER_MILE, formatClimb, formatDistance } from "./format.ts";
import { describeError, type RouteError } from "./api.ts";
import { runs, twoPointsOnly, type PresetId } from "./presets.ts";
import { t } from "./i18n.ts";

/** The loop's length the API takes (core/bike_loop.py TARGET_MIN_M and TARGET_MAX_M): 3 mi to 100 mi. */
export const LOOP_MIN_M = Math.round(3 * METRES_PER_MILE);
export const LOOP_MAX_M = Math.round(100 * METRES_PER_MILE);
/** The box's first distance (our default, unmeasured). */
export const LOOP_DEFAULT_M = Math.round(20 * METRES_PER_MILE);

/** One shape, as the API answers it (core/api.py LoopShapeOut). */
export interface LoopShape {
  points: LonLat[];
  via_points: number[];
  heading_deg: number;
  distance_m: number;
  climb_m: number;
  quiet_pct: number | null;
  busy_m: number | null;
  near_target: boolean;
  spur_pct: number;
  geometry: { type: "LineString"; coordinates: LonLat[] };
}

export type LoopShapesResult = { ok: true; shapes: LoopShape[]; targetM: number } | { ok: false; error: RouteError };

/**
 * Whether a ride type plans a loop from a start and a distance here (core/bike_loop.py offered): every bike ride type
 * that plans loops (our default). Not Mass Ride (one route by design), the bikeshare and transit ride types (a start
 * and an end), nor Run, whose own loop is its target distance in Ride settings.
 */
export function offersBikeLoop(preset: PresetId): boolean {
  return preset !== "mass-ride" && !twoPointsOnly(preset) && !runs(preset);
}

/** Whether Plan shows the loop box: a bike ride type, Make it a loop on, and the start alone. */
export function showsBikeLoop(preset: PresetId, points: readonly LonLat[], loop: boolean): boolean {
  return offersBikeLoop(preset) && loop && points.length === 1;
}

const COMPASS = [t("north"), t("northeast"), t("east"), t("southeast"), t("south"), t("southwest"), t("west"), t("northwest")] as const;

/** The way a shape heads out, in words: "northeast". */
export function headingWord(degrees: number): string {
  const index = Math.round((((degrees % 360) + 360) % 360) / 45) % 8;
  return COMPASS[index];
}

/** A shape's name on its button: "Heads northeast". */
export function shapeName(shape: Pick<LoopShape, "heading_deg">): string {
  return t("Heads {way}", { way: headingWord(shape.heading_deg) });
}

/** A shape's figures in one line, distance first: "About 20.4 mi, 1,150 ft climb, 78% quiet". */
export function shapeLine(shape: LoopShape): string {
  const parts = [t("About {distance}", { distance: formatDistance(shape.distance_m) }), t("{climb} climb", { climb: formatClimb(shape.climb_m) })];
  if (shape.quiet_pct !== null) parts.push(t("{pct}% quiet", { pct: shape.quiet_pct }));
  if (!shape.near_target) parts.push(t("the nearest to your distance found"));
  return parts.join(", ");
}

/**
 * The name the picked shape's last point (the start again) is given: a stop by Plan's rule that a loop's last point is
 * one, so it is named for what it is rather than shown as "Stop 1" alone. Kept as a stop's own name is.
 */
export const FINISH_NAME = t("Finish");

/** What "quiet" means, said once under the shapes. */
export const QUIET_MEANS = t("Quiet is traffic stress level 1 or 2. Figures are before the full plan; picking a shape plans it.");

/**
 * The points a picked shape is planned through: fresh pairs (lib/pointKinds.ts keeps a point's kind on its pair), the
 * start kept as the rider placed it, the corners marked as via points by `markVia`, and the start again at the end.
 */
export function shapePoints(
  start: LonLat,
  shape: LoopShape,
  markVia: (p: LonLat) => LonLat,
  markFinish: (p: LonLat) => LonLat = (p) => p,
): LonLat[] {
  const corners = shape.via_points.map((i) => shape.points[i]).filter((p): p is LonLat => Array.isArray(p) && p.length === 2);
  return [start, ...corners.map((p) => markVia([p[0], p[1]] as LonLat)), markFinish([start[0], start[1]] as LonLat)];
}

/** Whether `points` are a picked shape's (the start, its corners, the start again), so its picker stays to switch. */
export function isShapeOf(points: readonly LonLat[], start: LonLat, shape: LoopShape): boolean {
  if (points.length !== 4) return false;
  const same = (a: LonLat, b: LonLat) => Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;
  return same(points[0], start) && same(points[1], shape.points[1]) && same(points[2], shape.points[2]) && same(points[3], start);
}

const KEPT_KEY = "routemaker.bikeLoopM";

/** The distance last asked for on this device, or our default. Storage that throws or is empty gives the default. */
export function keptLoopM(storage: Pick<Storage, "getItem"> | null = safeStorage()): number {
  try {
    const value = Number(storage?.getItem(KEPT_KEY));
    return Number.isFinite(value) && value >= LOOP_MIN_M && value <= LOOP_MAX_M ? Math.round(value) : LOOP_DEFAULT_M;
  } catch {
    return LOOP_DEFAULT_M;
  }
}

export function keepLoopM(metres: number, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(KEPT_KEY, String(Math.round(metres)));
  } catch {
    // A private window: the box starts at our default next time.
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

/** POST /api/route/loop-shapes's body: the start, the distance, the ride type and the dials a plan would send. */
export function loopShapesBody(start: LonLat, preset: PresetId, dials: Dials, targetM: number): string {
  const body: Record<string, unknown> = {
    start: [start[0], start[1]],
    target_distance_m: Math.round(targetM),
    preset,
    stress: dials.stress,
    hills: dials.hills,
    ...closureFields(dials),
  };
  if (dials.when) body.when = dials.when;
  if (dials.carrying) body.carrying = dials.carrying;
  if (dials.assist) body.assist = true;
  if (dials.trailsOff) body.trails_off = true;
  if (dials.easyMtb) body.easy_mtb = true;
  if (typeof dials.ridingSpeedKmh === "number" && Number.isFinite(dials.ridingSpeedKmh)) body.cycling_speed_kmh = dials.ridingSpeedKmh;
  return JSON.stringify(body);
}

function looksLikeShape(value: unknown): value is LoopShape {
  if (typeof value !== "object" || value === null) return false;
  const s = value as Record<string, unknown>;
  return (
    Array.isArray(s.points) &&
    s.points.length === 4 &&
    Array.isArray(s.via_points) &&
    typeof s.distance_m === "number" &&
    typeof s.climb_m === "number" &&
    typeof s.heading_deg === "number"
  );
}

/** The shapes for a loop of about `targetM` from `start`, or the error as the route's errors are said. */
export async function requestLoopShapes(
  start: LonLat,
  preset: PresetId,
  dials: Dials,
  targetM: number,
  options: { fetchImpl?: FetchLike; signal?: AbortSignal; planId?: string } = {},
): Promise<LoopShapesResult> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  try {
    const response = await fetchImpl("/api/route/loop-shapes", {
      method: "POST",
      // Named (X-Plan-Id), so a search given up on is stopped on the server too (lib/api.ts cancelRoute).
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(options.planId ? { "X-Plan-Id": options.planId } : {}) },
      body: loopShapesBody(start, preset, dials, targetM),
      signal: options.signal,
    });
    const body: unknown = await response.json().catch(() => null);
    const shapes = (body as { shapes?: unknown } | null)?.shapes;
    if (response.ok && Array.isArray(shapes)) {
      const kept = shapes.filter(looksLikeShape);
      if (kept.length) return { ok: true, shapes: kept, targetM };
    }
    return { ok: false, error: describeError(response.ok ? 500 : response.status, body, response.headers.get("Retry-After")) };
  } catch {
    return { ok: false, error: { kind: "network", status: 0, title: t("Can't reach the planner"), message: "" } };
  }
}
