import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  IDLE_CLOSE_ALWAYS,
  IDLE_CLOSE_ATTR,
  IDLE_CLOSE_SETTLE_MS,
  IDLE_HOLD_ATTR,
  IDLE_RECENTRE_MS,
  IDLE_TOUCH_EVENTS,
  RIDE_PANEL_OPEN,
  followZoom,
  closeIdlePanels,
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
  // See everyone's view (lib/seeEveryone.ts) is chosen: left alone, it stays.
  assert.match(app, /away: \(\) => \(!followNow\.current && !seeAllNow\.current\) \|\| movedByHand\.current/);
  assert.match(app, /panelOpen: \(\) => document\.querySelector\(RIDE_PANEL_OPEN\) !== null/);
  assert.match(app, /onRiderMoved=\{\(\) => \{\s+movedByHand\.current = true;\s+everyone\.stop\(\);\s+\}\}\s+followReset=\{followReset\}/);
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /followZoom\(reset, following\.current, map\.getZoom\(\), FOLLOW_ZOOM\)/);
  assert.match(map, /map\.on\("movestart", moved\);/);
  // The panels the ride's screen opens all show as expanded toggles there or in the group bar.
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  for (const open of ["detourOpen", "dockOpen", "menu311", "moreOpen"]) assert.match(ride, new RegExp(`aria-expanded=\\{${open}\\}`));
  // The ride's settings are a modal <dialog> (dialog[open] above), closed by the screen left alone too.
  assert.match(ride, /className="ask-dialog ride-settings-dialog"[^>]*data-idle-close/);
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

test("the map's Help panel open counts as a panel; folded to its i, it does not", () => {
  // MapLibre's compact credits: shown with maplibregl-compact-show, while `open` is on the details folded to the "i".
  assert.match(RIDE_PANEL_OPEN, /\.maplibregl-ctrl-attrib\.maplibregl-compact-show/);
  assert.doesNotMatch(RIDE_PANEL_OPEN, /ctrl-attrib\[open\]/);
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
  for (const open of ["detourOpen", "dockOpen", "menu311", "moreOpen"]) assert.match(ride, new RegExp(`aria-expanded=\\{${open}\\}\\s+aria-controls=\\{[^\\n]+\\}\\s+${IDLE_CLOSE_ATTR}`));
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

/** A fake page element: children, attributes, and what a press or close does. */
class FakeEl {
  children: FakeEl[] = [];
  parent: FakeEl | null = null;
  attrs: Record<string, string> = {};
  value?: string;
  textContent = "";
  presses = 0;
  closes = 0;
  focused = 0;
  tag: string;
  cls: string[];
  onPress?: (el: FakeEl) => void;
  constructor(tag: string, cls: string[] = [], attrs: Record<string, string> = {}, onPress?: (el: FakeEl) => void) {
    this.tag = tag;
    this.cls = cls;
    this.attrs = attrs;
    this.onPress = onPress;
  }
  add(...kids: FakeEl[]) {
    for (const kid of kids) (kid.parent = this), this.children.push(kid);
    return this;
  }
  all(): FakeEl[] {
    return this.children.flatMap((kid) => [kid, ...kid.all()]);
  }
  contains(other: unknown): boolean {
    return other === this || this.all().includes(other as FakeEl);
  }
  closest(sel: string): FakeEl | null {
    for (let at: FakeEl | null = this; at; at = at.parent) if (at.cls.includes(sel.slice(1))) return at;
    return null;
  }
  getAttribute(name: string) {
    return this.attrs[name] ?? null;
  }
  querySelector(sel: string) {
    return this.querySelectorAll(sel)[0] ?? null;
  }
  querySelectorAll(sel: string): FakeEl[] {
    const els = this.all();
    if (sel === MAP_CARD) return els.filter((e) => e.cls.includes("maplibregl-popup-close-button") && e.closest(".maplibregl-popup"));
    if (sel === `[${IDLE_HOLD_ATTR}]`) return els.filter((e) => IDLE_HOLD_ATTR in e.attrs);
    if (sel === `[${IDLE_CLOSE_ATTR}][aria-expanded="true"]`) return els.filter((e) => IDLE_CLOSE_ATTR in e.attrs && e.attrs["aria-expanded"] === "true");
    if (sel === `dialog[open][${IDLE_CLOSE_ATTR}]`) return els.filter((e) => e.tag === "dialog" && "open" in e.attrs && IDLE_CLOSE_ATTR in e.attrs);
    if (sel.startsWith("input")) return els.filter((e) => e.tag === "input");
    return [];
  }
  click() {
    this.presses += 1;
    this.onPress?.(this);
  }
  close() {
    this.closes += 1;
    delete this.attrs.open;
  }
  focus() {
    this.focused += 1;
  }
}
const MAP_CARD = ".maplibregl-popup .maplibregl-popup-close-button";

test("closeIdlePanels: each card, menu and dialog closes by its own close; typed words, a hold and unmarked questions stay", () => {
  const body = new FakeEl("body");
  const canvas = new FakeEl("canvas", ["maplibregl-canvas"]);
  const cardX = new FakeEl("button", ["maplibregl-popup-close-button"], {}, (x) => x.parent!.parent!.children.splice(0));
  const card = new FakeEl("div", ["maplibregl-popup"]).add(new FakeEl("div", ["maplibregl-popup-content"]).add(cardX));
  const detourPanel = new FakeEl("div", [], { id: "detour" }).add(new FakeEl("button"), Object.assign(new FakeEl("input"), { value: "" }));
  const detour = new FakeEl("button", [], { [IDLE_CLOSE_ATTR]: "", "aria-expanded": "true", "aria-controls": "detour" }, (t) => (t.attrs["aria-expanded"] = "false"));
  const alertPanel = new FakeEl("div", [], { id: "alert" }).add(Object.assign(new FakeEl("input"), { value: "flat tyre" }));
  const alert = new FakeEl("button", [], { [IDLE_CLOSE_ATTR]: "", "aria-expanded": "true", "aria-controls": "alert" });
  const ridersPanel = new FakeEl("div", [], { id: "riders" }).add(new FakeEl("div", [], { [IDLE_HOLD_ATTR]: "" }));
  const riders = new FakeEl("button", [], { [IDLE_CLOSE_ATTR]: "", "aria-expanded": "true", "aria-controls": "riders" });
  const info = new FakeEl("dialog", [], { open: "", [IDLE_CLOSE_ATTR]: "" });
  const question = new FakeEl("dialog", [], { open: "" });
  body.add(canvas, card, detour, detourPanel, alert, alertPanel, riders, ridersPanel, info, question);
  const inDetour = detourPanel.children[0];
  let active: FakeEl = inDetour;
  const doc = {
    body,
    get activeElement() {
      return active;
    },
    querySelector: (sel: string) => (sel === ".maplibregl-canvas" ? canvas : body.querySelector(sel)),
    querySelectorAll: (sel: string) => body.querySelectorAll(sel),
    getElementById: (id: string) => body.all().find((e) => e.attrs.id === id) ?? null,
  } as unknown as Document;
  assert.equal(closeIdlePanels(doc), true);
  assert.equal(cardX.presses, 1);
  assert.equal(detour.presses, 1);
  assert.equal(detour.focused, 1, "the focus was in Detour: it goes to Detour's toggle");
  assert.equal(alert.presses, 0, "words typed keep Alert open");
  assert.equal(riders.presses, 0, "a hold keeps the menu open");
  assert.equal(info.closes, 1);
  assert.equal(question.closes, 0);
  assert.equal(canvas.focused, 0);
  // Nothing left to close: says so, and a second look closes nothing more.
  active = body;
  assert.equal(closeIdlePanels(doc), false);
});

test("a dialog with the focus in it (Ride settings, the join sheet) stays open when the screen is left alone; the group's question still closes", () => {
  const body = new FakeEl("body");
  const pickerInSettings = new FakeEl("select");
  const settings = new FakeEl("dialog", [], { open: "", [IDLE_CLOSE_ATTR]: "" }).add(pickerInSettings);
  const join = new FakeEl("dialog", [], { open: "", [IDLE_CLOSE_ATTR]: "" }).add(new FakeEl("button"));
  body.add(settings, join);
  let active: FakeEl = pickerInSettings;
  const doc = {
    body,
    get activeElement() {
      return active;
    },
    querySelector: (sel: string) => body.querySelector(sel),
    querySelectorAll: (sel: string) => body.querySelectorAll(sel),
    getElementById: () => null,
  } as unknown as Document;
  assert.equal(closeIdlePanels(doc), true, "the join sheet, without the focus, closes");
  assert.equal(settings.closes, 0, "Ride settings, with the focus in it, stays");
  assert.equal(join.closes, 1);
  // The group's question closes as its No even with the focus on its first button.
  const first = new FakeEl("button");
  const question = new FakeEl("dialog", [], { open: "", [IDLE_CLOSE_ATTR]: IDLE_CLOSE_ALWAYS }).add(first);
  body.add(question);
  active = first;
  assert.equal(closeIdlePanels(doc), true);
  assert.equal(question.closes, 1);
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  assert.match(group, new RegExp(`className="ask-dialog ride-consent"\\s+${IDLE_CLOSE_ATTR}="${IDLE_CLOSE_ALWAYS}"`));
});

test("the focus moving (a screen reader's swipe) starts the 30 s again, like a touch", () => {
  assert.ok((IDLE_TOUCH_EVENTS as readonly string[]).includes("focusin"));
  const w = fakeWindow();
  let closes = 0;
  watchIdleRecentre(w.win, { away: () => false, panelOpen: () => true, recentre: () => undefined, closePanels: () => ((closes += 1), true) });
  w.advance(25_000);
  w.touch("focusin");
  w.advance(25_000);
  assert.equal(closes, 0);
  w.advance(5_000);
  assert.equal(closes, 1);
});

test("an idle close that moves the focus leaves no 30 s running: a menu opened later gets its full 30 s from the last touch", () => {
  const w = fakeWindow();
  let closes = 0;
  watchIdleRecentre(w.win, {
    away: () => false,
    panelOpen: () => false,
    recentre: () => undefined,
    // Closing a menu that held the focus hands it to the toggle: a focusin.
    closePanels: () => ((closes += 1), w.touch("focusin"), true),
  });
  w.advance(IDLE_RECENTRE_MS);
  assert.equal(closes, 1);
  // The rider opens another menu at 40 s and touches it at 45 s and 55 s.
  w.advance(10_000);
  w.touch();
  w.advance(5_000);
  w.touch();
  w.advance(10_000);
  w.touch();
  w.advance(IDLE_RECENTRE_MS - 1);
  assert.equal(closes, 1, "nothing closes before 30 s after the last touch");
  w.advance(1);
  assert.equal(closes, 2);
});

test("a map card or side menu with a key's or screen reader's focus shown in it stays open; a tap's focus does not hold it", () => {
  const body = new FakeEl("body");
  const shown = (el: FakeEl) => Object.assign(el, { matches: (sel: string) => sel === ":focus-visible" });
  const inCard = new FakeEl("button");
  const cardX = new FakeEl("button", ["maplibregl-popup-close-button"], {}, (x) => x.parent!.children.splice(0));
  const card = new FakeEl("div", ["maplibregl-popup"]).add(cardX);
  const inMenu = new FakeEl("button");
  const menu = new FakeEl("div", [], { id: "more" }).add(inMenu);
  const more = new FakeEl("button", [], { [IDLE_CLOSE_ATTR]: "", "aria-expanded": "true", "aria-controls": "more" }, (t) => (t.attrs["aria-expanded"] = "false"));
  body.add(card, more, menu);
  let active: FakeEl = shown(inMenu);
  const doc = {
    body,
    get activeElement() {
      return active;
    },
    querySelector: (sel: string) => body.querySelector(sel),
    querySelectorAll: (sel: string) => body.querySelectorAll(sel),
    getElementById: (id: string) => body.all().find((e) => e.attrs.id === id) ?? null,
  } as unknown as Document;
  closeIdlePanels(doc);
  assert.equal(more.presses, 0, "the menu with the focus shown stays");
  assert.equal(cardX.presses, 1, "the card without the focus closes");
  active = shown(inCard);
  const card2X = new FakeEl("button", ["maplibregl-popup-close-button"]);
  body.add(new FakeEl("div", ["maplibregl-popup"]).add(inCard, card2X));
  closeIdlePanels(doc);
  assert.equal(card2X.presses, 0, "the card with the focus shown stays");
  assert.equal(more.presses, 1, "the menu, the focus now elsewhere, closes");
  // A finger's tap focuses without showing it: the menu still closes, and the focus goes to its toggle.
  more.attrs["aria-expanded"] = "true";
  active = new FakeEl("button");
  menu.add(active);
  closeIdlePanels(doc);
  assert.equal(more.presses, 2);
  assert.equal(more.focused, 1);
});
