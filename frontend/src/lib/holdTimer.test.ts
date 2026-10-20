// The short-lived messages' timer (review F4, F6): the 311 line and the ride's toast clear after a while, but
// never while the focus or a mouse is in them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { HoldTimer, type Clock } from "./holdTimer.ts";

/** A clock the test moves by hand. */
function fakeClock() {
  let now = 0;
  let next = 1;
  const pending = new Map<number, { at: number; run: () => void }>();
  const clock: Clock = {
    set: (run, ms) => {
      const id = next++;
      pending.set(id, { at: now + ms, run });
      return id;
    },
    clear: (handle) => {
      pending.delete(handle as number);
    },
  };
  const advance = (ms: number) => {
    now += ms;
    for (const [id, item] of [...pending]) {
      if (item.at <= now) {
        pending.delete(id);
        item.run();
      }
    }
  };
  return { clock, advance };
}

test("F4. the message clears after its time", () => {
  const { clock, advance } = fakeClock();
  let gone = 0;
  const timer = new HoldTimer(8_000, () => gone++, clock);
  timer.start();
  advance(7_999);
  assert.equal(gone, 0);
  advance(1);
  assert.equal(gone, 1);
  assert.equal(timer.running, false);
});

test("F4. the focus or a mouse inside holds it; once both leave, the full time starts again", () => {
  const { clock, advance } = fakeClock();
  let gone = 0;
  const timer = new HoldTimer(8_000, () => gone++, clock);
  timer.start();
  advance(5_000);
  timer.focus(true);
  advance(60_000);
  assert.equal(gone, 0, "held while focused");
  timer.hover(true);
  timer.focus(false);
  advance(60_000);
  assert.equal(gone, 0, "held while hovered");
  timer.hover(false);
  advance(7_999);
  assert.equal(gone, 0, "the full time again, not what was left");
  advance(1);
  assert.equal(gone, 1);
});

test("F4. a new message restarts the time; a start while held waits; reset lets go of a gone element's hold", () => {
  const { clock, advance } = fakeClock();
  let gone = 0;
  const timer = new HoldTimer(8_000, () => gone++, clock);
  timer.start();
  advance(6_000);
  timer.start();
  advance(6_000);
  assert.equal(gone, 0, "restarted by the second message");
  timer.focus(true);
  timer.start();
  assert.equal(timer.running, false, "a start while focused waits");
  timer.reset();
  timer.start();
  advance(8_000);
  assert.equal(gone, 1);
});

test("F4. RideMode: the 311 line uses it (8 s), held on focus or a mouse", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /export const SAID_311_MS = 8_000;/);
  assert.match(ride, /const said311Timer = useHoldTimer\(SAID_311_MS, \(\) => setSaid311\(""\)\);/);
  assert.match(ride, /<div className="ride-311-said" \{\.\.\.said311Timer\.hold\}>/);
  assert.match(ride, /if \(said311Shown\) said311Timer\.timer\.start\(\);\s*else said311Timer\.timer\.reset\(\);/);
  // A touch's emulated hover is not a hover (it would hold the line until the next tap).
  assert.match(ride, /if \(event\.pointerType === "mouse"\) timer\.current\?\.hover\(true\);/);
});
