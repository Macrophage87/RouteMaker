/**
 * Off-grid riding (Stephen, 2026-11-12: "the one mile would be a default, with a whole region pack an optional
 * download"): a way back to the planned line found on the phone, with no signal, over the road network around the
 * route. The network (`CorridorGraph`) comes from the server with the route's kept map; this file only reads it.
 *
 * It is an approximation of the server's routing, and Ride says so ("Offline way back"): each stretch costs its riding
 * time times the ride's own weight for its stress level (`OfflineWeights`, sent by the server for the ride's type and
 * dials, so the levels are priced as the server's graded stress prices them), and nothing else. No junction pricing,
 * signal waits, turn prices, live closures or alternatives. Within a mile of the line those matter far less than
 * having turns at all.
 *
 * Privacy: the network is map data for an area, kept as the corridor's tiles are (lib/corridor.ts). Nothing here
 * keeps or sends a position.
 */
import { haversineM, type LonLat } from "./geo.ts";
import type { TurnMovement } from "./navigate.ts";

/** The network's format version this file reads. */
export const CORRIDOR_GRAPH_VERSION = 1;

/** Coordinates are whole numbers of this many degrees (about 4 in at DC's latitude). */
export const GRAPH_DEG = 1e-6;

/** Values in each edge's group of `EDGE_FIELDS` in `CorridorGraph.edges`. */
export const EDGE_FIELDS = 6;

/** Edge flags. */
export const EDGE_ONEWAY = 1; // ridden from its first node to its second only
export const EDGE_WALK = 2; // walk the bike (steps, a dismount path)
export const EDGE_UNPAVED = 4;

/**
 * The road network around a route, as the server sends it (JSON).
 * - `nodes`: [lon, lat] pairs in whole `GRAPH_DEG`, flat: node i is nodes[2i], nodes[2i+1].
 * - `edges`: groups of EDGE_FIELDS: from node, to node, length in metres, stress level times 2 (2 = LTS 1, 7 = 3.5,
 *   9 = 4.5, 10 = Avoid), flags (EDGE_*), name index into `names` (-1 for none).
 * - `shapes`: per edge, the points between its two nodes, flat whole `GRAPH_DEG` [lon, lat] pairs, or 0 for none.
 */
export interface CorridorGraph {
  v: number;
  nodes: number[];
  edges: number[];
  shapes?: (number[] | 0)[];
  names: string[];
}

/**
 * The ride's prices (the server works them out from the ride type and dials): riding speed on a paved stretch, the
 * factor on an unpaved one's speed, walking speed, and by stress level times 2 (index 2 to 10) the multiple of a
 * stretch's time it costs (1 adds nothing; graded stress makes LTS 3 and 4 several times their time).
 */
export interface OfflineWeights {
  speedMps: number;
  unpavedSpeedFactor: number;
  walkMps: number;
  levelFactor: number[];
}

/** How far the rider may be from a road in the network for a way back to start there (about 500 ft). Our default, unmeasured. */
export const START_SNAP_M = 150;
/** A node this close to the planned line ahead is on it: a way back may end there (about 65 ft). Our default, unmeasured. */
export const JOIN_SNAP_M = 20;
/** The way back joins the line at least this far past the rider's progress, as the server's way back does (lib/rejoin.ts REJOIN_AHEAD_M). */
export const JOIN_AHEAD_M = 100;
/**
 * A join further along the planned line is worth this share of the time it saves riding the line: under 1, so of two
 * ways back that cost the same less the line they skip, the one that rejoins sooner wins. Our default, unmeasured.
 */
export const JOIN_SAVED_SHARE = 0.8;
/** A change of direction at a junction this large or more is a turn said (degrees). Our default, unmeasured. */
export const TURN_DEG = 30;
/** Above this a turn is left or right, below it bear left or right; above UTURN_DEG a U-turn. Our defaults, unmeasured. */
export const SHARP_DEG = 60;
export const UTURN_DEG = 160;

/** A turn on the offline way back: how far along it, which way, and onto what (null: unnamed). */
export interface OfflineTurn {
  atM: number;
  movement: TurnMovement;
  street: string | null;
}

/** The way back found offline: its line, length, turns, the street it starts on, and where it joins the planned line. */
export interface OfflineWayBack {
  line: LonLat[];
  distanceM: number;
  /** Seconds at the ride's speeds, before the stress weights. */
  durationS: number;
  turns: OfflineTurn[];
  startStreet: string | null;
  /** The way to set off, degrees from north, over its first FIRST_TURN_M or more: Ride says "Head east on …". */
  startBearingDeg: number;
  /** Along the planned line, the metres at which the way back meets it. */
  joinAtM: number;
  /** The worst stress level ridden (times 2, as the network's). */
  worstLevel2: number;
}

interface Adjacent {
  /** For each node, the edges leaving it: edge index * 2 + 0 when ridden forward, + 1 when backward. */
  out: number[][];
}

const adjacency = new WeakMap<CorridorGraph, Adjacent>();

function adjacent(g: CorridorGraph): Adjacent {
  const known = adjacency.get(g);
  if (known) return known;
  const out: number[][] = Array.from({ length: g.nodes.length / 2 }, () => []);
  for (let e = 0; e < g.edges.length / EDGE_FIELDS; e++) {
    const at = e * EDGE_FIELDS;
    const from = g.edges[at];
    const to = g.edges[at + 1];
    out[from]?.push(e * 2);
    if (!(g.edges[at + 4] & EDGE_ONEWAY)) out[to]?.push(e * 2 + 1);
  }
  const made = { out };
  adjacency.set(g, made);
  return made;
}

/** Whether a network is one this file reads. */
export function readableGraph(g: unknown): g is CorridorGraph {
  const x = g as CorridorGraph | null;
  return (
    !!x &&
    x.v === CORRIDOR_GRAPH_VERSION &&
    Array.isArray(x.nodes) &&
    Array.isArray(x.edges) &&
    Array.isArray(x.names) &&
    x.nodes.length % 2 === 0 &&
    x.edges.length % EDGE_FIELDS === 0
  );
}

function nodeAt(g: CorridorGraph, n: number): LonLat {
  return [g.nodes[n * 2] * GRAPH_DEG, g.nodes[n * 2 + 1] * GRAPH_DEG];
}

/** An edge's points from its first node to its second. */
function edgePoints(g: CorridorGraph, e: number): LonLat[] {
  const at = e * EDGE_FIELDS;
  const pts: LonLat[] = [nodeAt(g, g.edges[at])];
  const shape = g.shapes?.[e];
  if (shape) for (let i = 0; i + 1 < shape.length; i += 2) pts.push([shape[i] * GRAPH_DEG, shape[i + 1] * GRAPH_DEG]);
  pts.push(nodeAt(g, g.edges[at + 1]));
  return pts;
}

/** Seconds to ride (or walk) an edge, and that times its level's weight: the search's cost. */
function edgeCost(g: CorridorGraph, w: OfflineWeights, e: number, fraction = 1): { s: number; cost: number } {
  const at = e * EDGE_FIELDS;
  const lengthM = g.edges[at + 2] * fraction;
  const level2 = g.edges[at + 3];
  const flags = g.edges[at + 4];
  const speed = flags & EDGE_WALK ? w.walkMps : flags & EDGE_UNPAVED ? w.speedMps * w.unpavedSpeedFactor : w.speedMps;
  const s = lengthM / Math.max(speed, 0.1);
  const factor = w.levelFactor[level2] ?? w.levelFactor[w.levelFactor.length - 1] ?? 1;
  return { s, cost: s * Math.max(factor, 1) };
}

/** Local metres east and north of `origin`, for nearest-point work over a few miles. */
function toXY(origin: LonLat, p: LonLat): [number, number] {
  const k = Math.cos((origin[1] * Math.PI) / 180);
  return [(p[0] - origin[0]) * 111_195 * k, (p[1] - origin[1]) * 111_195];
}

/** The nearest point of a polyline to `p`: its distance, and its distance along the polyline. */
function nearestOn(points: readonly LonLat[], p: LonLat): { distM: number; alongM: number; totalM: number } {
  let best = { distM: Infinity, alongM: 0 };
  let along = 0;
  for (let i = 0; i + 1 < points.length; i++) {
    const [ax, ay] = toXY(p, points[i]);
    const [bx, by] = toXY(p, points[i + 1]);
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    const x = ax + t * dx;
    const y = ay + t * dy;
    const d = Math.hypot(x, y);
    const segM = Math.sqrt(len2);
    if (d < best.distM) best = { distM: d, alongM: along + t * segM };
    along += segM;
  }
  return { ...best, totalM: along };
}

/** The planned line's cumulative metres at each point. */
function measure(line: readonly LonLat[]): number[] {
  const at = [0];
  for (let i = 1; i < line.length; i++) at.push(at[i - 1] + haversineM(line[i - 1], line[i]));
  return at;
}

/** Where a node meets the planned line at or past `fromM`, within JOIN_SNAP_M, or null. */
function joinAlong(line: readonly LonLat[], measured: number[], fromM: number, p: LonLat): number | null {
  let best: { d: number; at: number } | null = null;
  for (let i = 0; i + 1 < line.length; i++) {
    if (measured[i + 1] < fromM) continue;
    const near = nearestOn([line[i], line[i + 1]], p);
    const at = measured[i] + near.alongM;
    if (at < fromM || near.distM > JOIN_SNAP_M) continue;
    if (!best || near.distM < best.d) best = { d: near.distM, at };
  }
  return best ? best.at : null;
}

/** A small binary heap of [cost, node]. */
class Heap {
  private items: [number, number][] = [];
  get size(): number {
    return this.items.length;
  }
  push(cost: number, node: number): void {
    const a = this.items;
    a.push([cost, node]);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop(): [number, number] | undefined {
    const a = this.items;
    const top = a[0];
    const last = a.pop();
    if (a.length && last) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = i * 2 + 1;
        const r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

function bearing(a: LonLat, b: LonLat): number {
  const [x, y] = toXY(a, b);
  return ((Math.atan2(x, y) * 180) / Math.PI + 360) % 360;
}

/** The movement for a change of direction (degrees, positive to the right), or null where it is not a turn said. */
export function movementFor(changeDeg: number): TurnMovement | null {
  const a = Math.abs(changeDeg);
  if (a < TURN_DEG) return null;
  if (a >= UTURN_DEG) return "uturn";
  if (a < SHARP_DEG) return changeDeg > 0 ? "bear_right" : "bear_left";
  return changeDeg > 0 ? "right" : "left";
}

/**
 * The way back to the planned `line` from `rider`, over the network: the cheapest at the ride's prices to any node on
 * the line at least JOIN_AHEAD_M past `progressM`, where a join further on is worth the planned riding it saves (at
 * the ride's paved speed and LTS 1). Null when the rider is not near the network or no join is reachable.
 */
export function offlineWayBack(
  g: CorridorGraph,
  w: OfflineWeights,
  rider: LonLat,
  line: readonly LonLat[],
  progressM: number,
): OfflineWayBack | null {
  if (!readableGraph(g) || line.length < 2 || !Number.isFinite(progressM) || !rider.every(Number.isFinite)) return null;
  const edgeCount = g.edges.length / EDGE_FIELDS;
  const nodeCount = g.nodes.length / 2;
  // The start: the nearest point of the nearest edge, its cost to each end by the share of the edge left.
  let start: { e: number; distM: number; fraction: number } | null = null;
  for (let e = 0; e < edgeCount; e++) {
    const pts = edgePoints(g, e);
    const near = nearestOn(pts, rider);
    if (near.distM <= START_SNAP_M && (!start || near.distM < start.distM)) {
      start = { e, distM: near.distM, fraction: near.totalM > 0 ? near.alongM / near.totalM : 0 };
    }
  }
  if (!start) return null;
  const measured = measure(line);
  const fromM = progressM + JOIN_AHEAD_M;
  const lineEndM = measured[measured.length - 1];
  if (fromM > lineEndM) return null;
  // Each node on the line ahead, and where.
  const joinAt = new Map<number, number>();
  for (let n = 0; n < nodeCount; n++) {
    const at = joinAlong(line, measured, fromM, nodeAt(g, n));
    if (at !== null) joinAt.set(n, at);
  }
  if (!joinAt.size) return null;
  // A join further along saves riding the planned line there: worth JOIN_SAVED_SHARE of its time at the paved speed.
  const savedPerM = JOIN_SAVED_SHARE / Math.max(w.speedMps, 0.1);
  const cost = new Float64Array(nodeCount).fill(Infinity);
  const secs = new Float64Array(nodeCount).fill(Infinity);
  const via = new Int32Array(nodeCount).fill(-1); // directed edge into the node (edge * 2 + backward)
  const heap = new Heap();
  const se = start.e * EDGE_FIELDS;
  const a = g.edges[se];
  const b = g.edges[se + 1];
  const oneway = !!(g.edges[se + 4] & EDGE_ONEWAY);
  // Forward to b: the share past the rider. Back to a: the share before, unless one-way.
  const toB = edgeCost(g, w, start.e, 1 - start.fraction);
  cost[b] = toB.cost;
  secs[b] = toB.s;
  heap.push(cost[b], b);
  if (!oneway) {
    const toA = edgeCost(g, w, start.e, start.fraction);
    if (toA.cost < cost[a]) {
      cost[a] = toA.cost;
      secs[a] = toA.s;
      heap.push(cost[a], a);
    }
  }
  const { out } = adjacent(g);
  while (heap.size) {
    const [c, n] = heap.pop() as [number, number];
    if (c > cost[n]) continue;
    for (const d of out[n] ?? []) {
      const e = d >> 1;
      const back = d & 1;
      const to = g.edges[e * EDGE_FIELDS + (back ? 0 : 1)];
      const step = edgeCost(g, w, e);
      const next = c + step.cost;
      if (next < cost[to]) {
        cost[to] = next;
        secs[to] = secs[n] + step.s;
        via[to] = d;
        heap.push(next, to);
      }
    }
  }
  // The best join: cost there less the planned riding it saves.
  let goal = -1;
  let goalScore = Infinity;
  for (const [n, at] of joinAt) {
    if (!Number.isFinite(cost[n])) continue;
    const score = cost[n] - at * savedPerM;
    if (score < goalScore) {
      goalScore = score;
      goal = n;
    }
  }
  if (goal < 0) return null;
  // Back from the goal to the start edge's end it was reached from.
  const legs: { e: number; back: boolean }[] = [];
  let n = goal;
  while (via[n] >= 0) {
    const d = via[n];
    const e = d >> 1;
    const back = !!(d & 1);
    legs.unshift({ e, back });
    n = g.edges[e * EDGE_FIELDS + (back ? 1 : 0)];
  }
  // The first stretch: from the rider along the start edge to the node the search set out from.
  const startPts = edgePoints(g, start.e);
  const startNear = nearestOn(startPts, rider);
  const split = splitAt(startPts, startNear.alongM);
  const firstPts = n === b ? split.after : split.before.slice().reverse();
  const line2: LonLat[] = [rider, ...firstPts];
  const pieces: { pts: LonLat[]; e: number }[] = [{ pts: line2.slice(), e: start.e }];
  for (const leg of legs) {
    const pts = edgePoints(g, leg.e);
    if (leg.back) pts.reverse();
    pieces.push({ pts, e: leg.e });
    line2.push(...pts.slice(1));
  }
  // Where the rider sets off: the first piece, or the edge after it where that piece is under FIRST_TURN_M (the rider
  // is on a junction, so its turn is the way they set off, not a turn said).
  const opening = pieces.length > 1 && pathM(pieces[0].pts) < FIRST_TURN_M ? pieces[1] : pieces[0];
  const openPts = distinct(opening === pieces[0] ? opening.pts : [...pieces[0].pts, ...opening.pts]);
  const startBearingDeg = bearing(openPts[0], openPts[Math.min(openPts.length - 1, 1)]);
  // Turns: at each node between two edges, where the street changes or the direction turns by TURN_DEG or more.
  const turns: OfflineTurn[] = [];
  let atM = pathM(pieces[0].pts);
  let worst = g.edges[start.e * EDGE_FIELDS + 3];
  for (let i = 1; i < pieces.length; i++) {
    const prev = pieces[i - 1];
    const cur = pieces[i];
    worst = Math.max(worst, g.edges[cur.e * EDGE_FIELDS + 3]);
    // No turn said within FIRST_TURN_M of the rider: there the way in is the rider's own, not the network's (a rider
    // standing on a junction would hear a turn the start edge's direction made up).
    if (atM < FIRST_TURN_M) {
      atM += pathM(cur.pts);
      continue;
    }
    const inPts = distinct(prev.pts);
    const outPts = distinct(cur.pts);
    const p0 = inPts[Math.max(0, inPts.length - 2)];
    const p1 = inPts[inPts.length - 1];
    const q1 = outPts[Math.min(1, outPts.length - 1)];
    let change = bearing(p1, q1) - bearing(p0, p1);
    if (change > 180) change -= 360;
    if (change < -180) change += 360;
    const prevName = nameOf(g, prev.e);
    const curName = nameOf(g, cur.e);
    const movement = movementFor(change) ?? (prevName !== curName && curName ? (change >= 0 ? "bear_right" : "bear_left") : null);
    if (movement) turns.push({ atM, movement, street: curName });
    atM += pathM(cur.pts);
  }
  return {
    line: line2,
    distanceM: pathM(line2),
    durationS: secs[goal] + startNear.distM / Math.max(w.speedMps, 0.1),
    turns,
    startStreet: nameOf(g, opening.e),
    startBearingDeg,
    joinAtM: joinAt.get(goal) as number,
    worstLevel2: worst,
  };
}

/** Under this far from the rider, a junction's turn is not said (about 30 ft). Our default, unmeasured. */
export const FIRST_TURN_M = 10;

/** The points with any within half a metre of the one before left out, so a bearing is never taken over nothing. */
function distinct(points: readonly LonLat[]): LonLat[] {
  const out: LonLat[] = [];
  for (const p of points) if (!out.length || haversineM(out[out.length - 1], p) >= 0.5) out.push(p);
  return out.length ? out : points.slice(0, 1);
}

function nameOf(g: CorridorGraph, e: number): string | null {
  const i = g.edges[e * EDGE_FIELDS + 5];
  return i >= 0 ? (g.names[i] ?? null) : null;
}

function pathM(points: readonly LonLat[]): number {
  let m = 0;
  for (let i = 1; i < points.length; i++) m += haversineM(points[i - 1], points[i]);
  return m;
}

/** A polyline split at `atM` along it: the points up to the split (ending there), and from it on (starting there). */
function splitAt(points: readonly LonLat[], atM: number): { before: LonLat[]; after: LonLat[] } {
  let along = 0;
  for (let i = 0; i + 1 < points.length; i++) {
    const seg = haversineM(points[i], points[i + 1]);
    if (along + seg >= atM) {
      const t = seg > 0 ? (atM - along) / seg : 0;
      const p: LonLat = [points[i][0] + t * (points[i + 1][0] - points[i][0]), points[i][1] + t * (points[i + 1][1] - points[i][1])];
      return { before: [...points.slice(0, i + 1), p], after: [p, ...points.slice(i + 1)] };
    }
    along += seg;
  }
  const last = points[points.length - 1];
  return { before: points.slice(), after: [last] };
}
