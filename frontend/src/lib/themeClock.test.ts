import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { solarDay } from "./lightTimes.ts";
import { COVERAGE_CENTRE } from "./plusCode.ts";
import { THEME_BAR, THEME_DARK_CLASS, THEME_EVENT, applyTheme, followSun, themeDarkAt, themeIsDark, themeWait } from "./themeClock.ts";

// The owner, 2026-11-01: "Set the default color mode to adjust by time of day", then "do sunrise/sunset".
const DAY = solarDay(Date.UTC(2026, 10, 1, 17), COVERAGE_CENTRE[1], COVERAGE_CENTRE[0]);

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

test("the theme is light from sunrise to sunset and dark from sunset to sunrise, not at civil dawn and dusk", () => {
  assert.ok(DAY.sunrise && DAY.sunset && DAY.civil_dawn && DAY.civil_dusk);
  assert.equal(themeDarkAt(DAY.sunrise! + 60_000), false);
  assert.equal(themeDarkAt(DAY.sunset! - 60_000), false);
  assert.equal(themeDarkAt(DAY.sunset! + 60_000), true, "just after sunset, before civil dusk");
  assert.ok(DAY.sunset! + 60_000 < DAY.civil_dusk!);
  assert.equal(themeDarkAt(DAY.sunrise! - 60_000), true, "just before sunrise, after civil dawn");
});

test("the page's class and the browser bar follow, and the map hears each turn", () => {
  const page = fakePage();
  assert.equal(applyTheme(page, DAY.sunset! + 60_000), true);
  assert.ok(page.classes.has(THEME_DARK_CLASS));
  assert.equal(themeIsDark(page.documentElement), true);
  for (const meta of page.metas) {
    assert.equal(meta.get("content"), THEME_BAR.dark);
    assert.equal(meta.has("media"), false, "one colour, not the phone's theme");
  }
  assert.equal(applyTheme(page, DAY.sunset! + 120_000), false, "no change, no event");
  assert.equal(applyTheme(page, Date.UTC(2026, 10, 2, 17)), true);
  assert.equal(themeIsDark(page.documentElement), false);
});

test("it looks again a second past the next sunrise or sunset (at most an hour on), and when the page is shown", () => {
  const before = DAY.sunset! - 10 * 60_000;
  assert.equal(themeWait(before), 10 * 60_000 + 1000);
  assert.equal(themeWait(DAY.sunrise! + 60_000), 60 * 60_000);
  const page = fakePage();
  const events: string[] = [];
  const timers: number[] = [];
  let now = DAY.sunset! - 1000;
  followSun(page, { setTimeout: ((_: () => void, ms: number) => timers.push(ms)) as never, dispatchEvent: ((e: Event) => events.push(e.type)) as never }, () => now);
  assert.equal(themeIsDark(page.documentElement), false);
  assert.equal(timers[0], 2000);
  now = DAY.sunset! + 5 * 60_000; // asleep through sunset: shown again
  page.listeners.forEach((f) => f());
  assert.equal(themeIsDark(page.documentElement), true);
  assert.deepEqual(events, [THEME_EVENT]);
});

test("the stylesheet no longer reads the phone's theme, and the map's own controls go dark with the dark map", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /prefers-color-scheme/);
  for (const selector of [":root.map-dark .maplibregl-ctrl-group", ":root.map-dark .maplibregl-ctrl-scale", ":root.map-dark .maplibregl-ctrl-attrib.maplibregl-compact"]) {
    assert.ok(css.includes(selector), selector);
  }
  const main = readFileSync(new URL("../main.tsx", import.meta.url), "utf8");
  assert.ok(main.indexOf("followSun();") < main.indexOf("createRoot("), "set before the first render");
});
