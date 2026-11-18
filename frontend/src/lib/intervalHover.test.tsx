// An interval stretch's hover card (lib/intervalHover.ts). The owner, 2026-11-18: "Allow a mouseover with elevation
// profile as well, it should also give distance and a rough estimate of interval time", and "Mark bollards on the
// interval card and have it noted".
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "../testSupport/render.ts";
import { INTERVAL_TITLE, intervalAt, intervalEnds, intervalHoverChart, intervalHoverWords } from "./intervalHover.ts";
import { INTERVALS_LINE_LAYER } from "./intervals.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";

await loadLanguage("es");

const DRAWN = { id: "s1", one: true, n: "Klingle Valley Trail", l: 1033, r: 58, t: 3.6, k: 2, x0: -77.07, y0: 38.93, x1: -77.06, y1: 38.935 };

test("the card names the stretch, then its distance, rise, minutes, which way and its bollards", () => {
  const words = intervalHoverWords(DRAWN);
  assert.equal(words.title, "Klingle Valley Trail");
  assert.match(words.detail, /0\.6 mi/);
  assert.match(words.detail, /5\.6%/);
  assert.match(words.detail, /about 3\.6 min at 18 mph \(29 km\/h\)/);
  assert.match(words.detail, /this way only/);
  assert.match(words.detail, /2 bollards to ride through/);
});

test("an unnamed flat stretch either way, with no bollards, says so and nothing about bollards", () => {
  const words = intervalHoverWords({ ...DRAWN, n: "", r: 0, one: false, k: 0 });
  assert.equal(words.title, INTERVAL_TITLE);
  assert.match(words.detail, /flat/);
  assert.match(words.detail, /either way/);
  assert.doesNotMatch(words.detail, /bollard/);
  assert.match(intervalHoverWords({ ...DRAWN, k: 1 }).detail, /1 bollard to ride through/);
});

test("in Spanish the card's words are Spanish (Plan is English and Spanish)", () => {
  setLanguageForTest("es");
  try {
    const words = intervalHoverWords({ ...DRAWN, n: "" });
    assert.match(words.detail, /sube .* al 5\.6%/);
    assert.match(words.detail, /unos 3\.6 min a /);
    assert.match(words.detail, /solo en este sentido/);
    assert.match(words.detail, /2 bolardos que atravesar/);
    assert.match(intervalHoverWords({ ...DRAWN, r: 0, one: false, k: 1 }).detail, /llano.*en ambos sentidos.*1 bolardo que atravesar/);
  } finally {
    setLanguageForTest("en");
  }
});

test("the profile is asked for once, drawn with the steepest grade, and none is drawn where there is none", async () => {
  let asked = 0;
  const profile = { id: "s1", length_m: 60, rise_m: 5, avg_grade_pct: 8, minutes: 3.6, both_ways: false, bollards: 2, max_grade_pct: 9, interval_m: 30, m: [0, 30, 60], elevation_m: [10, 12, 15], grade_pct: [null, 6.7, 10] };
  const ok = async () => {
    asked += 1;
    return { ok: true, status: 200, json: async () => profile };
  };
  const chart = intervalHoverChart("s1", intervalEnds(DRAWN), ok);
  const drawn = await chart();
  assert.ok(drawn);
  await chart();
  assert.equal(asked, 1);
  const shown = await render(drawn);
  assert.ok(shown.get("img", /steepest 9%/));
  const none = intervalHoverChart("s2", null, async () => ({ ok: false, status: 404, json: async () => ({}) }));
  assert.equal(await none(), null);
});

test("the stretch under the mouse is found only while the layer is on the map", () => {
  const map = (on: boolean) => ({
    getLayer: (id: string) => (on && id === INTERVALS_LINE_LAYER ? {} : undefined),
    queryRenderedFeatures: () => [{ properties: DRAWN }],
  });
  assert.equal(intervalAt(map(true), { x: 10, y: 10 }, 6)?.properties.id, "s1");
  assert.equal(intervalAt(map(false), { x: 10, y: 10 }, 6), null);
});
