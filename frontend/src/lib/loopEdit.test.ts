/** Dragging the line and Reverse in a loop (OWNER-DECISIONS 374). */
import assert from "node:assert/strict";
import test from "node:test";
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { dragPreview, insertIntoRide, legEnds, legPoints, validLegEnds } from "./lineEdit.ts";
import { canReverse, reverseKeepsStart, reversedPoints } from "./loop.ts";
import { insertedSaid } from "./pointText.ts";
import { pointName } from "./summary.ts";

const A: LonLat = [-77.0, 38.9];
const B: LonLat = [-76.98, 38.9];
const C: LonLat = [-76.98, 38.92];
const D: LonLat = [-77.0, 38.93];
const mid = (p: LonLat, q: LonLat): LonLat => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
// A loop's line as the API draws it: A to B to C and back to A, a vertex between each.
const LOOP_LINE: LonLat[] = [A, mid(A, B), B, mid(B, C), C, mid(C, A), A];
const LOOP_ENDS = [2, 4, 6];

test("legPoints: a loop's legs close on the start; a one-way ride or a round trip has no closing leg", () => {
  assert.deepEqual(legPoints([A, B, C], true), [A, B, C, A]);
  assert.deepEqual(legPoints([A, B], true), [A, B, A]);
  assert.deepEqual(legPoints([A, B, C], false), [A, B, C]);
  assert.deepEqual(legPoints([A, B, [-77.0001, 38.9001]], true), [A, B, [-77.0001, 38.9001]], "already ends on its start");
  assert.deepEqual(legPoints([A], true), [A]);
});

test("a loop's leg ends from the API fit its legs, so a drag is not left to a guess", () => {
  assert.equal(validLegEnds(LOOP_ENDS, LOOP_LINE.length, 3), false, "one more leg than the rider's points make");
  assert.equal(validLegEnds(LOOP_ENDS, LOOP_LINE.length, legPoints([A, B, C], true).length), true);
  assert.deepEqual(legEnds(LOOP_LINE, legPoints([A, B, C], true), LOOP_ENDS), LOOP_ENDS);
  // With the leg ends lost, the guess over the closed points still finds the closing leg.
  assert.deepEqual(legEnds(LOOP_LINE, legPoints([A, B, C], true), undefined), LOOP_ENDS);
});

test("a drag on a loop's closing leg appends the stop, as a click there does", () => {
  const P = mid(C, A);
  assert.deepEqual(insertIntoRide([A, B, C], 2, P, true), [A, B, C, P]);
  assert.deepEqual(insertIntoRide([A, B], 1, P, true), [A, B, P], "a start and one stop: the way back");
  assert.deepEqual(insertIntoRide([A, B, C], 0, P, true), [A, P, B, C]);
  assert.deepEqual(insertIntoRide([A, B, C], 1, P, true), [A, B, P, C]);
  assert.equal(insertIntoRide([A, B, C], 3, P, true), null, "no such leg");
  assert.equal(insertIntoRide([A, B, C], 2, P, false), null, "no closing leg off the loop");
  assert.equal(insertIntoRide([A, B, C], -1, P, true), null);
});

test("off the loop a drag inserts as before", () => {
  const P = mid(B, C);
  assert.deepEqual(insertIntoRide([A, B, C], 0, P, false), [A, P, B, C]);
  assert.deepEqual(insertIntoRide([A, B, C], 1, P, false), [A, B, P, C]);
});

test("the point cap holds on the closing leg", () => {
  const full: LonLat[] = Array.from({ length: MAX_POINTS }, (_, i) => [-77 + i / 1000, 38.9]);
  assert.equal(insertIntoRide(full, MAX_POINTS - 1, A, true), null);
  const room = full.slice(0, MAX_POINTS - 1);
  assert.equal(insertIntoRide(room, MAX_POINTS - 2, D, true)?.length, MAX_POINTS);
});

test("the preview, the new list and the announcement agree on every leg of a loop", () => {
  const points = [A, B, C];
  const legs = legPoints(points, true);
  const P = D;
  for (let leg = 0; leg < legs.length - 1; leg += 1) {
    const next = insertIntoRide(points, leg, P, true)!;
    const [toCursor, fromCursor] = dragPreview(legs, leg, P);
    const closed = legPoints(next, true);
    assert.deepEqual(next[leg + 1], P);
    assert.deepEqual(toCursor[0], closed[leg], `leg ${leg}: the preview starts at the point before`);
    assert.deepEqual(fromCursor[1], closed[leg + 2], `leg ${leg}: the preview ends at the point after`);
    const said = insertedSaid(leg, next.length, true);
    const after = leg + 2 === next.length ? "the start" : pointName(leg + 2, next.length, true);
    const before = leg === 0 ? "the start" : pointName(leg, next.length, true);
    assert.equal(said, `Stop ${leg + 1} added, between ${before} and ${after}.`);
  }
  assert.equal(insertedSaid(2, 4, true), "Stop 3 added, between Stop 2 and the start.");
});

test("Reverse in a loop keeps the start and rides the stops the other way around", () => {
  assert.deepEqual(reversedPoints([A, B, C, D], true), [A, D, C, B]);
  assert.deepEqual(reversedPoints([A, B, C, D], false), [D, C, B, A]);
  assert.equal(reverseKeepsStart([A, B, C], true), true);
  assert.equal(reverseKeepsStart([A, B, C], false), false);
});

test("Reverse is offered only where it changes something", () => {
  assert.equal(canReverse([A, B], true), false, "a start and one stop is the same loop either way around");
  assert.deepEqual(reversedPoints([A, B], true), [A, B]);
  assert.equal(canReverse([A, B, C], true), true);
  assert.equal(canReverse([A, B], false), true);
  assert.equal(canReverse([A], false), false);
  assert.equal(canReverse([], true), false);
});

test("a ride that already ends on its start is reversed whole, loop or not", () => {
  const back: LonLat = [-77.0001, 38.9001];
  assert.equal(reverseKeepsStart([A, B, back], true), false);
  assert.deepEqual(reversedPoints([A, B, back], true), [back, B, A]);
  assert.equal(canReverse([A, B, back], true), true);
});
