// One shared 5-minute clock for the background checks (the owner, 2026-11-01: battery audit).
import { test } from "node:test";
import assert from "node:assert/strict";
import { TICK_MS, boundaryAt, createSharedTick, msToNextBoundary, type TickEnv } from "./sharedTick.ts";

function fakeEnv(start: number) {
  let now = start;
  let hidden = false;
  let nextId = 0;
  const timers = new Map<number, { at: number; fn: () => void }>();
  const listeners = new Set<() => void>();
  const env: TickEnv = {
    now: () => now,
    setTimeout: (fn, ms) => {
      nextId += 1;
      timers.set(nextId, { at: now + ms, fn });
      return nextId;
    },
    clearTimeout: (id) => void timers.delete(id as number),
    hidden: () => hidden,
    onVisibility: (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
  const advance = (ms: number) => {
    const until = now + ms;
    for (;;) {
      const due = [...timers].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      now = due[1].at;
      due[1].fn();
    }
    now = until;
  };
  const setHidden = (h: boolean) => {
    hidden = h;
    for (const fn of [...listeners]) fn();
  };
  return { env, advance, setHidden, timers, listeners };
}

const T0 = Date.UTC(2026, 10, 1, 12, 0, 0);

test("boundaries are the wall clock's 5 minutes", () => {
  assert.equal(TICK_MS, 5 * 60_000);
  assert.equal(boundaryAt(T0 + 61_000), T0);
  assert.equal(msToNextBoundary(T0 + 61_000), TICK_MS - 61_000);
  assert.equal(msToNextBoundary(T0), TICK_MS);
});

test("checks started at different times are called together on the same boundary, so the radio wakes once", () => {
  const { env, advance } = fakeEnv(T0 + 30_000);
  const tick = createSharedTick(env);
  const calls: string[] = [];
  tick.subscribe(() => calls.push(`weather@${env.now()}`));
  advance(90_000);
  tick.subscribe(() => calls.push(`closures@${env.now()}`));
  advance(60_000);
  tick.subscribe(() => calls.push(`rail@${env.now()}`));
  advance(TICK_MS);
  const at = T0 + TICK_MS + 5;
  assert.deepEqual(calls, [`weather@${at}`, `closures@${at}`, `rail@${at}`]);
  advance(TICK_MS);
  assert.equal(calls.length, 6);
});

test("hidden in a browser: no timer at all, and a catch-up subscriber runs as the page comes back", () => {
  const { env, advance, setHidden } = fakeEnv(T0 + 1_000);
  const tick = createSharedTick(env);
  const calls: string[] = [];
  tick.subscribe(() => calls.push("weather"), { catchUp: true });
  tick.subscribe(() => calls.push("closures"));
  setHidden(true);
  assert.equal(tick.armed(), false, "nothing wakes the page while hidden");
  advance(3 * TICK_MS);
  assert.deepEqual(calls, []);
  setHidden(false);
  assert.deepEqual(calls, ["weather"], "the missed weather check runs at once; closures check on their own");
  assert.equal(tick.armed(), true);
  advance(TICK_MS);
  assert.deepEqual(calls, ["weather", "weather", "closures"]);
});

test("the app's ride weather runs on with the screen locked; the others wait", () => {
  const { env, advance, setHidden } = fakeEnv(T0 + 1_000);
  const tick = createSharedTick(env);
  const calls: string[] = [];
  tick.subscribe(() => calls.push("ride weather"), { whileHidden: () => true });
  tick.subscribe(() => calls.push("rail"), { catchUp: true });
  setHidden(true);
  assert.equal(tick.armed(), true);
  advance(TICK_MS);
  assert.deepEqual(calls, ["ride weather"]);
  setHidden(false);
  assert.deepEqual(calls, ["ride weather", "rail"]);
});

test("the last unsubscribe clears the timer and the visibility listener", () => {
  const { env, listeners } = fakeEnv(T0);
  const tick = createSharedTick(env);
  const off1 = tick.subscribe(() => undefined);
  const off2 = tick.subscribe(() => undefined);
  off1();
  assert.equal(tick.armed(), true);
  off2();
  assert.equal(tick.armed(), false);
  assert.equal(listeners.size, 0);
  assert.equal(tick.size(), 0);
});
