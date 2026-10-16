// A back gesture during a ride does nothing (review RIDE-2), against a stand-in history.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { holdBackDuringRide, type BackWindow } from "./rideBack.ts";

function fakeWindow() {
  const entries: unknown[] = [null];
  let index = 0;
  const listeners = new Set<() => void>();
  const win: BackWindow = {
    history: {
      get state() {
        return entries[index];
      },
      pushState: (state: unknown) => {
        entries.splice(index + 1, Infinity, state);
        index += 1;
      },
      back: () => {
        if (index === 0) return;
        index -= 1;
        for (const listener of [...listeners]) listener();
      },
    } as BackWindow["history"],
    location: { href: "https://example.test/#plan" },
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
  };
  return { win, entries: () => entries.slice(0, index + 1), listeners };
}

test("Start ride pushes the ride's entry; a back while riding stays; End takes the entry off", () => {
  const { win, entries, listeners } = fakeWindow();
  const release = holdBackDuringRide(win);
  assert.equal(entries().length, 2);
  // The rider's back gesture: the page stays, with the ride's entry on top again.
  win.history.back();
  assert.equal(entries().length, 2);
  assert.deepEqual(win.history.state, { routemakerRide: true });
  release();
  assert.equal(listeners.size, 0);
  assert.deepEqual(entries(), [null], "the history as before the ride");
});

test("an entry the page replaced during the ride is not taken off at End", () => {
  const { win, entries } = fakeWindow();
  const release = holdBackDuringRide(win);
  (win.history as unknown as { pushState: (s: unknown) => void }).pushState(null);
  release();
  assert.equal(entries().length, 3);
});

test("App holds the back gesture for exactly the ride", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /useEffect\(\(\) => \(riding \? holdBackDuringRide\(window\) : undefined\), \[riding\]\);/);
});
