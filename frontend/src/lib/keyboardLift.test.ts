// The on-screen keyboard over the bottom sheet (review UI-7): Android resizes the page, iOS lifts the app.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { keyboardLift, watchKeyboard, type LiftWindow } from "./keyboardLift.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

function fakeWindow(innerHeight: number) {
  const listeners = new Set<() => void>();
  const view = {
    height: innerHeight,
    offsetTop: 0,
    scale: 1,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  const win: LiftWindow = { innerHeight, visualViewport: view };
  const props = new Map<string, string>();
  const root = { style: { setProperty: (name: string, value: string) => props.set(name, value), removeProperty: (name: string) => String(props.delete(name)) } };
  return { win, view, listeners, props, root };
}

test("the lift is the part of the page below the visual viewport", () => {
  assert.equal(keyboardLift({ innerHeight: 800 }), 0, "no visualViewport: no lift");
  const { win, view } = fakeWindow(800);
  assert.equal(keyboardLift(win), 0);
  view.height = 460;
  assert.equal(keyboardLift(win), 340);
  view.offsetTop = 40;
  assert.equal(keyboardLift(win), 300, "iOS panned the view up to the box");
});

test("no lift while pinch-zoomed: the smaller visual viewport is the zoom, not a keyboard", () => {
  const { win, view, props, root } = fakeWindow(800);
  view.height = 400;
  view.scale = 2;
  assert.equal(keyboardLift(win), 0);
  const stop = watchKeyboard(win, root);
  assert.equal(props.has("--keyboard-lift"), false);
  view.scale = 1;
  view.height = 460;
  assert.equal(keyboardLift(win), 340, "back at 1, the keyboard lifts again");
  stop();
});

test("the watch sets --keyboard-lift while the keyboard is up and takes it off when stopped", () => {
  const { win, view, listeners, props, root } = fakeWindow(800);
  const stop = watchKeyboard(win, root as never);
  assert.equal(props.has("--keyboard-lift"), false);
  view.height = 480;
  for (const listener of listeners) listener();
  assert.equal(props.get("--keyboard-lift"), "320px");
  stop();
  assert.equal(props.has("--keyboard-lift"), false);
  assert.equal(listeners.size, 0);
});

test("wiring: Android resizes the page, a phone's place search lifts the app, the app is shortened by the lift", () => {
  assert.match(read("../../index.html"), /<meta name="viewport" content="width=device-width, initial-scale=1, interactive-widget=resizes-content" \/>/);
  const search = read("../PlaceSearch.tsx");
  assert.match(search, /keyboardWatch\.current = watchKeyboard\(window, document\.documentElement\)/);
  assert.match(search, /onBlur=\{\(\) => \{\s*setOpen\(false\);\s*stopKeyboardWatch\(\);/);
  assert.match(read("../styles.css"), /\.app \{\s*height: calc\(100% - var\(--keyboard-lift, 0px\)\);/);
});

test("a reading between the two heights' steps does not stick: the window's resize and a settle re-read fix it", () => {
  const { win, view, listeners, props, root } = fakeWindow(800);
  const winListeners = new Set<() => void>();
  const timers = new Map<number, () => void>();
  let nextTimer = 1;
  Object.assign(win, {
    addEventListener: (_type: string, listener: () => void) => winListeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => winListeners.delete(listener),
    setTimeout: (handler: () => void) => {
      timers.set(nextTimer, handler);
      return nextTimer++;
    },
    clearTimeout: (id: number) => timers.delete(id),
  });
  const fire = (set: Iterable<() => void>) => {
    for (const listener of [...set]) listener();
  };
  const runTimers = () => {
    const due = [...timers.values()];
    timers.clear();
    for (const handler of due) handler();
  };
  const stop = watchKeyboard(win, root);
  // Keyboard opens: the visual viewport shrinks first (one event), the page shrinks after it with no visual event.
  view.height = 460;
  fire(listeners);
  assert.equal(props.get("--keyboard-lift"), "340px", "for that moment it looks like iOS");
  (win as { innerHeight: number }).innerHeight = 460;
  fire(winListeners);
  assert.equal(props.has("--keyboard-lift"), false, "the window's resize puts it right");
  // Keyboard closes with the box still focused: the last visual event comes mid-way, the rest lands without one.
  (win as { innerHeight: number }).innerHeight = 800;
  view.height = 460;
  fire(listeners);
  assert.equal(props.get("--keyboard-lift"), "340px");
  view.height = 800;
  runTimers();
  assert.equal(props.has("--keyboard-lift"), false, "the settle re-read takes the lift off");
  stop();
  assert.equal(winListeners.size, 0);
  assert.equal(timers.size, 0);
});
