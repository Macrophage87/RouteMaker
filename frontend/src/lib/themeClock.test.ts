import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { solarDay } from "./lightTimes.ts";
import { COVERAGE_CENTRE } from "./plusCode.ts";
import type { KeyValueStore } from "./accessMode.ts";
import {
  THEME_BAR,
  THEME_CHOICES,
  THEME_DARK_CLASS,
  THEME_EVENT,
  THEME_KEY,
  THEME_LIGHT_CLASS,
  applyTheme,
  chooseTheme,
  followTheme,
  readThemeChoice,
  sunDownAt,
  themeDarkFor,
  themeIsDark,
  themeWait,
  writeThemeChoice,
} from "./themeClock.ts";
import { mapFlavourFor } from "./mapFlavour.ts";

// The owner, 2026-11-01: "Set the default color mode to adjust by time of day", then "do sunrise/sunset", then "There's
// the ability to use whatever setting you want still?" (Settings > Display > Colors).
const DAY = solarDay(Date.UTC(2026, 10, 1, 17), COVERAGE_CENTRE[1], COVERAGE_CENTRE[0]);
const NOON = Date.UTC(2026, 10, 1, 17);
const NIGHT = DAY.sunset! + 60 * 60_000;

function memory(start: Record<string, string> = {}): KeyValueStore & { data: Map<string, string> } {
  const data = new Map(Object.entries(start));
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}
const refusing: KeyValueStore = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
};

function fakePage() {
  const classes = new Set<string>();
  const metas = [new Map<string, string>([["media", "(prefers-color-scheme: light)"]]), new Map<string, string>()];
  const listeners: Array<() => void> = [];
  return {
    classes,
    metas,
    listeners,
    visibilityState: "visible",
    documentElement: { classList: { contains: (n: string) => classes.has(n), toggle: (n: string, on: boolean) => (on ? classes.add(n) : classes.delete(n)) } },
    querySelectorAll: () => metas.map((m) => ({ setAttribute: (k: string, v: string) => m.set(k, v), removeAttribute: (k: string) => m.delete(k) })),
    addEventListener: (_: "visibilitychange", f: () => void) => listeners.push(f),
  };
}

function fakeWindow() {
  const events: string[] = [];
  const timers: number[] = [];
  const cleared: number[] = [];
  return {
    events,
    timers,
    cleared,
    win: {
      setTimeout: ((_: () => void, ms: number) => timers.push(ms)) as never,
      clearTimeout: ((id: number) => cleared.push(id)) as never,
      dispatchEvent: ((e: Event) => events.push(e.type)) as never,
    },
  };
}

function fakePhone(dark: boolean) {
  const listeners: Array<() => void> = [];
  return { matches: dark, listeners, addEventListener: (_: "change", f: () => void) => listeners.push(f) };
}

test("the sun is down from sunset to sunrise, not civil dawn and dusk", () => {
  assert.ok(DAY.sunrise && DAY.sunset && DAY.civil_dawn && DAY.civil_dusk);
  assert.equal(sunDownAt(DAY.sunrise! + 60_000), false);
  assert.equal(sunDownAt(DAY.sunset! - 60_000), false);
  assert.equal(sunDownAt(DAY.sunset! + 60_000), true, "just after sunset, before civil dusk");
  assert.ok(DAY.sunset! + 60_000 < DAY.civil_dusk!);
  assert.equal(sunDownAt(DAY.sunrise! - 60_000), true, "just before sunrise, after civil dawn");
});

test("Colors: the sun by default, the phone's setting, always light or always dark", () => {
  assert.deepEqual([...THEME_CHOICES], ["sun", "phone", "light", "dark"]);
  for (const phoneDark of [false, true]) {
    assert.equal(themeDarkFor("sun", NOON, phoneDark), false);
    assert.equal(themeDarkFor("sun", NIGHT, phoneDark), true);
    assert.equal(themeDarkFor("light", NIGHT, phoneDark), false);
    assert.equal(themeDarkFor("dark", NOON, phoneDark), true);
    assert.equal(themeDarkFor("phone", NOON, phoneDark), phoneDark);
    assert.equal(themeDarkFor("phone", NIGHT, phoneDark), phoneDark);
  }
});

test("the choice is kept on this device; nothing kept, something else or storage refused is the sun", () => {
  const store = memory();
  assert.equal(readThemeChoice(store), "sun");
  assert.equal(writeThemeChoice("dark", store), true);
  assert.equal(store.data.get(THEME_KEY), "dark");
  assert.equal(THEME_KEY, "routemaker.theme");
  assert.equal(readThemeChoice(store), "dark");
  assert.equal(readThemeChoice(memory({ [THEME_KEY]: "purple" })), "sun");
  assert.equal(readThemeChoice(refusing), "sun");
  assert.equal(readThemeChoice(null), "sun");
  assert.equal(writeThemeChoice("light", refusing), false);
  assert.equal(writeThemeChoice("light", null), false);
});

test("the page's class and the browser bar follow, and the map hears each turn", () => {
  const page = fakePage();
  assert.equal(applyTheme(page, true), true);
  assert.ok(page.classes.has(THEME_DARK_CLASS));
  assert.ok(!page.classes.has(THEME_LIGHT_CLASS));
  assert.equal(themeIsDark(page.documentElement), true);
  for (const meta of page.metas) {
    assert.equal(meta.get("content"), THEME_BAR.dark);
    assert.equal(meta.has("media"), false, "one colour, the page's");
  }
  assert.equal(applyTheme(page, true), false, "no change, no event");
  assert.equal(applyTheme(page, false), true);
  assert.equal(themeIsDark(page.documentElement), false);
  assert.ok(page.classes.has(THEME_LIGHT_CLASS), "decided light: the post page's own CSS stops following the phone");
});

test("following the sun, it looks again a second past the next sunrise or sunset (at most an hour on); other choices keep no clock", () => {
  const before = DAY.sunset! - 10 * 60_000;
  assert.equal(themeWait("sun", before), 10 * 60_000 + 1000);
  assert.equal(themeWait("sun", DAY.sunrise! + 60_000), 60 * 60_000);
  for (const choice of ["phone", "light", "dark"] as const) assert.equal(themeWait(choice, before), null);
});

test("the follower: the sun's turns, a page shown again, the phone's change when following the phone, and a new choice at once", () => {
  const page = fakePage();
  const { win, events, timers } = fakeWindow();
  const phone = fakePhone(false);
  const store = memory();
  let now = DAY.sunset! - 1000;
  followTheme(page, win, () => now, store, phone);
  assert.equal(themeIsDark(page.documentElement), false);
  assert.equal(timers[0], 2000);
  now = DAY.sunset! + 5 * 60_000; // asleep through sunset: shown again
  page.listeners.forEach((f) => f());
  assert.equal(themeIsDark(page.documentElement), true);
  assert.deepEqual(events, [THEME_EVENT]);
  // The phone's own change does nothing while the sun decides.
  phone.listeners.forEach((f) => f());
  assert.equal(themeIsDark(page.documentElement), true);
  // Always light, from Settings: kept, and shown at once, the map told.
  timers.length = 0;
  chooseTheme("light", store);
  assert.equal(store.data.get(THEME_KEY), "light");
  assert.equal(themeIsDark(page.documentElement), false);
  assert.deepEqual(events, [THEME_EVENT, THEME_EVENT]);
  assert.deepEqual(timers, [], "no clock for a fixed choice");
  // The phone's setting: follows the phone live.
  chooseTheme("phone", store);
  assert.equal(themeIsDark(page.documentElement), false);
  phone.matches = true;
  phone.listeners.forEach((f) => f());
  assert.equal(themeIsDark(page.documentElement), true);
  // Storage refused: the choice still shows for this visit.
  chooseTheme("light", refusing);
  assert.equal(themeIsDark(page.documentElement), false);
});

test("a kept choice is the one the page opens in", () => {
  const page = fakePage();
  followTheme(page, fakeWindow().win, () => NOON, memory({ [THEME_KEY]: "dark" }), fakePhone(false));
  assert.equal(themeIsDark(page.documentElement), true);
});

test("a ride's map reckons the sun where the page's theme does, so they turn dark together", () => {
  for (const at of [DAY.sunset! - 60_000, DAY.sunset! + 60_000, DAY.sunrise! - 60_000, DAY.sunrise! + 60_000]) {
    assert.equal(mapFlavourFor({ themeDark: false, onBike: true, now: at }) === "dark", sunDownAt(at));
  }
});

test("the startup script reads the sun without the base map's styles", () => {
  // main.tsx runs followTheme before the first render; mapFlavour.ts brings @protomaps/basemaps (the 2026-11-01 review).
  const clock = readFileSync(new URL("./themeClock.ts", import.meta.url), "utf8");
  assert.doesNotMatch(clock, /from "\.\/mapFlavour\.ts"/);
  const main = readFileSync(new URL("../main.tsx", import.meta.url), "utf8");
  assert.ok(main.indexOf("followTheme();") >= 0 && main.indexOf("followTheme();") < main.indexOf("createRoot("), "set before the first render");
});
