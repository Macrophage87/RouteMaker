// App's own commit and undo/redo (MERGE-SEARCH re-check R15).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EditHistory } from "./editHistory.ts";
import { planEdits, travelSaid } from "./planEdits.ts";

function wired(start: number[] = []) {
  const history = new EditHistory<number[]>();
  let points = start;
  let syncs = 0;
  const edits = planEdits<number[]>({
    history,
    current: () => points,
    set: (next) => {
      points = next;
    },
    sync: () => {
      syncs += 1;
    },
  });
  return { edits, history, points: () => points, syncs: () => syncs };
}

test("an edit is recorded, so undo gives back the points before it and redo the edit", () => {
  const p = wired([1]);
  p.edits.commit([1, 2]);
  p.edits.commit([1, 2, 3]);
  assert.deepEqual(p.points(), [1, 2, 3]);
  assert.equal(p.history.canUndo, true);
  assert.deepEqual(p.edits.travel("undo"), [1, 2]);
  assert.deepEqual(p.points(), [1, 2]);
  assert.deepEqual(p.edits.travel("undo"), [1]);
  assert.deepEqual(p.edits.travel("redo"), [1, 2]);
  assert.deepEqual(p.points(), [1, 2]);
});

test("an edit builds on the points as they are now, and clears what could be redone", () => {
  const p = wired([1]);
  p.edits.commit([1, 2]);
  p.edits.travel("undo");
  p.edits.commit([1, 9]);
  assert.equal(p.history.canRedo, false);
  assert.deepEqual(p.edits.travel("undo"), [1]);
});

test("the history's buttons are told of every change, and of nothing when there is nothing to give back", () => {
  const p = wired([]);
  assert.equal(p.edits.travel("undo"), undefined);
  assert.equal(p.syncs(), 0);
  assert.deepEqual(p.points(), []);
  p.edits.commit([1]);
  assert.equal(p.syncs(), 1);
  p.edits.travel("undo");
  assert.equal(p.syncs(), 2);
});

test("what a screen reader hears after undo and redo", () => {
  assert.equal(travelSaid("undo", 2), "Undone. The route has 2 points.");
  assert.equal(travelSaid("redo", 1), "Redone. The route has 1 point.");
});

test("App edits through planEdits, with its own history and points", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /planEdits<LonLat\[\]>\(\{\s*history: history\.current,\s*current: \(\) => pointsRef\.current,/);
  assert.match(app, /const commit = edits\.commit;/);
  assert.match(app, /const next = edits\.travel\(direction\);/);
  assert.match(app, /announce\(travelSaid\(direction, next\.length\)\)/);
  // No second way in: nothing else in App records to the history.
  assert.doesNotMatch(app, /history\.current\.record\(/);
});
