import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  IDLE_CLOSE_ATTR,
  IDLE_CLOSE_SETTLE_MS,
  IDLE_HOLD_ATTR,
  IDLE_RECENTRE_MS,
  IDLE_TOUCH_EVENTS,
  RIDE_PANEL_OPEN,
  followZoom,
  typingIn,
  watchIdleRecentre,
  type IdleWindow,
} from "./idleRecentre.ts";

/** A window with a clock that moves only when told. */
function fakeWindow() {
  let now = 0;
  let next = 1;
  const timers = new Map<number, { at: number; run: () => void }>();
  const listeners = new Map<string, Set<() => void>>();
  const win: IdleWindow = {
    addEventListener: (type, listener) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)!.add(listener);
    },
    removeEventListener: (type, listener) => listeners.get(type)?.delete(listener),
    setTimeout: (run, ms) => {
      timers.set(next, { at: now + ms, run });
      return next++;
    },
    clearTimeout: (id) => void timers.delete(id),
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
  const touch = (type: string = "pointerdown") => listeners.get(type)?.forEach((listener) => listener());
  return { win, advance, touch, listening: () => [...listeners.values()].reduce((n, set) => n + set.size, 0), timers };
}

test("the screen left alone 30 s after the map was moved by hand: the map goes back to the rider", () => {
  assert.equal(IDLE_RECENTRE_MS, 30_000);
  const w = fakeWindow();
  let away = true;
  let recentred = 0;
  watchIdleRecentre(w.win, { away: () => away, panelOpen: () => false, recentre: () => ((recentred += 1), (away = false)) });
  w.advance(29_999);
  assert.equal(recentred, 0);
  w.advance(1);
  assert.equal(recentred, 1);
  // Back on the rider, nothing more happens however long it is left.
  w.advance(5 * 60_000);
  assert.equal(recentred, 1);
});

test("each touch, lift, wheel or key starts the 30 s again", () => {
  const w = fakeWindow();
  let recentred = 0;
  watchIdleRecentre(w.win, { away: () => true, panelOpen: () => false, recentre: () => (recentred += 1) });
  for (const type of IDLE_TOUCH_EVENTS) {
    w.advance(20_000);
    w.touch(type);
  }
  assert.equal(recentred, 0);
  w.advance(29_000);
  assert.equal(recentred, 0);
  w.advance(1_000);
  assert.equal(recentred, 1);
});

test("an open panel holds the map where it is; once it closes, the next 30 s put it back", () => {
  const w = fakeWindow();
  let panel = true;
  let recentred = 0;
  watchIdleRecentre(w.win, { away: () => true, panelOpen: () => panel, recentre: () => (recentred += 1) });
  w.advance(90_000);
  assert.equal(recentred, 0);
  panel = false;
  w.advance(30_000);
  assert.equal(recentred, 1);
});

test("following, unmoved: the map is left alone", () => {
  const w = fakeWindow();
  let recentred = 0;
  watchIdleRecentre(w.win, { away: () => false, panelOpen: () => false, recentre: () => (recentred += 1) });
  w.advance(10 * 60_000);
  assert.equal(recentred, 0);
});

test("the ride over: no listener and no timer is left", () => {
  const w = fakeWindow();
  const stop = watchIdleRecentre(w.win, { away: () => true, panelOpen: () => false, recentre: () => assert.fail("recentred after the ride") });
  assert.equal(w.listening(), IDLE_TOUCH_EVENTS.length);
  stop();
  assert.equal(w.listening(), 0);
  assert.equal(w.timers.size, 0);
  w.advance(60_000);
});

test("wired: a ride or Roam watches, a move by hand marks the map away, and the reset takes the zoom back", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(!onBike\) return undefined;\s+movedByHand\.current = false;\s+return watchIdleRecentre\(window,/);
  assert.match(app, /away: \(\) => !followNow\.current \|\| movedByHand\.current/);
  assert.match(app, /panelOpen: \(\) => document\.querySelector\(RIDE_PANEL_OPEN\) !== null/);
  assert.match(app, /onRiderMoved=\{\(\) => \(movedByHand\.current = true\)\}\s+followReset=\{followReset\}/);
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /followZoom\(reset, following\.current, map\.getZoom\(\), FOLLOW_ZOOM\)/);
  assert.match(map, /map\.on\("movestart", moved\);/);
  // The panels the ride's screen opens all show as expanded toggles there or in the group bar.
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  for (const open of ["detourOpen", "dockOpen", "menu311", "settingsOpen"]) assert.match(ride, new RegExp(`aria-expanded=\\{${open}\\}`));
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  for (const open of ["ridersOpen", "alertOpen"]) assert.match(group, new RegExp(`aria-expanded=\\{${open}\\}`));
  assert.match(RIDE_PANEL_OPEN, /\.ride \[aria-expanded="true"\]/);
  assert.match(RIDE_PANEL_OPEN, /\.ride-group \[aria-expanded="true"\]/);
});

test("the follow camera's zoom: back to the ride's own after a reset, a pinch kept while following, closed in as it starts", () => {
  // A pinch out to 13 while following, then the screen left alone: back to 16; a pinch in to 18 too.
  assert.equal(followZoom(true, true, 13, 16), 16);
  assert.equal(followZoom(true, false, 18, 16), 16);
  // Following, no reset: the rider's pinch is kept.
  assert.equal(followZoom(false, true, 13, 16), 13);
  // Following starts (Where am I?): closed in to at least 16, a closer view kept.
  assert.equal(followZoom(false, false, 12, 16), 16);
  assert.equal(followZoom(false, false, 17.5, 16), 17.5);
});

test("the map's Help panel open counts as a panel", () => {
  assert.match(RIDE_PANEL_OPEN, /\.maplibregl-ctrl-attrib\[open\]/);
});

test("the screen left alone 30 s: the cards and side menus close, then the map goes back to the rider", () => {
  const w = fakeWindow();
  const steps: string[] = [];
  let open = true;
  watchIdleRecentre(w.win, {
    away: () => true,
    panelOpen: () => open,
    closePanels: () => {
      if (!open) return false;
      steps.push("closed");
      open = false;
      return true;
    },
    recentre: () => steps.push("recentred"),
  });
  w.advance(29_999);
  assert.deepEqual(steps, []);
  w.advance(1);
  assert.deepEqual(steps, ["closed"]);
  // The menu is given a moment to leave the page, then the map is put back.
  w.advance(IDLE_CLOSE_SETTLE_MS);
  assert.deepEqual(steps, ["closed", "recentred"]);
});

test("a touch while a card is open starts its 30 s again", () => {
  const w = fakeWindow();
  let closed = 0;
  watchIdleRecentre(w.win, { away: () => false, panelOpen: () => true, closePanels: () => ((closed += 1), true), recentre: () => undefined });
  w.advance(25_000);
  w.touch("pointerup");
  w.advance(25_000);
  assert.equal(closed, 0);
  w.advance(5_000);
  assert.equal(closed, 1);
});

test("a menu kept open (words typed): nothing closes and the map stays held, looked at again each 30 s", () => {
  const w = fakeWindow();
  let asked = 0;
  let recentred = 0;
  watchIdleRecentre(w.win, { away: () => true, panelOpen: () => true, closePanels: () => ((asked += 1), false), recentre: () => (recentred += 1) });
  w.advance(90_000);
  assert.equal(asked, 3);
  assert.equal(recentred, 0);
});

test("following, nothing open: closing is still asked, and the map is left alone", () => {
  const w = fakeWindow();
  let recentred = 0;
  watchIdleRecentre(w.win, { away: () => false, panelOpen: () => false, closePanels: () => false, recentre: () => (recentred += 1) });
  w.advance(60_000);
  assert.equal(recentred, 0);
});

/** An element with only what typingIn reads. */
function box(fields: { value?: string; text?: string }[], hold = false) {
  const made = fields.map((f) => (f.value !== undefined ? { value: f.value } : { textContent: f.text ?? "" }));
  return {
    made,
    el: {
      querySelector: (sel: string) => (sel === `[${IDLE_HOLD_ATTR}]` && hold ? {} : null),
      querySelectorAll: () => made,
    } as unknown as Element,
  };
}

test("words typed, being typed, or the microphone listening keep a menu open", () => {
  assert.equal(typingIn(box([]).el, null), false);
  assert.equal(typingIn(box([{ value: "" }, { value: "  " }]).el, null), false);
  assert.equal(typingIn(box([{ value: "coffee" }]).el, null), true);
  const empty = box([{ value: "" }]);
  assert.equal(typingIn(empty.el, empty.made[0] as unknown as Element), true);
  assert.equal(typingIn(box([{ text: "note" }]).el, null), true);
  assert.equal(typingIn(box([], true).el, null), true);
});

test("wired: the ride's side menus, the group's, Roam's Detour and the road info are marked to close; accessibility mode closes nothing", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /closePanels: \(\) => !accessModeNow\.current && closeIdlePanels\(document\)/);
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  for (const open of ["detourOpen", "dockOpen", "menu311", "settingsOpen"]) assert.match(ride, new RegExp(`aria-expanded=\\{${open}\\}\\s+aria-controls=\\{[^\\n]+\\}\\s+${IDLE_CLOSE_ATTR}`));
  const roam = readFileSync(new URL("../RoamMode.tsx", import.meta.url), "utf8");
  assert.match(roam, new RegExp(`aria-expanded=\\{detourOpen\\}\\s+aria-controls=\\{detourId\\}\\s+${IDLE_CLOSE_ATTR}`));
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  for (const open of ["ridersOpen", "alertOpen"]) assert.match(group, new RegExp(`aria-expanded=\\{${open}\\} ${IDLE_CLOSE_ATTR}`));
  assert.match(group, new RegExp(`aria-pressed=\\{listening\\} onClick=\\{speak\\} ${IDLE_HOLD_ATTR}=\\{listening \\|\\| undefined\\}`));
  const info = readFileSync(new URL("../RoadInfoDialog.tsx", import.meta.url), "utf8");
  assert.match(info, new RegExp(`${IDLE_CLOSE_ATTR}=\\{editing \\|\\| suggesting \\|\\| suggestingJunction \\|\\| reporting \\|\\| closing \\? undefined : ""\\}`));
});

test("a map card's X is a finger's size", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  const rule = css.match(/\.maplibregl-popup \.maplibregl-popup-close-button \{([^}]*)\}/);
  assert.ok(rule);
  assert.match(rule[1], /width: 44px;/);
  assert.match(rule[1], /height: 44px;/);
});
