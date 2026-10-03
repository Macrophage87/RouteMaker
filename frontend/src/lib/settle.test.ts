// One plan per slider release and one announcement per route (a11y review of
// integrate-2), on a clock the test drives.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ANNOUNCE_SETTLE_MS, Debounce, KEY_SETTLE_MS, SettledText, type Clock } from "./settle.ts";

function fakeClock() {
  let now = 0;
  let next = 1;
  const timers = new Map<number, { at: number; run: () => void }>();
  const clock: Clock = {
    set: (run, ms) => {
      const id = next++;
      timers.set(id, { at: now + ms, run });
      return id;
    },
    clear: (handle) => {
      timers.delete(handle as number);
    },
  };
  const advance = (ms: number) => {
    const until = now + ms;
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      now = due[1].at;
      due[1].run();
    }
    now = until;
  };
  return { clock, advance, pending: () => timers.size };
}

test("five key presses in a row plan once, after the keys rest", () => {
  const { clock, advance } = fakeClock();
  const keys = new Debounce(KEY_SETTLE_MS, clock);
  let plans = 0;
  for (let i = 0; i < 5; i++) {
    keys.later(() => plans++);
    advance(KEY_SETTLE_MS - 100);
  }
  assert.equal(plans, 0, "still pressing");
  assert.equal(keys.pending, true);
  advance(100);
  assert.equal(plans, 1);
  assert.equal(keys.pending, false);
  advance(KEY_SETTLE_MS * 3);
  assert.equal(plans, 1, "and only once");
});

test("a pointer let go, or the focus leaving, plans at once and drops a key's pending plan", () => {
  const { clock, advance, pending } = fakeClock();
  const keys = new Debounce(KEY_SETTLE_MS, clock);
  const said: string[] = [];
  keys.later(() => said.push("key"));
  keys.now(() => said.push("blur"));
  assert.deepEqual(said, ["blur"]);
  assert.equal(pending(), 0);
  advance(KEY_SETTLE_MS * 2);
  assert.deepEqual(said, ["blur"], "the key's plan does not follow");
  keys.later(() => said.push("late"));
  keys.cancel();
  advance(KEY_SETTLE_MS * 2);
  assert.deepEqual(said, ["blur"]);
});

test("a route's sentence is said once it stands; routes that replace each other quickly are said once, the last", () => {
  const { clock, advance } = fakeClock();
  const shown: string[] = [];
  const live = new SettledText(ANNOUNCE_SETTLE_MS, (text) => shown.push(text), clock);
  live.offer("Route A");
  advance(ANNOUNCE_SETTLE_MS - 1);
  assert.deepEqual(shown, []);
  live.offer("");
  live.offer("Route B");
  advance(ANNOUNCE_SETTLE_MS);
  assert.deepEqual(shown, ["", "Route B"], "A is never said; clearing is at once");
});

test("the same sentence after a new plan is said again: it is cleared in between", () => {
  const { clock, advance } = fakeClock();
  const shown: string[] = [];
  const live = new SettledText(ANNOUNCE_SETTLE_MS, (text) => shown.push(text), clock);
  live.offer("Route A");
  advance(ANNOUNCE_SETTLE_MS);
  live.offer("");
  live.offer("Route A");
  advance(ANNOUNCE_SETTLE_MS);
  assert.deepEqual(shown, ["Route A", "", "Route A"]);
  live.offer("Route C");
  live.cancel();
  advance(ANNOUNCE_SETTLE_MS * 2);
  assert.deepEqual(shown, ["Route A", "", "Route A"], "cancelled on unmount");
});

test("the waits are short enough to feel at once and long enough to fold a burst", () => {
  assert.ok(KEY_SETTLE_MS >= 400 && KEY_SETTLE_MS <= 1000);
  assert.ok(ANNOUNCE_SETTLE_MS >= 400 && ANNOUNCE_SETTLE_MS <= 1000);
});
