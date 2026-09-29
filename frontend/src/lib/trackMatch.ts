/**
 * Track geometry for the GPX import: choosing a few via points that make the
 * router follow a track, and measuring how closely a routed line does.
 *
 * Distances are on a local plane (equirectangular about the track's mean
 * latitude), which inside the coverage box is within a fraction of a percent
 * of the ground distance at the scale of a street - well inside the 30 m the
 * fidelity figure is measured at.
 */
import { haversineM, type LonLat } from "./geo.ts";

const M_PER_DEG_LAT = 111_195;

interface Plane {
  x: (p: LonLat) => number;
  y: (p: LonLat) => number;
}

function planeFor(points: readonly LonLat[]): Plane {
  let sum = 0;
  for (const p of points) sum += p[1];
  const lat = points.length ? sum / points.length : 0;
  const kx = M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
  return { x: (p) => p[0] * kx, y: (p) => p[1] * M_PER_DEG_LAT };
}

/** Distance in metres from p to the segment ab, all on the plane. */
function segmentDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  let t = len2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const ex = ax + t * dx - px;
  const ey = ay + t * dy - py;
  return Math.sqrt(ex * ex + ey * ey);
}

/** Consecutive duplicates dropped (a paused recorder writes many). */
export function dedupe(points: readonly LonLat[], minM = 0.5): LonLat[] {
  const out: LonLat[] = [];
  for (const p of points) {
    if (!out.length || haversineM(out[out.length - 1], p) >= minM) out.push(p);
  }
  return out;
}

/**
 * The indexes Douglas-Peucker keeps, greedily: start from the two ends and
 * split, each time, the span whose farthest point is farthest off its chord,
 * until `count` indexes are kept or every point is within `toleranceM`.
 * Greedy rather than a fixed tolerance so the budget of points (25 per route)
 * goes to the track's biggest departures first. A loop's two ends coincide;
 * the chord is then a point and the distance is to it.
 */
export function significantIndexes(points: readonly LonLat[], count: number, toleranceM = 0): number[] {
  const n = points.length;
  if (n <= 2 || count <= 2) return n <= 1 ? [0].slice(0, n) : [0, n - 1];
  const plane = planeFor(points);
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    xs[i] = plane.x(points[i]);
    ys[i] = plane.y(points[i]);
  }
  const farthest = (a: number, b: number): { index: number; distance: number } => {
    let index = -1;
    let distance = -1;
    for (let i = a + 1; i < b; i += 1) {
      const d = segmentDistance(xs[i], ys[i], xs[a], ys[a], xs[b], ys[b]);
      if (d > distance) {
        distance = d;
        index = i;
      }
    }
    return { index, distance };
  };
  const spans: Array<{ a: number; b: number; index: number; distance: number }> = [];
  const push = (a: number, b: number) => {
    if (b - a >= 2) spans.push({ a, b, ...farthest(a, b) });
  };
  push(0, n - 1);
  const kept = [0, n - 1];
  while (kept.length < count && spans.length) {
    let best = 0;
    for (let s = 1; s < spans.length; s += 1) if (spans[s].distance > spans[best].distance) best = s;
    const span = spans[best];
    if (span.distance <= toleranceM) break;
    spans.splice(best, 1);
    kept.push(span.index);
    push(span.a, span.index);
    push(span.index, span.b);
  }
  return kept.sort((a, b) => a - b);
}

/** Cumulative distance along the points, in metres. */
export function cumulative(points: readonly LonLat[]): Float64Array {
  const out = new Float64Array(points.length);
  for (let i = 1; i < points.length; i += 1) out[i] = out[i - 1] + haversineM(points[i - 1], points[i]);
  return out;
}

/** The point `at` metres along the line. */
export function pointAlong(points: readonly LonLat[], along: Float64Array, at: number): LonLat {
  let lo = 0;
  let hi = points.length - 1;
  if (at <= 0) return points[0];
  if (at >= along[hi]) return points[hi];
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (along[mid] <= at) lo = mid;
    else hi = mid;
  }
  const span = along[hi] - along[lo];
  const t = span > 0 ? (at - along[lo]) / span : 0;
  return [points[lo][0] + t * (points[hi][0] - points[lo][0]), points[lo][1] + t * (points[hi][1] - points[lo][1])];
}

/**
 * Via points that make the router follow a track: the start, the end, and
 * one point halfway along each stretch between the track's most significant
 * corners. Halfway rather than on the corner itself: a point at a corner is an
 * intersection, where the router may snap it to the cross street and add a
 * spur, while a point mid-block pins the street the track took and leaves the
 * turns to the router. `mode: "corners"` keeps the corners instead (measured
 * against the midpoints in the PUBLIC-GPX report).
 */
export function viaPoints(track: readonly LonLat[], maxPoints: number, mode: "mid" | "corners" = "mid"): LonLat[] {
  if (track.length < 2 || maxPoints < 2) return track.slice(0, Math.min(track.length, maxPoints));
  if (mode === "corners") return significantIndexes(track, maxPoints).map((i) => track[i]);
  if (maxPoints < 3) return [track[0], track[track.length - 1]];
  // maxPoints - 2 midpoints are one per stretch between maxPoints - 1 corners.
  const corners = significantIndexes(track, maxPoints - 1);
  const along = cumulative(track);
  const out: LonLat[] = [track[0]];
  for (let k = 1; k < corners.length; k += 1) {
    out.push(pointAlong(track, along, (along[corners[k - 1]] + along[corners[k]]) / 2));
  }
  out.push(track[track.length - 1]);
  return out;
}

/** Points every `stepM` metres along the line, ends included. */
export function resample(points: readonly LonLat[], stepM: number): LonLat[] {
  if (points.length < 2) return [...points];
  const along = cumulative(points);
  const total = along[along.length - 1];
  const count = Math.max(1, Math.ceil(total / stepM));
  const out: LonLat[] = [];
  for (let k = 0; k <= count; k += 1) out.push(pointAlong(points, along, (total * k) / count));
  return out;
}

/**
 * Distance from each probe to the nearest point of `line`, on a grid of the
 * line's segments so a 20,000-point track against a long route is not a
 * product of the two. Probes farther than `capM` report capM.
 */
export function distancesToLine(probes: readonly LonLat[], line: readonly LonLat[], capM = 200): Float64Array {
  const out = new Float64Array(probes.length).fill(capM);
  if (line.length === 0) return out;
  const plane = planeFor(line);
  const cell = capM;
  const grid = new Map<string, number[]>();
  const lx = line.map((p) => plane.x(p));
  const ly = line.map((p) => plane.y(p));
  const segments = Math.max(1, line.length - 1);
  for (let s = 0; s < segments; s += 1) {
    const e = Math.min(s + 1, line.length - 1);
    const x0 = Math.floor(Math.min(lx[s], lx[e]) / cell);
    const x1 = Math.floor(Math.max(lx[s], lx[e]) / cell);
    const y0 = Math.floor(Math.min(ly[s], ly[e]) / cell);
    const y1 = Math.floor(Math.max(ly[s], ly[e]) / cell);
    for (let gx = x0; gx <= x1; gx += 1) {
      for (let gy = y0; gy <= y1; gy += 1) {
        const key = `${gx},${gy}`;
        const list = grid.get(key);
        if (list) list.push(s);
        else grid.set(key, [s]);
      }
    }
  }
  for (let i = 0; i < probes.length; i += 1) {
    const px = plane.x(probes[i]);
    const py = plane.y(probes[i]);
    const gx = Math.floor(px / cell);
    const gy = Math.floor(py / cell);
    let best = capM;
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        const list = grid.get(`${gx + dx},${gy + dy}`);
        if (!list) continue;
        for (const s of list) {
          const e = Math.min(s + 1, line.length - 1);
          const d = segmentDistance(px, py, lx[s], ly[s], lx[e], ly[e]);
          if (d < best) best = d;
        }
      }
    }
    out[i] = best;
  }
  return out;
}

/** Off-route stretches shorter than this many 10 m probes are left alone. */
const MIN_RUN_PROBES = 3;

/**
 * The via points with up to `add` more, one in the middle of each of the
 * longest stretches of the track that the routed line misses by more than
 * `withinM`, each inserted in its place along the track. Where the router
 * went its own way is where a point is needed, which geometry alone cannot
 * see: a track that follows a trail beside a road looks straight either way.
 * Returns the vias unchanged when nothing is missed.
 */
export function refineVias(
  track: readonly LonLat[],
  vias: readonly LonLat[],
  route: readonly LonLat[],
  add: number,
  withinM = FIDELITY_WITHIN_M,
): LonLat[] {
  if (add <= 0 || vias.length < 2 || track.length < 2) return [...vias];
  const probes = resample(track, FIDELITY_STEP_M);
  const off = distancesToLine(probes, route, withinM * 2);
  const runs: Array<[number, number]> = [];
  let start = -1;
  for (let i = 0; i <= off.length; i += 1) {
    const missed = i < off.length && off[i] > withinM;
    if (missed && start < 0) start = i;
    if (!missed && start >= 0) {
      if (i - start >= MIN_RUN_PROBES) runs.push([start, i - 1]);
      start = -1;
    }
  }
  if (!runs.length) return [...vias];
  runs.sort((a, b) => b[1] - b[0] - (a[1] - a[0]) || a[0] - b[0]);
  // Each via's place along the track: the nearest probe at or after the
  // previous via's, so an out-and-back's two passes are told apart.
  const plane = planeFor(probes);
  const px = probes.map((p) => plane.x(p));
  const py = probes.map((p) => plane.y(p));
  const places: number[] = [];
  let from = 0;
  vias.forEach((v, k) => {
    if (k === 0) {
      places.push(0);
      return;
    }
    if (k === vias.length - 1) {
      places.push(probes.length - 1);
      return;
    }
    const vx = plane.x(v);
    const vy = plane.y(v);
    let best = from;
    let bestD = Number.POSITIVE_INFINITY;
    for (let i = from; i < probes.length; i += 1) {
      const d = (px[i] - vx) ** 2 + (py[i] - vy) ** 2;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    places.push(best);
    from = best;
  });
  const tagged = vias.map((p, k) => ({ p, at: places[k], order: k }));
  for (const [a, b] of runs.slice(0, add)) {
    const middle = (a + b) >> 1;
    tagged.push({ p: probes[middle], at: middle, order: vias.length });
  }
  tagged.sort((x, y) => x.at - y.at || x.order - y.order);
  // The start and end stay the ends.
  const first = tagged.findIndex((t) => t.order === 0);
  const [head] = tagged.splice(first, 1);
  const last = tagged.findIndex((t) => t.order === vias.length - 1);
  const [tail] = tagged.splice(last, 1);
  return [head.p, ...tagged.map((t) => t.p), tail.p];
}

export interface Fidelity {
  /** Share of the track, by length, within `withinM` of the route. */
  trackCovered: number;
  /** Share of the route, by length, within `withinM` of the track: low when the route adds spurs or detours. */
  routeOnTrack: number;
  /** Route length over track length. */
  lengthRatio: number;
}

export const FIDELITY_WITHIN_M = 30;
const FIDELITY_STEP_M = 10;

/** How closely a routed line reproduces a track, both ways. */
export function fidelity(track: readonly LonLat[], route: readonly LonLat[], withinM = FIDELITY_WITHIN_M): Fidelity {
  const share = (from: readonly LonLat[], to: readonly LonLat[]) => {
    const probes = resample(from, FIDELITY_STEP_M);
    if (!probes.length || to.length === 0) return 0;
    const d = distancesToLine(probes, to, Math.max(withinM * 2, 60));
    let inside = 0;
    for (const v of d) if (v <= withinM) inside += 1;
    return inside / probes.length;
  };
  const trackM = cumulative(track).at(-1) ?? 0;
  const routeM = cumulative(route).at(-1) ?? 0;
  return {
    trackCovered: share(track, route),
    routeOnTrack: share(route, track),
    lengthRatio: trackM > 0 ? routeM / trackM : 0,
  };
}
