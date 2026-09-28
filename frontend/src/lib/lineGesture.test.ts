// When a press on the drawn route becomes a drag of it, by mouse and by finger.
import { test } from "node:test";
import assert from "node:assert/strict";
import { HOLD_MS, LineGesture, MOUSE_SLOP_PX, TOUCH_SLOP_PX } from "./lineGesture.ts";
import type { Timers } from "./routeScheduler.ts";

function fakeTimers() {
  let now = 0;
  const pending: Array<{ at: number; fn: () => void; id: number }> = [];
  let next = 0;
  const timers: Timers = {
    set: (fn, ms) => {
      next += 1;
      pending.push({ at: now + ms, fn, id: next });
      return next;
    },
    clear: (handle) => {
      const i = pending.findIndex((p) => p.id === handle);
      if (i >= 0) pending.splice(i, 1);
    },
  };
  const advance = (ms: number) => {
    now += ms;
    for (const p of [...pending].sort((a, b) => a.at - b.at)) {
      if (p.at <= now && pending.includes(p)) {
        pending.splice(pending.indexOf(p), 1);
        p.fn();
      }
    }
  };
  return { timers, advance, pending: () => pending.length };
}

function gesture() {
  const clock = fakeTimers();
  let pickUps = 0;
  const g = new LineGesture({ timers: clock.timers, onPickUp: () => (pickUps += 1) });
  return { g, clock, pickUps: () => pickUps };
}

test("a mouse press on the line drags it once the pointer moves past the click tolerance", () => {
  const { g } = gesture();
  g.press("mouse", 100, 100);
  assert.equal(g.active, true);
  assert.equal(g.dragging, false);
  assert.equal(g.move(100 + MOUSE_SLOP_PX - 1, 100), "none");
  assert.equal(g.dragging, false);
  assert.equal(g.move(100 + MOUSE_SLOP_PX, 100), "drag");
  assert.equal(g.dragging, true);
  assert.equal(g.move(160, 140), "drag");
  assert.equal(g.release(), "drop");
  assert.equal(g.active, false);
});

test("a mouse press released without moving is a click, not a drop", () => {
  const { g } = gesture();
  g.press("mouse", 100, 100);
  g.move(101, 101);
  assert.equal(g.release(), "none");
  assert.equal(g.active, false);
});

test("a mouse drag does not wait for a hold", () => {
  const { g, clock, pickUps } = gesture();
  g.press("mouse", 0, 0);
  assert.equal(clock.pending(), 0);
  g.move(20, 0);
  assert.equal(pickUps(), 0, "the mouse is not a pick-up: the map was stopped at the press");
});

test("a finger held still on the line picks it up after the hold", () => {
  const { g, clock, pickUps } = gesture();
  g.press("touch", 50, 50);
  clock.advance(HOLD_MS - 1);
  assert.equal(g.dragging, false);
  assert.equal(pickUps(), 0);
  clock.advance(1);
  assert.equal(g.dragging, true);
  assert.equal(pickUps(), 1);
  assert.equal(g.move(90, 120), "drag");
  assert.equal(g.release(), "drop");
});

test("a finger may tremble within the slop while holding", () => {
  const { g, clock } = gesture();
  g.press("touch", 50, 50);
  assert.equal(g.move(50 + TOUCH_SLOP_PX, 50), "none");
  clock.advance(HOLD_MS);
  assert.equal(g.dragging, true);
});

test("a finger that moves before the hold is up is a pan: the line is never picked up", () => {
  const { g, clock, pickUps } = gesture();
  g.press("touch", 50, 50);
  clock.advance(HOLD_MS / 2);
  assert.equal(g.move(50 + TOUCH_SLOP_PX + 1, 50), "none");
  assert.equal(g.active, false);
  clock.advance(HOLD_MS);
  assert.equal(pickUps(), 0);
  assert.equal(g.dragging, false);
  assert.equal(g.move(200, 200), "none");
  assert.equal(g.release(), "none");
});

test("a quick tap on the line is not a drag (the map's click handles it)", () => {
  const { g, clock, pickUps } = gesture();
  g.press("touch", 50, 50);
  clock.advance(100);
  assert.equal(g.release(), "none");
  clock.advance(HOLD_MS);
  assert.equal(pickUps(), 0);
});

test("picked up and let go on the spot drops nothing", () => {
  const { g, clock } = gesture();
  g.press("touch", 50, 50);
  clock.advance(HOLD_MS);
  g.move(51, 50);
  assert.equal(g.release(), "none");
});

test("cancel (Escape, a second finger) ends a drag and says one was under way", () => {
  const { g, clock, pickUps } = gesture();
  g.press("mouse", 0, 0);
  g.move(30, 0);
  assert.equal(g.cancel(), true);
  assert.equal(g.release(), "none");
  g.press("touch", 0, 0);
  assert.equal(g.cancel(), false);
  clock.advance(HOLD_MS * 2);
  assert.equal(pickUps(), 0, "a cancelled hold never picks up");
});

test("a new press replaces one still being followed", () => {
  const { g, clock, pickUps } = gesture();
  g.press("touch", 0, 0);
  g.press("mouse", 10, 10);
  clock.advance(HOLD_MS);
  assert.equal(pickUps(), 0);
  assert.equal(g.move(10 + MOUSE_SLOP_PX, 10), "drag");
});

test("with nothing pressed, moves and releases do nothing", () => {
  const { g } = gesture();
  assert.equal(g.move(10, 10), "none");
  assert.equal(g.release(), "none");
  assert.equal(g.cancel(), false);
});

test("a quick flick past the click tolerance and straight up is a drop", () => {
  const { g } = gesture();
  g.press("mouse", 100, 100);
  assert.equal(g.move(100 + MOUSE_SLOP_PX, 100), "drag");
  assert.equal(g.release(), "drop");
});

test("a finger that picked the line up may wobble as far as during the hold and still drop nothing", () => {
  const { g, clock } = gesture();
  g.press("touch", 50, 50);
  clock.advance(HOLD_MS);
  assert.equal(g.move(50 + TOUCH_SLOP_PX, 50), "drag");
  assert.equal(g.release(), "none");
});

test("a finger that picked the line up and moved past the slop drops a via", () => {
  const { g, clock } = gesture();
  g.press("touch", 50, 50);
  clock.advance(HOLD_MS);
  g.move(50 + TOUCH_SLOP_PX + 1, 50);
  g.move(52, 50); // back near the start: it has still moved
  assert.equal(g.release(), "drop");
});

test("a vertical move past the slop after the pick-up counts as moved too", () => {
  const { g, clock } = gesture();
  g.press("touch", 50, 50);
  clock.advance(HOLD_MS);
  g.move(50, 50 + TOUCH_SLOP_PX + 1);
  assert.equal(g.release(), "drop");
});
