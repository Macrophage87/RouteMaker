import { test } from "node:test";
import assert from "node:assert/strict";
import { junctionPaths } from "./junctionShape.ts";

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
