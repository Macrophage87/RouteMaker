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
import { ViaMarks, stopsOnly, withVias } from "./pointKinds.ts";
import type { LonLat } from "./geo.ts";

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

test("while a stop is dragged, it follows the pointer and the stops it passes slide to their neighbour's place", () => {
  // Stops at 0, 60, 100 and 150 (a via point's row between the first two): each passed stop takes the next one's top.
  const tops = [0, 60, 100, 150];
  const down = { from: 1, over: 3, dy: 95, tops };
  assert.deepEqual([0, 1, 2, 3].map((i) => rowShift(i, down)), [0, 95, -40, -50]);
  const up = { from: 3, over: 1, dy: -100, tops };
  assert.deepEqual([0, 1, 2, 3].map((i) => rowShift(i, up)), [0, 40, 50, -100]);
});

const STOPS = [1, 2];

function list(m: PointMover | null, slots: readonly number[] = STOPS, rows: readonly PointRow[] = ROWS): string {
  return renderToStaticMarkup(createElement(PointsList, { rows, onRemove: () => {}, removeRef: () => {}, mover: m, slots }));
}

test("only the stops have a grip, named for the stop and described in a few words, with two stops or more", () => {
  const html = list(mover());
  assert.deepEqual([...html.matchAll(/<button type="button" class="point-grip" aria-label="([^"]*)" aria-describedby="point-move-hint" aria-expanded="false"/g)].map((m) => m[1]), [
    "Move Stop 1",
    "Move Stop 2",
  ]);
  // The start and the end keep their place: a blank the grip's width, so the roles line up.
  assert.equal((html.match(/<span class="point-grip-space" aria-hidden="true"><\/span>/g) ?? []).length, 2);
  assert.match(html, new RegExp(`<span id="point-move-hint" hidden="">${MOVE_HINT}</span>$`));
  assert.ok(MOVE_HINT.split(" ").length <= 8, "short, as it is read on every grip");
  // One stop has nothing to reorder; no mover, no grips.
  assert.doesNotMatch(list(mover(), [1]), /point-grip/);
  assert.doesNotMatch(list(null), /point-grip|point-move-hint/);
});

test("a grip's press shows Up, Down and Done on a line under its stop, in place of Remove; the first stop has no Up", () => {
  const first = list(mover({ moving: 0 }));
  assert.match(first, /<li class="point-moving"><button type="button" class="point-grip" aria-label="Move Stop 1" aria-describedby="point-move-hint" aria-expanded="true"/);
  assert.match(first, /<span class="point-steps"><button type="button" class="link" aria-label="Move Stop 1 down">Down<\/button><button type="button" class="link">Done<\/button><\/span><\/li>/);
  assert.doesNotMatch(first, /aria-label="Remove Stop 1"/);
  assert.match(first, /aria-label="Remove Stop 2"/);
  const last = list(mover({ moving: 1 }));
  assert.match(last, /<span class="point-steps"><button type="button" class="link" aria-label="Move Stop 2 up">Up<\/button><button type="button" class="link">Done<\/button><\/span>/);
});

test("mid-drag the dragged stop is lifted and moved, and the stop it passed slides; the start and the end stay", () => {
  const html = list(mover({ drag: { from: 0, over: 1, dy: 60, tops: [100, 150] } }));
  assert.match(html, /^<ol class="points points-dragging">/);
  assert.match(html, /<li class="point-dragged" style="transform:translateY\(60px\)"><button type="button" class="point-grip" aria-label="Move Stop 1"/);
  assert.match(html, /<li style="transform:translateY\(-50px\)"><button type="button" class="point-grip" aria-label="Move Stop 2"/);
  assert.match(html, /<li><span class="point-grip-space" aria-hidden="true"><\/span><span class="point-name">Start/);
});

test("App: only stops move, each with the via points leading to it, as one edit; a drag is said, a key's focus says it", () => {
  const app = appSource();
  assert.match(app, /const split = stopsOnly\(current, VIA_MARKS\.isVia, loopVias\);/);
  assert.match(app, /if \(a < 1 \|\| b < 1 \|\| a === b\) return;/);
  assert.match(app, /const next = withVias\(reorder\(split\.points\.map\(\(_, i\) => i\), a, b\), split\);\s*commit\(next\);\s*if \(by !== "drag"\) return;/);
  assert.match(app, /announce\(name \? t\("\{name\} is now \{role\}\.", \{ name, role \}\) : t\("Moved to \{role\}\.", \{ role \}\)\);/);
  assert.match(app, /const slots = namePoints\(points, VIA_MARKS\.isVia, loopVias\)\.flatMap\(\(n, i\) => \(n\.role === "stop" \? \[i\] : \[\]\)\);/);
  assert.match(app, /const mover = usePointMover\(slots, \(from, to, by\) => reorderPoint\(slots\[from\], slots\[to\], by\), points\);/);
  assert.match(app, /warnings=\{pointWarnings\}\s+mover=\{mover\}\s+slots=\{slots\}/);
});

test("a stop moved past another takes its via points with it, and the start and the end stay (lib/pointKinds.ts)", () => {
  const marks = new ViaMarks();
  const start: LonLat = [0, 0], via: LonLat = marks.via([1, 1]), s1: LonLat = [2, 2], s2: LonLat = [3, 3], end: LonLat = [4, 4];
  const points = [start, via, s1, s2, end];
  const split = stopsOnly(points, marks.isVia);
  const next = withVias(reorder(split.points.map((_, i) => i), split.points.indexOf(s1), split.points.indexOf(s2)), split);
  assert.deepEqual(next, [start, s2, via, s1, end]);
});
