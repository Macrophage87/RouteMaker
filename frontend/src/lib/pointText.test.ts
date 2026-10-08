/** What the page says about points, with the loop on and off (OWNER-DECISIONS 374). */
import assert from "node:assert/strict";
import test from "node:test";
import { placeEffectHint } from "./geocode.ts";
import { LOOP_LABEL, LOOP_START_NAME, loopView } from "./loop.ts";
import { markerDeps } from "./mapGlue.ts";
import {
  addedSaid,
  editingTips,
  emptyPlanHint,
  insertedSaid,
  loopChangeSaid,
  LOOP_FIRST_SAID,
  loneStartHint,
  loopToggledSaid,
  pointLabel,
  removedSaid,
  REVERSE_ONE_STOP_HINT,
  reverseUnavailableHint,
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

test("Reverse says what it did, and a loop has no end to mention", () => {
  assert.match(reversedSaid(true), /other way around, from the same start/);
  assert.doesNotMatch(reversedSaid(true), /end/);
  assert.match(reversedSaid(false), /old end is now the start/);
});

test("Reverse in a loop of a start and one stop says why it does nothing", () => {
  const A: LonLat = [-77.0, 38.9];
  const B: LonLat = [-76.98, 38.9];
  const C: LonLat = [-76.96, 38.9];
  assert.equal(
    REVERSE_ONE_STOP_HINT,
    "A loop with one stop is the same either way around. Add another stop to reverse it.",
  );
  assert.equal(reverseUnavailableHint([A, B], true), REVERSE_ONE_STOP_HINT);
  assert.equal(reverseUnavailableHint([A, B, C], true), null, "two stops can be reversed");
  assert.equal(reverseUnavailableHint([A, B], false), null, "a one-way ride can be reversed");
  // Nothing to reverse at all: plainly disabled, no reason needed.
  assert.equal(reverseUnavailableHint([A], true), null);
  assert.equal(reverseUnavailableHint([], true), null);
});

test("turning the loop on or off says how the points are now named", () => {
  assert.equal(loopToggledSaid(true, 1), "Loop on: the start is also the finish; other points are stops.");
  assert.equal(loopToggledSaid(true, 3), "Loop on: the start is also the finish; other points are stops.");
  assert.equal(loopToggledSaid(false, 3), "Loop off: the last point is now the end.");
  assert.equal(loopToggledSaid(false, 1), "Loop off: the next point you add is the end.");
});

test("a change of the ride says how the points are renamed, and only when they are", () => {
  const off = { preset: "default" as const, dials: { loop: false } };
  const on = { preset: "default" as const, dials: { loop: true } };
  const unset = { preset: "default" as const, dials: {} };
  const massOn = { preset: "mass-ride" as const, dials: { loop: true } };
  const massOff = { preset: "mass-ride" as const, dials: { loop: false } };
  // The toggle: off to on, on to off.
  assert.equal(loopChangeSaid(off, on, 2), loopToggledSaid(true, 2));
  assert.equal(loopChangeSaid(unset, on, 1), loopToggledSaid(true, 1));
  assert.equal(loopChangeSaid(on, off, 3), "Loop off: the last point is now the end.");
  assert.equal(loopChangeSaid(on, off, 1), "Loop off: the next point you add is the end.");
  // Unchanged: a slider moved, or the toggle as it was.
  assert.equal(loopChangeSaid(on, on, 3), null);
  assert.equal(loopChangeSaid(off, off, 3), null);
  assert.equal(loopChangeSaid(unset, off, 3), null, "unset is off");
  // Mass Ride has no loop: into it from a loop renames the points, and out of it back into a loop.
  assert.equal(loopChangeSaid(on, massOn, 3), loopToggledSaid(false, 3));
  assert.equal(loopChangeSaid(massOn, on, 3), loopToggledSaid(true, 3));
  assert.equal(loopChangeSaid(massOff, massOn, 3), null, "the toggle does nothing on a Mass Ride");
  assert.equal(loopChangeSaid(off, massOn, 3), null);
  // No points: nothing is renamed, so only the state is said: the loop on, with what to place first (389), or "Loop off.".
  assert.equal(loopChangeSaid(off, on, 0), "Loop on. Place the starting point, then a stop or two along the way.");
  assert.equal(loopChangeSaid(off, on, 0), LOOP_FIRST_SAID);
  assert.equal(loopChangeSaid(on, off, 0), "Loop off.", "off with no point says so, whether pressed or undone");
  assert.equal(loopChangeSaid(on, on, 0), null, "and nothing when it did not change");
  // Out of Mass Ride into a ride type with the loop on, with no point: the box comes back checked, so say it.
  assert.equal(loopChangeSaid(massOn, on, 0), LOOP_FIRST_SAID);
  assert.equal(loopChangeSaid(on, massOn, 0), "Loop off.");
});

test("the empty-plan hint: start then stops in a loop; the toggle offered only where the ride type has one", () => {
  const loop = emptyPlanHint("default", true);
  assert.match(loop, /set a start, then add stops/);
  assert.doesNotMatch(loop, /then an end/);
  // After Clear the toggle stays on, in view under the search (388, 389): say so, and how to turn it off.
  assert.match(loop, /"Make it a loop" is checked, under the search; uncheck it for a ride that ends somewhere else\./);
  const plain = emptyPlanHint("default", false);
  assert.match(plain, /set a start, then an end/);
  assert.match(plain, /To finish back at the start, check "Make it a loop" under the search; then each click after the start is a stop\./);
  assert.doesNotMatch(`${loop} ${plain}`, /ride settings|Edit button/, "the toggle is no longer behind the Ride line (388)");
  const mass = emptyPlanHint("mass-ride", false);
  assert.match(mass, /set a start, then an end/);
  assert.doesNotMatch(mass, /loop/i);
  for (const hint of [loop, plain, mass]) {
    assert.match(hint, /"Add point at map center"/);
    assert.doesNotMatch(hint, /centre/);
  }
});

test("the lone-start hint: a stop next in a loop; the toggle offered only where the ride type has one", () => {
  assert.equal(
    loneStartHint("default", true, true),
    'Now click the map to add a stop, or use "Add point at map center" in Map tools. The ride comes back to the start.',
  );
  assert.equal(
    loneStartHint("default", false, true),
    'Now click the map where you want to finish, or use "Add point at map center" in Map tools. To finish back at the start' +
      ' instead, check "Make it a loop" under the search.',
  );
  assert.equal(
    loneStartHint("mass-ride", false, true),
    'Now click the map where you want to finish, or use "Add point at map center" in Map tools.',
  );
  assert.doesNotMatch(loneStartHint("mass-ride", false, true), /loop/i);
});

test("accessibility mode off: the hints say to turn it on, not to use Map tools that is not there (455)", () => {
  for (const hint of [
    loneStartHint("default", true),
    loneStartHint("default", false),
    loneStartHint("mass-ride", false),
  ]) {
    assert.match(hint, /turn on accessibility mode/);
    assert.doesNotMatch(hint, /Map tools/);
  }
  const tips = editingTips();
  assert.match(tips, /turn on accessibility mode \(the first link on the page\), then use "Add point at map center" in Map tools/);
  assert.match(editingTips(true), /use "Add point at map center" in Map tools; Ctrl\+Z/);
  assert.doesNotMatch(editingTips(true), /accessibility mode/);
  assert.match(emptyPlanHint("default", false), /turn on accessibility mode/);
  assert.doesNotMatch(emptyPlanHint("default", false, true), /accessibility mode/);
});

test("the toggle's hint with a start alone talks of no end point", () => {
  const A: LonLat = [-77.0, 38.9];
  const B: LonLat = [-76.98, 38.9];
  const off = loopView("default", false, [A])!;
  assert.equal(off.hint, "Turn on to finish back at the start. Each point you add is then a stop.");
  assert.equal(loopView("default", false, [])!.hint, off.hint, "the same before any point (389)");
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
