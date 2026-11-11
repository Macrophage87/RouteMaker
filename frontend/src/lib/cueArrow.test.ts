// The picture beside each cue of the phone cue images (lib/cueArrow.ts): the owner, 2026-11-10, "Basically show the
// arrows". Plain geometry in a 100 by 100 box, the same as the connector's (src/core/cue_cards.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { arrowShape, type CueArrow } from "./cueArrow.ts";

const ALL: CueArrow[] = [
  { kind: "turn", moves: ["left"], across: false },
  { kind: "turn", moves: ["right", "left", "right"], across: false },
  { kind: "turn", moves: ["uturn"], across: false },
  { kind: "turn", moves: ["bear_right"], across: true },
  { kind: "cross" },
  { kind: "walk" },
  { kind: "start" },
  { kind: "finish" },
  { kind: "stop", number: 3 },
  { kind: "caution" },
  { kind: "note" },
];

test("every picture keeps inside its box", () => {
  for (const arrow of ALL) {
    const s = arrowShape(arrow);
    for (const p of [...s.strokes, ...s.thin, ...s.fills].flat()) assert.ok(p[0] >= 0 && p[0] <= 100 && p[1] >= 0 && p[1] <= 100, JSON.stringify(arrow));
  }
});

test("a turn's head points its way; a turn across a road and a crossing draw the road's two edges", () => {
  const left = arrowShape({ kind: "turn", moves: ["left"], across: false });
  const right = arrowShape({ kind: "turn", moves: ["right"], across: false });
  const xs = (s: typeof left) => [...s.fills[0], ...s.strokes[0]].map((p) => p[0]);
  assert.equal(left.fills[0][0][0], Math.min(...xs(left)));
  assert.equal(right.fills[0][0][0], Math.max(...xs(right)));
  assert.equal(left.thin.length, 0);
  assert.equal(arrowShape({ kind: "turn", moves: ["right"], across: true }).thin.length, 2);
  assert.equal(arrowShape({ kind: "cross" }).thin.length, 2);
  // A walk is dashed: many short strokes.
  assert.ok(arrowShape({ kind: "walk" }).strokes.length > 2);
  assert.equal(arrowShape({ kind: "stop", number: 3 }).label?.text, "3");
});

test("the browser's and the connector's pictures are the same numbers", () => {
  // src/core/cue_cards.py follows this file; tests/test_cue_cards.py checks the same shapes.
  const s = arrowShape({ kind: "turn", moves: ["left"], across: false });
  assert.deepEqual(s.fills[0], [[28, 35.3], [60.3, 6], [60.3, 64.7]]);
});
