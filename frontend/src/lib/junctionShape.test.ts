import { test } from "node:test";
import assert from "node:assert/strict";
import { junctionPaths, ringPaths } from "./junctionShape.ts";

test("an unusual junction is drawn: in and the way taken solid with a head, each other way its own dashed line", () => {
  // A left onto a service road with the road running on ahead and to the right.
  const drawn = junctionPaths({ out: -90, others: [0, 90] });
  assert.equal(drawn.route, "M24 52 L24 30 L4 30 M10.9 24.2 L4 30 L10.9 35.8");
  assert.deepEqual(drawn.others, ["M24 30 L24 10", "M24 30 L44 30"]);
});

test("a five-way's diagonals stay inside the arrow's box", () => {
  const drawn = junctionPaths({ out: 45, others: [-135, -90, 0, 90, 135] });
  const numbers = [drawn.route, ...drawn.others].join(" ").match(/-?\d+(\.\d+)?/g)!.map(Number);
  for (let i = 0; i < numbers.length; i += 2) {
    assert.ok(numbers[i] >= 0 && numbers[i] <= 48, `x ${numbers[i]}`);
    assert.ok(numbers[i + 1] >= 0 && numbers[i + 1] <= 56, `y ${numbers[i + 1]}`);
  }
  assert.equal(drawn.others.length, 5);
});

test("a service road's main road is drawn as a road's two edges, across the way in or the way ahead", () => {
  assert.equal(junctionPaths({ out: -90, others: [0] }).main, null);
  // A left across East-West Highway: the highway runs across the way in, below the junction.
  assert.equal(junctionPaths({ out: -90, others: [0], main: "before" }).main, "M-2 47.5 L50 47.5 M-2 42.5 L50 42.5");
  // A right short of it: across the way ahead, above.
  assert.equal(junctionPaths({ out: 90, others: [0], main: "after" }).main, "M50 12.5 L-2 12.5 M50 17.5 L-2 17.5");
});

test("a circle: in from the bottom, round the way it is ridden, off at the exit with a head; the exits passed dashed", () => {
  // Bearing right onto the ring (anticlockwise), past an exit on the right, off to the left: the long way round.
  const left = ringPaths({ out: -90, others: [80, -30], ring: "right" });
  assert.match(left.route, /^M24 54 L24 36 A12 12 0 1 0 12 24 L1 24 /);
  assert.deepEqual(left.others, ["M35.8 21.9 L46.7 20", "M18 13.6 L12.5 4.1"]);
  // Off to the right is the short way round; bearing left onto the ring, it is the long way.
  assert.match(ringPaths({ out: 90, others: [], ring: "right" }).route, / A12 12 0 0 0 36 24 /);
  assert.match(ringPaths({ out: 90, others: [], ring: "left" }).route, / A12 12 0 1 1 36 24 /);
  // Back the way it came in is right round.
  assert.match(ringPaths({ out: 180, others: [], ring: "right" }).route, / A12 12 0 0 0 24 12 A12 12 0 0 0 24 36 /);
});
