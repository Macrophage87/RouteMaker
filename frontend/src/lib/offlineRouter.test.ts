// The way back found on the phone with no signal (lib/offlineRouter.ts). Synthetic networks only, never a ride.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import {
  CORRIDOR_GRAPH_VERSION,
  EDGE_FIELDS,
  EDGE_ONEWAY,
  GRAPH_DEG,
  movementFor,
  offlineWayBack,
  readableGraph,
  type CorridorGraph,
  type OfflineWeights,
} from "./offlineRouter.ts";

const LAT = 38.9;
const LON = -77.0;
const M_LAT = 1 / 111_195;
const M_LON = 1 / (111_195 * Math.cos((LAT * Math.PI) / 180));
const at = (eastM: number, northM: number): LonLat => [LON + eastM * M_LON, LAT + northM * M_LAT];

/** Weights like a calm ride's: LTS 3 five times its time, LTS 4 twenty (index = level x 2). */
const CALM: OfflineWeights = { speedMps: 5, unpavedSpeedFactor: 0.8, walkMps: 1.3, levelFactor: [1, 1, 1, 1, 1.1, 1.5, 5, 8, 20, 30, 40] };

/**
 * A grid of streets 200 m apart, `cols` x `rows` nodes, all LTS 1 (level 2) unless `level` says otherwise for an
 * edge "from-to". Names: east-west streets "Row N", north-south "Col N".
 */
function grid(cols: number, rows: number, level: (from: number, to: number) => number = () => 2, flags: (from: number, to: number) => number = () => 0): CorridorGraph {
  const nodes: number[] = [];
  const id = (c: number, r: number) => r * cols + c;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const p = at(c * 200, r * 200);
    nodes.push(Math.round(p[0] / GRAPH_DEG), Math.round(p[1] / GRAPH_DEG));
  }
  const names: string[] = [];
  const name = (n: string) => (names.includes(n) ? names.indexOf(n) : names.push(n) - 1);
  const edges: number[] = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    if (c + 1 < cols) edges.push(id(c, r), id(c + 1, r), 200, level(id(c, r), id(c + 1, r)), flags(id(c, r), id(c + 1, r)), name(`Row ${r}`));
    if (r + 1 < rows) edges.push(id(c, r), id(c, r + 1), 200, level(id(c, r), id(c, r + 1)), flags(id(c, r), id(c, r + 1)), name(`Col ${c}`));
  }
  return { v: CORRIDOR_GRAPH_VERSION, nodes, edges, names };
}

// The planned line runs along Row 0, east, 0 to 1,000 m.
const PLANNED: LonLat[] = [at(0, 0), at(1000, 0)];

test("a network of another version or shape is not read", () => {
  assert.equal(readableGraph(grid(2, 2)), true);
  assert.equal(readableGraph({ ...grid(2, 2), v: 99 }), false);
  assert.equal(readableGraph({ ...grid(2, 2), edges: [1, 2, 3] }), false);
  assert.equal(readableGraph(null), false);
});

test("off the route two blocks north, the way back turns and rejoins the planned line ahead", () => {
  const g = grid(6, 4);
  // On Col 1, 400 m north of the line, the rider's progress 200 m.
  const way = offlineWayBack(g, CALM, at(200, 390), PLANNED, 200);
  assert.ok(way);
  assert.ok(way.joinAtM >= 300, `joins ahead, at ${way.joinAtM}`);
  assert.ok(way.distanceM < 1200, `short, ${way.distanceM}`);
  const end = way.line[way.line.length - 1];
  assert.ok(Math.abs(end[1] - LAT) < 1e-5, "ends on the planned line");
  assert.ok(way.turns.length >= 1);
  assert.equal(way.startStreet, "Col 1");
});

test("the way back avoids a stressful street where a calm one is near", () => {
  // Col 1 and Col 2 between rows 0 and 2 are LTS 4 (level 8); Col 3 is calm.
  const busy = new Set(["1-7", "7-13", "2-8", "8-14"]);
  const g = grid(6, 4, (a, b) => (busy.has(`${a}-${b}`) ? 8 : 2));
  const way = offlineWayBack(g, CALM, at(200, 400), PLANNED, 0);
  assert.ok(way);
  assert.equal(way.worstLevel2, 2, "rides only LTS 1");
  // With a ride that does not mind traffic, the busy street is straight down.
  const any: OfflineWeights = { ...CALM, levelFactor: CALM.levelFactor.map(() => 1) };
  const direct = offlineWayBack(g, any, at(200, 400), PLANNED, 0);
  assert.ok(direct);
  assert.ok(direct.distanceM < way.distanceM);
});

test("a one-way street is not ridden against its direction", () => {
  // Col 1 from row 2 down to row 0 is one-way north only (from its lower node to its upper).
  const g = grid(4, 3, () => 2, (a, b) => (b - a === 4 && a % 4 === 1 ? EDGE_ONEWAY : 0));
  const way = offlineWayBack(g, CALM, at(200, 400), PLANNED, 0);
  assert.ok(way);
  // Rides Col 0 or Col 2 down, never south on Col 1.
  const usesCol1Down = way.line.some((p, i) => i > 0 && Math.abs(p[0] - at(200, 0)[0]) < 1e-6 && way.line[i - 1][1] - p[1] > 1e-5 && Math.abs(way.line[i - 1][0] - p[0]) < 1e-6);
  assert.equal(usesCol1Down, false);
});

test("too far from any road, or past the end of the line, there is no way back", () => {
  const g = grid(3, 3);
  assert.equal(offlineWayBack(g, CALM, at(200, 2000), PLANNED, 0), null);
  assert.equal(offlineWayBack(g, CALM, at(200, 200), PLANNED, 950), null);
});

test("turns are named by their angle", () => {
  assert.equal(movementFor(10), null);
  assert.equal(movementFor(45), "bear_right");
  assert.equal(movementFor(-45), "bear_left");
  assert.equal(movementFor(90), "right");
  assert.equal(movementFor(-90), "left");
  assert.equal(movementFor(175), "uturn");
});

test("every edge in the test network has EDGE_FIELDS values", () => {
  assert.equal(grid(3, 3).edges.length % EDGE_FIELDS, 0);
});

test("a rider on a junction hears no made-up first turn, and bad input finds nothing", () => {
  const g = grid(6, 4);
  // Exactly on the node at Col 1, Row 2.
  const way = offlineWayBack(g, CALM, at(200, 400), PLANNED, 0);
  assert.ok(way);
  assert.ok(way.turns.every((turn) => turn.atM >= 10));
  assert.equal(offlineWayBack(g, CALM, at(200, 400), PLANNED, Number.NaN), null);
  assert.equal(offlineWayBack(g, CALM, [Number.NaN, LAT], PLANNED, 0), null);
});
