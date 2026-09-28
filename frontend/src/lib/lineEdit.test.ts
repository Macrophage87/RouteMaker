// Dragging the drawn route: which leg was grabbed, and where the new via goes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_POINTS, addPoint, type LonLat } from "./geo.ts";
import {
  canDragLine,
  dragPreview,
  dropStillValid,
  guessLegEnds,
  insertIntoLeg,
  legEnds,
  legOfSegment,
  nearestOnPath,
  validLegEnds,
} from "./lineEdit.ts";

// A line east along a parallel, then north: an L.
const L: LonLat[] = [
  [-77.05, 38.9],
  [-77.04, 38.9],
  [-77.03, 38.9],
  [-77.03, 38.91],
  [-77.03, 38.92],
];

test("the nearest point on a path lies on the segment under the cursor", () => {
  const near = nearestOnPath(L, [-77.035, 38.9004]);
  assert.ok(near);
  assert.equal(near.segment, 1);
  assert.ok(Math.abs(near.point[0] - -77.035) < 1e-9);
  assert.ok(Math.abs(near.point[1] - 38.9) < 1e-9);
  assert.ok(near.t > 0.49 && near.t < 0.51);
});

test("the nearest point is found on a later segment when that one is closer", () => {
  const near = nearestOnPath(L, [-77.0296, 38.915]);
  assert.ok(near);
  assert.equal(near.segment, 3);
  assert.ok(Math.abs(near.point[0] - -77.03) < 1e-9);
  assert.ok(Math.abs(near.point[1] - 38.915) < 1e-9);
});

test("past a path's end the nearest point is the end itself, not beyond it", () => {
  const near = nearestOnPath(L, [-77.06, 38.899]);
  assert.ok(near);
  assert.equal(near.segment, 0);
  assert.equal(near.t, 0);
  assert.ok(Math.hypot(near.point[0] - L[0][0], near.point[1] - L[0][1]) < 1e-9);
  const far = nearestOnPath(L, [-77.029, 38.93]);
  assert.ok(far);
  assert.equal(far.segment, 3);
  assert.equal(far.t, 1);
  assert.ok(Math.hypot(far.point[0] - L[4][0], far.point[1] - L[4][1]) < 1e-9);
});

test("longitude is scaled by latitude, so the nearest segment is the nearest on the ground", () => {
  // A north-south segment 0.003 degrees of longitude west (about 260 m at
  // 38.9 N) and an east-west one 0.0025 degrees of latitude north (about
  // 280 m). Unscaled degrees would call the second one nearer.
  const path: LonLat[] = [
    [-77.003, 38.89],
    [-77.003, 38.91],
    [-76.9, 38.95],
    [-76.9, 38.9025],
    [-77.1, 38.9025],
  ];
  const near = nearestOnPath(path, [-77.0, 38.9]);
  assert.ok(near);
  assert.equal(near.segment, 0);
});

test("a segment of no length (a repeated vertex) still has its nearest point", () => {
  const near = nearestOnPath([L[1], L[1]], [-77.035, 38.9004]);
  assert.ok(near);
  assert.equal(near.segment, 0);
  assert.ok(Math.hypot(near.point[0] - L[1][0], near.point[1] - L[1][1]) < 1e-9);
});

test("a point exactly as near two segments goes with the first along the line", () => {
  // Out and straight back along the same line, on the equator, where the
  // arithmetic is exact: the point is as near the way out as the way back.
  const path: LonLat[] = [
    [0, 0],
    [2, 0],
    [0, 0],
  ];
  const near = nearestOnPath(path, [1, 1]);
  assert.ok(near);
  assert.equal(near.segment, 0);
});

test("a path of one vertex, or none, has nothing to grab", () => {
  assert.equal(nearestOnPath([], [-77, 38.9]), null);
  assert.equal(nearestOnPath([L[0]], [-77, 38.9]), null);
});

test("a segment belongs to the leg whose stretch of the line holds it", () => {
  const ends = [2, 5, 9];
  assert.equal(legOfSegment(ends, 0), 0);
  assert.equal(legOfSegment(ends, 1), 0);
  assert.equal(legOfSegment(ends, 2), 1);
  assert.equal(legOfSegment(ends, 4), 1);
  assert.equal(legOfSegment(ends, 5), 2);
  assert.equal(legOfSegment(ends, 8), 2);
});

test("a leg of no length (two points on one spot) is never the one grabbed", () => {
  assert.equal(legOfSegment([3, 3, 7], 3), 2);
  assert.equal(legOfSegment([3, 3, 7], 2), 0);
});

test("a segment index past the line's end is the last leg's", () => {
  assert.equal(legOfSegment([2, 5], 9), 1);
});

test("the API's leg ends are used only when they describe this line and these points", () => {
  assert.equal(validLegEnds([2, 4], 5, 3), true);
  assert.equal(validLegEnds([2, 2, 4], 5, 4), true);
  assert.equal(validLegEnds(undefined, 5, 3), false);
  assert.equal(validLegEnds("2,4", 5, 3), false);
  assert.equal(validLegEnds([4], 5, 3), false, "one end for two legs");
  assert.equal(validLegEnds([1, 2, 4], 5, 3), false, "three ends for two legs");
  assert.equal(validLegEnds([2, 3], 5, 3), false, "the last leg must end at the last vertex");
  assert.equal(validLegEnds([3, 2, 4], 5, 4), false, "ends go forwards");
  assert.equal(validLegEnds([-1, 4], 5, 3), false);
  assert.equal(validLegEnds([1.5, 4], 5, 3), false);
  assert.equal(validLegEnds([2, 5], 5, 3), false, "past the last vertex");
});

test("without the API's leg ends, each via is matched to its nearest vertex, in order", () => {
  const points: LonLat[] = [L[0], [-77.0301, 38.9001], L[4]];
  assert.deepEqual(guessLegEnds(L, points), [2, 4]);
});

test("a route with no via has one leg, ending at the last vertex", () => {
  assert.deepEqual(guessLegEnds(L, [L[0], L[4]]), [4]);
});

test("a via the line passes twice is matched where the line first reaches it", () => {
  // Out to the east end and back along the same street: via 1 (the middle
  // vertex) is on the way out and on the way back.
  const path: LonLat[] = [L[0], L[1], L[2], L[1], L[0]];
  assert.deepEqual(guessLegEnds(path, [L[0], L[1], L[0]]), [1, 4]);
});

test("the guess keeps the vias in order when the line passes a later via first", () => {
  // Out along the parallel to the far end, back to the middle, then north.
  // Via 2 sits on the way out, but its leg comes after via 1's.
  const path: LonLat[] = [
    [-77.05, 38.9],
    [-77.04, 38.9],
    [-77.03, 38.9],
    [-77.04, 38.9001],
    [-77.04, 38.91],
  ];
  const points: LonLat[] = [path[0], path[2], [-77.04, 38.9], path[4]];
  const ends = guessLegEnds(path, points);
  assert.deepEqual(ends, [2, 3, 4]);
});

test("legEnds takes the API's when they fit and guesses otherwise", () => {
  const points: LonLat[] = [L[0], [-77.0301, 38.9001], L[4]];
  assert.deepEqual(legEnds(L, points, [1, 4]), [1, 4]);
  assert.deepEqual(legEnds(L, points, [1]), [2, 4]);
  assert.deepEqual(legEnds(L, points, undefined), [2, 4]);
});

test("a via dragged from a leg goes into that leg, between its two points", () => {
  const points: LonLat[] = [
    [-77.05, 38.9],
    [-77.0, 38.9],
    [-77.0, 38.95],
  ];
  const via: LonLat = [-77.02, 38.93];
  assert.deepEqual(insertIntoLeg(points, 0, via), [points[0], via, points[1], points[2]]);
  assert.deepEqual(insertIntoLeg(points, 1, via), [points[0], points[1], via, points[2]]);
});

test("the grabbed leg wins over the leg a click there would lengthen least", () => {
  // A click at `via` would go on leg 1 (addPoint's rule); a drag of leg 0 to
  // the same spot still goes on leg 0.
  const points: LonLat[] = [
    [-77.05, 38.9],
    [-77.0, 38.9],
    [-77.0, 38.95],
  ];
  const via: LonLat = [-77.005, 38.93];
  assert.equal(addPoint(points, via).indexOf(via), 2);
  assert.equal(insertIntoLeg(points, 0, via)?.indexOf(via), 1);
});

test("a full route takes no more vias, and a leg that is not there takes none", () => {
  const full: LonLat[] = Array.from({ length: MAX_POINTS }, (_, i) => [-77 + i * 0.001, 38.9]);
  assert.equal(insertIntoLeg(full, 3, [-77, 38.95]), null);
  const two: LonLat[] = [full[0], full[1]];
  assert.equal(insertIntoLeg(two, 1, [-77, 38.95]), null);
  assert.equal(insertIntoLeg(two, -1, [-77, 38.95]), null);
  assert.equal(insertIntoLeg([L[0], L[2], L[4]], 0.5, [-77, 38.95]), null, "a leg is a whole number");
  assert.equal(insertIntoLeg(full.slice(0, MAX_POINTS - 1), 0, [-77, 38.95])?.length, MAX_POINTS);
});

test("the preview runs from the grabbed leg's two points to the cursor", () => {
  const points: LonLat[] = [
    [-77.05, 38.9],
    [-77.0, 38.9],
    [-77.0, 38.95],
  ];
  const cursor: LonLat = [-77.02, 38.93];
  assert.deepEqual(dragPreview(points, 1, cursor), [
    [points[1], cursor],
    [cursor, points[2]],
  ]);
  assert.deepEqual(dragPreview(points, 0, cursor), [
    [points[0], cursor],
    [cursor, points[1]],
  ]);
});

test("the line can be dragged only when it is the showing, settled route of these points", () => {
  const ok = { routeShown: true, stale: false, routedIsCurrent: true, vertexCount: 5 };
  assert.equal(canDragLine(ok), true);
  assert.equal(canDragLine({ ...ok, routeShown: false }), false);
  assert.equal(canDragLine({ ...ok, stale: true }), false, "being planned again");
  assert.equal(canDragLine({ ...ok, routedIsCurrent: false }), false, "planned for an older list");
  assert.equal(canDragLine({ ...ok, vertexCount: 1 }), false, "no segment to grab");
  assert.equal(canDragLine({ ...ok, vertexCount: 2 }), true);
});

test("a drop is kept only while the points are the very list the line was planned for", () => {
  const points: LonLat[] = [L[0], L[4]];
  assert.equal(dropStillValid(points, points), true);
  assert.equal(dropStillValid(points, [...points]), false, "an equal list is a newer edit");
});
