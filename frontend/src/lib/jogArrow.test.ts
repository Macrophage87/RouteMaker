import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { jogArrowPath } from "./jogArrow.ts";

/** The path's points, in order. */
function points(d: string): [number, number][] {
  return [...d.matchAll(/(-?[\d.]+) (-?[\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
}

test("jogArrowPath: one arrow through every turn, inside the card's 48 x 56 box, its foot at the bottom", () => {
  // The owner's screenshot, 2026-10-26: bear right to stay on Rock Creek Trail, then immediately left.
  const d = jogArrowPath({ movement: "bear_right", then: [{ movement: "left", street: "Rock Creek Trail" }] });
  assert.ok(d);
  const pts = points(d);
  // Foot, the bear, the left, the tip; then the head's three points.
  assert.equal(pts.length, 4 + 3);
  for (const [x, y] of pts) assert.ok(x >= 2 && x <= 46 && y >= 2 && y <= 54, `${x} ${y}`);
  const [foot, bear, left, tip] = pts;
  assert.equal(foot[1], Math.max(...pts.map((p) => p[1])));
  assert.equal(bear[0], foot[0]); // the stem goes straight up
  assert.ok(left[0] > bear[0] && left[1] < bear[1]); // bears right
  assert.ok(tip[0] < left[0] && tip[1] < left[1]); // then turns left, up and to the left
  // Three turns: a leg for each, all in the box.
  const three = points(jogArrowPath({ movement: "left", then: [{ movement: "right", street: null }, { movement: "left", street: null }] })!);
  assert.equal(three.length, 5 + 3);
  for (const [x, y] of three) assert.ok(x >= 2 && x <= 46 && y >= 2 && y <= 54, `${x} ${y}`);
});

test("jogArrowPath: none through a circle (its ring and exit number say more), nor where the legs would cross", () => {
  const exit = { number: 2, circle: "Dupont Circle Northwest" };
  assert.equal(jogArrowPath({ movement: "bear_right", then: [{ movement: "left", street: "P Street Northwest", exit }] }), null);
  assert.equal(jogArrowPath({ movement: "right", exit, then: [{ movement: "left", street: null }] }), null);
  const right = { movement: "right" as const, street: null };
  assert.equal(jogArrowPath({ movement: "right", then: [right, right] }), null);
  assert.ok(jogArrowPath({ movement: "right", then: [right] }));
});

test("jogArrowPath: none for a single turn or a U-turn in the jog", () => {
  assert.equal(jogArrowPath({ movement: "left" }), null);
  assert.equal(jogArrowPath({ movement: "left", then: [] }), null);
  assert.equal(jogArrowPath({ movement: "uturn", then: [{ movement: "left", street: null }] }), null);
});

test("Ride's card draws a jog's arrow, not across a crossing (crossArrow draws that)", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /jog=\{cue\.cross \? null : jogArrowPath\(cue\)\}/);
});
