/**
 * Dragging the drawn route to reshape it, as Ride with GPS and Strava do: the
 * rider grabs the line somewhere in one leg (the stretch between two of their
 * points) and pulls; on release a via goes into THAT leg, between its two
 * points. addPoint's rule for a click - the leg the via lengthens least - is
 * not used here: a drag says which leg it means.
 *
 * Which leg a spot on the line is in comes from the API's `leg_ends` (the
 * index of each leg's last vertex in the line). An API that predates the
 * field, or an answer that does not fit the points, falls back to matching
 * each via to its nearest vertex, in order along the line.
 */
import { MAX_POINTS, haversineM, type LonLat } from "./geo.ts";

/** Where on a path a point is nearest: segment i runs from vertex i to i + 1. */
export interface OnPath {
  segment: number;
  /** How far along the segment, 0 at its start and 1 at its end. */
  t: number;
  point: LonLat;
}

/**
 * The point on `path` nearest `p`. Distances are measured in a flat frame
 * about `p` with longitude scaled by the cosine of its latitude, which over
 * the few kilometres a cursor is from a line is the ground's own measure (and
 * the screen's: Web Mercator is conformal). Null for a path with no segment.
 */
export function nearestOnPath(path: readonly LonLat[], p: LonLat): OnPath | null {
  if (path.length < 2) return null;
  const k = Math.cos((p[1] * Math.PI) / 180);
  let best: OnPath | null = null;
  let bestD = Number.POSITIVE_INFINITY;
  for (let i = 0; i + 1 < path.length; i += 1) {
    const a = path[i];
    const b = path[i + 1];
    const ax = (a[0] - p[0]) * k;
    const ay = a[1] - p[1];
    const dx = (b[0] - a[0]) * k;
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.min(1, Math.max(0, -(ax * dx + ay * dy) / len2)) : 0;
    const x = ax + t * dx;
    const y = ay + t * dy;
    const d = x * x + y * y;
    if (d < bestD) {
      bestD = d;
      best = { segment: i, t, point: [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])] };
    }
  }
  return best;
}

/**
 * The leg a segment of the line is in. Leg k runs from vertex ends[k - 1]
 * (0 for the first) to ends[k], so segment i is in the first leg that ends
 * after vertex i. A leg of no length holds no segment and is never chosen.
 */
export function legOfSegment(ends: readonly number[], segment: number): number {
  for (let k = 0; k < ends.length; k += 1) {
    if (segment < ends[k]) return k;
  }
  return ends.length - 1;
}

/** Whether the API's `leg_ends` describe a line of `vertexCount` vertices through `pointCount` points. */
export function validLegEnds(ends: unknown, vertexCount: number, pointCount: number): ends is number[] {
  if (!Array.isArray(ends) || ends.length !== pointCount - 1) return false;
  let previous = 0;
  for (const end of ends) {
    if (!Number.isInteger(end) || end < previous || end > vertexCount - 1) return false;
    previous = end;
  }
  return previous === vertexCount - 1;
}

/**
 * Leg ends matched from the geometry alone: each via's boundary is a vertex,
 * the boundaries run forwards along the line, and the total distance from
 * each via to its vertex is the least it can be. Run once per route; 25
 * points by a few thousand vertices is quick.
 */
export function guessLegEnds(path: readonly LonLat[], points: readonly LonLat[]): number[] {
  const last = path.length - 1;
  const vias = points.slice(1, -1);
  if (vias.length === 0 || path.length === 0) return [Math.max(0, last)];
  // cost[v]: the least total with the current via at vertex v; from[j][v]:
  // where the via before it was, for walking back.
  let prefix = new Array<number>(path.length).fill(0);
  let prefixAt = Array.from({ length: path.length }, (_, v) => v);
  const from: number[][] = [];
  let cost: number[] = [];
  for (const via of vias) {
    cost = path.map((vertex, v) => haversineM(via, vertex) + prefix[v]);
    from.push(prefixAt);
    const nextPrefix = new Array<number>(path.length);
    const nextAt = new Array<number>(path.length);
    for (let v = 0; v < path.length; v += 1) {
      if (v > 0 && nextPrefix[v - 1] <= cost[v]) {
        nextPrefix[v] = nextPrefix[v - 1];
        nextAt[v] = nextAt[v - 1];
      } else {
        nextPrefix[v] = cost[v];
        nextAt[v] = v;
      }
    }
    prefix = nextPrefix;
    prefixAt = nextAt;
  }
  const ends = new Array<number>(vias.length);
  let at = prefixAt[last];
  for (let j = vias.length - 1; j >= 0; j -= 1) {
    ends[j] = at;
    at = from[j][at];
  }
  return [...ends, last];
}

/** The API's leg ends when they fit this line and these points; otherwise the geometry's guess. */
export function legEnds(path: readonly LonLat[], points: readonly LonLat[], fromApi: unknown): number[] {
  return validLegEnds(fromApi, path.length, points.length) ? [...fromApi] : guessLegEnds(path, points);
}

/**
 * The points with `via` put into leg `leg` (between points[leg] and
 * points[leg + 1]). Null when the route already has the most points one
 * request may carry, or there is no such leg.
 */
export function insertIntoLeg(points: readonly LonLat[], leg: number, via: LonLat): LonLat[] | null {
  if (points.length >= MAX_POINTS) return null;
  if (!Number.isInteger(leg) || leg < 0 || leg > points.length - 2) return null;
  return [...points.slice(0, leg + 1), via, ...points.slice(leg + 1)];
}

/** The light preview while dragging: from the grabbed leg's two points to the cursor. */
export function dragPreview(points: readonly LonLat[], leg: number, cursor: LonLat): LonLat[][] {
  return [
    [points[leg], cursor],
    [cursor, points[leg + 1]],
  ];
}
