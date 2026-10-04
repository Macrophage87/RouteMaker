/** What the page says about points, with the loop on and off (OWNER-DECISIONS 374). */
import assert from "node:assert/strict";
import test from "node:test";
import { placeEffectHint } from "./geocode.ts";
import { LOOP_LABEL, LOOP_START_NAME, loopView } from "./loop.ts";
import { markerDeps } from "./mapGlue.ts";
import {
  addedSaid,
  emptyPlanHint,
  insertedSaid,
  loneStartHint,
  loopToggledSaid,
  pointLabel,
  removedSaid,
  reversedSaid,
  stationSaid,
} from "./pointText.ts";
import { LOOP_START_NAME as SUMMARY_LOOP_START_NAME } from "./summary.ts";
import type { LonLat } from "./geo.ts";

const labels = (count: number, loop: boolean) => Array.from({ length: count }, (_, i) => pointLabel(i, count, loop));

test("pointLabel: in a loop A is the start and finish, the rest are numbered stops, and there is no B or End", () => {
  assert.deepEqual(labels(3, true), [
    { text: "A", name: LOOP_START_NAME, kind: "start" },
    { text: "1", name: "Stop 1", kind: "via" },
    { text: "2", name: "Stop 2", kind: "via" },
  ]);
  assert.deepEqual(labels(1, true), [{ text: "A", name: "Start and finish", kind: "start" }]);
  for (let count = 1; count <= 6; count += 1) {
    for (const label of labels(count, true)) {
      assert.notEqual(label.text, "B");
      assert.notEqual(label.name, "End");
      assert.notEqual(label.kind, "end");
    }
  }
});

test("pointLabel: off the loop, A is the start, B the end, and the stops between are numbered", () => {
  assert.deepEqual(labels(3, false), [
    { text: "A", name: "Start", kind: "start" },
    { text: "1", name: "Stop 1", kind: "via" },
    { text: "B", name: "End", kind: "end" },
  ]);
  assert.deepEqual(labels(1, false), [{ text: "A", name: "Start", kind: "start" }]);
});

test("one name for the loop's start, shared by the list, the markers and the GPX", () => {
  assert.equal(LOOP_START_NAME, "Start and finish");
  assert.equal(SUMMARY_LOOP_START_NAME, LOOP_START_NAME);
});

test("add, remove and station announcements name the point as the loop does", () => {
  assert.equal(addedSaid(0, 1, true), "Start and finish added.");
  assert.equal(addedSaid(1, 2, true), "Stop 1 added.");
  assert.equal(addedSaid(1, 2, false), "End added.");
  assert.equal(removedSaid(2, 3, true), "Stop 2 removed.");
  assert.equal(removedSaid(2, 3, false), "End removed.");
  assert.equal(removedSaid(0, 3, true), "Start and finish removed.");
  assert.equal(stationSaid(1, 2, true), "Stop 1 set at the station.");
  assert.equal(stationSaid(1, 2, false), "End set at the station.");
  assert.equal(stationSaid(0, 2, false), "Start set at the station.");
});

test("a dragged stop is said between two places, and the loop's start is 'the start'", () => {
  // Leg 0 of a loop [A, P, S1]: between the start and the stop after it.
  assert.equal(insertedSaid(0, 3, true), "Stop 1 added, between the start and Stop 2.");
  // The closing leg of [A, S1] gives [A, S1, P]: P is between Stop 1 and the start.
  assert.equal(insertedSaid(1, 3, true), "Stop 2 added, between Stop 1 and the start.");
  assert.equal(insertedSaid(1, 4, true), "Stop 2 added, between Stop 1 and Stop 3.");
  // Off the loop the sentence is as before.
  assert.equal(insertedSaid(0, 3, false), "Stop 1 added, between Start and End.");
  assert.equal(insertedSaid(1, 4, false), "Stop 2 added, between Stop 1 and End.");
  for (const leg of [0, 1, 2]) assert.doesNotMatch(insertedSaid(leg, 4, true), /Start and finish|End/);
});

test("Reverse says what it did", () => {
  assert.match(reversedSaid(true), /other way around, from the same start/);
  assert.match(reversedSaid(false), /old end is now the start/);
});

test("turning the loop on or off says how the points are now named", () => {
  assert.equal(loopToggledSaid(true, 1), "Loop on: the start is also the finish; other points are stops.");
  assert.equal(loopToggledSaid(true, 3), "Loop on: the start is also the finish; other points are stops.");
  assert.equal(loopToggledSaid(false, 3), "Loop off: the last point is now the end.");
  assert.equal(loopToggledSaid(false, 1), "Loop off: the next point you add is the end.");
});

test("the empty-plan hint: start then stops in a loop; the toggle offered only where the ride type has one", () => {
  const loop = emptyPlanHint("default", true);
  assert.match(loop, /set a start, then add stops/);
  assert.doesNotMatch(loop, /then an end/);
  assert.doesNotMatch(loop, new RegExp(LOOP_LABEL));
  const plain = emptyPlanHint("default", false);
  assert.match(plain, /set a start, then an end/);
  assert.match(plain, /turn on Make it a loop under Adjust this ride/);
  const mass = emptyPlanHint("mass-ride", false);
  assert.match(mass, /set a start, then an end/);
  assert.doesNotMatch(mass, /loop/i);
  for (const hint of [loop, plain, mass]) {
    assert.match(hint, /"Add point at map center"/);
    assert.doesNotMatch(hint, /centre/);
  }
});

test("the lone-start hint: a stop next in a loop; the toggle offered only where the ride type has one", () => {
  assert.equal(loneStartHint("default", true), "Now click the map to add a stop. The ride comes back to the start.");
  assert.equal(
    loneStartHint("default", false),
    "Now click the map where you want to finish, or turn on Make it a loop under Adjust this ride to finish back at the start.",
  );
  assert.equal(loneStartHint("mass-ride", false), "Now click the map where you want to finish.");
  assert.doesNotMatch(loneStartHint("mass-ride", false), /loop/i);
});

test("the toggle's hint with a start alone talks of no end point", () => {
  const A: LonLat = [-77.0, 38.9];
  const B: LonLat = [-76.98, 38.9];
  const off = loopView("default", false, [A])!;
  assert.equal(off.hint, "Turn on to finish back at the start. Each point you add is then a stop.");
  assert.doesNotMatch(off.hint, /end point/);
  assert.match(loopView("default", false, [A, B])!.hint, /end point/);
  const on = loopView("default", true, [A])!;
  assert.match(on.hint, /on the way around/);
  assert.doesNotMatch(on.hint, /way round/);
});

test("the search hint in a loop: a new start is the new start and finish", () => {
  assert.equal(placeEffectHint("replace-start", true), "The place you pick becomes the new start and finish.");
  assert.equal(placeEffectHint("start", true), "The place you pick becomes the start and finish.");
  assert.equal(placeEffectHint("via", true), "The place you pick is added as a stop along the way.");
  assert.equal(placeEffectHint("replace-start"), "The place you pick becomes the new start.");
  assert.equal(placeEffectHint("end"), "The place you pick becomes the destination.");
  assert.equal(placeEffectHint("replace-end", false), "The place you pick becomes the new destination.");
});

test("the markers are rebuilt when the loop toggle flips", () => {
  const points: LonLat[] = [[-77.0, 38.9]];
  const changed = (a: readonly unknown[], b: readonly unknown[]) => a.some((d, i) => !Object.is(d, b[i]));
  assert.equal(changed(markerDeps(points, 0, true), markerDeps(points, 0, true)), false);
  assert.equal(changed(markerDeps(points, 0, false), markerDeps(points, 0, true)), true, "the toggle renames the markers");
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 0, false)), false, "unset is off");
});
