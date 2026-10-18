// Reordering the plan's points by hand (Stephen 2026-10-18: "In addition to best order, allow the stops to be
// dragged and dropped too"): the drop's arithmetic, the list's grips, and App's one edit.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { dropIndex, reorder, rowShift, type PointMover } from "./pointMover.ts";
import { MOVE_HINT, PointsList } from "./pointsList.ts";
import type { PointRow } from "./geocode.ts";
import { appSource } from "../testSupport/appSource.mjs";

const ROWS: PointRow[] = [
  { role: "Start", place: { name: "Union Market", label: "Union Market" }, coords: "38.9080, -76.9970" },
  { role: "Stop 1", place: undefined, coords: "38.9000, -77.0200" },
  { role: "Stop 2", place: undefined, coords: "38.8950, -77.0300" },
  { role: "End", place: undefined, coords: "38.8978, -77.0074" },
];

function mover(over: Partial<PointMover> = {}): PointMover {
  return {
    drag: null,
    moving: null,
    grip: () => ({ ref: () => {}, onPointerDown: () => {}, onPointerMove: () => {}, onPointerUp: () => {}, onPointerCancel: () => {}, onClick: () => {}, onKeyDown: () => {} }),
    step: () => {},
    stepRef: () => {},
    done: () => {},
    ...over,
  };
}

function render(rows: readonly PointRow[], m: PointMover | null): string {
  return renderToStaticMarkup(createElement(PointsList, { rows, onRemove: () => {}, removeRef: () => {}, mover: m }));
}

test("reorder takes the item out and puts it back at its new place, the same objects, the list untouched", () => {
  const a = [1, 1] as const, b = [2, 2] as const, c = [3, 3] as const, d = [4, 4] as const;
  const list = [a, b, c, d];
  assert.deepEqual(reorder(list, 1, 3), [a, c, d, b]);
  assert.deepEqual(reorder(list, 3, 0), [d, a, b, c]);
  assert.deepEqual(reorder(list, 2, 2), list);
  assert.equal(reorder(list, 0, 2)[2], a, "the same pair, so its kind and name go with it");
  assert.deepEqual(list, [a, b, c, d]);
});

test("a dragged row lands past every other row whose middle it has passed", () => {
  const rows = [0, 1, 2, 3].map((i) => ({ top: i * 50, height: 50 }));
  // Row 1's middle is 75: unmoved it stays; past row 2's middle (125) it is third; above row 0's (25) it is first.
  assert.equal(dropIndex(rows, 1, 75), 1);
  assert.equal(dropIndex(rows, 1, 130), 2);
  assert.equal(dropIndex(rows, 1, 400), 3);
  assert.equal(dropIndex(rows, 1, 20), 0);
  assert.equal(dropIndex(rows, 3, 60), 1);
});

test("while a row is dragged, it follows the pointer and the rows it passes slide aside by its height", () => {
  const down = { from: 1, over: 3, dy: 110, height: 50 };
  assert.deepEqual([0, 1, 2, 3].map((i) => rowShift(i, down)), [0, 110, -50, -50]);
  const up = { from: 3, over: 1, dy: -100, height: 50 };
  assert.deepEqual([0, 1, 2, 3].map((i) => rowShift(i, up)), [0, 50, 50, -100]);
});

test("each row has a grip named for its point, described by the three ways, with three points or more", () => {
  const html = render(ROWS, mover());
  assert.deepEqual([...html.matchAll(/<button type="button" class="point-grip" aria-label="([^"]*)" aria-describedby="point-move-hint" aria-expanded="false"/g)].map((m) => m[1]), [
    "Move Start",
    "Move Stop 1",
    "Move Stop 2",
    "Move End",
  ]);
  assert.match(html, new RegExp(`<span id="point-move-hint" hidden="">${MOVE_HINT}</span>$`));
  // Two points have Reverse; no mover, no grips.
  assert.doesNotMatch(render(ROWS.slice(0, 2), mover()), /point-grip/);
  assert.doesNotMatch(render(ROWS, null), /point-grip|point-move-hint/);
});

test("a grip's press shows Move up, Move down and Done in place of Remove; the top row has no Move up", () => {
  const second = render(ROWS, mover({ moving: 1 }));
  assert.match(second, /aria-label="Move Stop 1" aria-describedby="point-move-hint" aria-expanded="true"/);
  assert.match(second, /<span class="point-steps"><button type="button" class="link" aria-label="Move Stop 1 up">Up<\/button><button type="button" class="link" aria-label="Move Stop 1 down">Down<\/button><button type="button" class="link">Done<\/button><\/span><\/li>/);
  assert.doesNotMatch(second, /aria-label="Remove Stop 1"/);
  assert.match(second, /aria-label="Remove Stop 2"/);
  const top = render(ROWS, mover({ moving: 0 }));
  assert.doesNotMatch(top, /Move Start up/);
  assert.match(top, /Move Start down/);
  const bottom = render(ROWS, mover({ moving: 3 }));
  assert.doesNotMatch(bottom, /Move End down/);
});

test("mid-drag the dragged row is lifted and moved, and the rows it passed are shifted", () => {
  const html = render(ROWS, mover({ drag: { from: 1, over: 2, dy: 60, height: 44 } }));
  assert.match(html, /^<ol class="points points-dragging">/);
  assert.match(html, /<li class="point-dragged" style="transform:translateY\(60px\)">/);
  assert.match(html, /<li style="transform:translateY\(-44px\)"><button type="button" class="point-grip" aria-label="Move Stop 2"/);
});

test("App: a reorder is one edit of the same pairs, said with the point's new role; the list's grips come from Planner", () => {
  const app = appSource();
  assert.match(app, /const next = reorder\(current, from, to\);\s*commit\(next\);/);
  assert.match(app, /announce\(name \? `\$\{name\} is now \$\{role\}\.` : `Moved to \$\{role\}\.`\);/);
  assert.match(app, /const mover = usePointMover\(points\.length, reorderPoint\);/);
  assert.match(app, /warnings=\{pointWarnings\}\s+mover=\{mover\}/);
});
