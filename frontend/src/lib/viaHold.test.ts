// A long press on a via point removes it (lib/viaHold.ts; MapView.tsx).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { HOLD_MS, HOLD_SLOP_PX, ViaHold } from "./viaHold.ts";

function clock() {
  let next: { fn: () => void; ms: number } | null = null;
  return {
    timers: {
      set: ((fn: () => void, ms: number) => {
        next = { fn, ms };
        return 1;
      }) as unknown as typeof setTimeout,
      clear: (() => {
        next = null;
      }) as unknown as typeof clearTimeout,
    },
    fire() {
      const due = next;
      next = null;
      due?.fn();
      return due?.ms;
    },
  };
}
const at = (x: number, y = 0) => [{ clientX: x, clientY: y }];

test("one finger held still is a long press", () => {
  const c = clock();
  let held = 0;
  const hold = new ViaHold(() => held++, c.timers);
  hold.start(at(100));
  hold.move(at(100 + HOLD_SLOP_PX - 2));
  assert.equal(c.fire(), HOLD_MS);
  assert.equal(held, 1);
});

test("a lift, a move past the slop or a second finger calls it off", () => {
  for (const off of [(h: ViaHold) => h.cancel(), (h: ViaHold) => h.move(at(100 + HOLD_SLOP_PX + 1)), (h: ViaHold) => h.move([...at(100), ...at(200)])]) {
    const c = clock();
    let held = 0;
    const hold = new ViaHold(() => held++, c.timers);
    hold.start(at(100));
    off(hold);
    c.fire();
    assert.equal(held, 0);
  }
  const c = clock();
  let held = 0;
  new ViaHold(() => held++, c.timers).start([...at(1), ...at(2)]);
  c.fire();
  assert.equal(held, 0, "a pinch never starts one");
});

test("a right-click or a long press on a via offers Remove, as a click does, and says so in its tooltip", () => {
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /element\.addEventListener\("contextmenu", \(event\) => \{\s*event\.stopPropagation\(\);\s*event\.preventDefault\(\);\s*if \(dragged\) return;\s*hold\.cancel\(\);\s*offerRemove\(\);/);
  assert.match(map, /new ViaHold\(\(\) => \{\s*if \(!dragged\) offerRemove\(\);/);
  assert.match(map, /click, right-click or long-press for Remove/);
});
