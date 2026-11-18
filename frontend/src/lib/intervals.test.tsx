// The Intervals layer (lib/intervals.ts). The owner, 2026-11-16: "a layer that could identify interval-capable
// segments ... in the Plan panel and available for the MCP."
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { act } from "react";
import { click, render } from "../testSupport/render.ts";
import { HALF_PALETTES, PALETTES, contrastRatio } from "../stressStyle.js";
import {
  INTERVALS_COLOUR,
  INTERVALS_DARK_COLOUR,
  INTERVALS_DARK_RAMP,
  INTERVALS_RAMP,
  intervalsColour,
  INTERVALS_HINT,
  INTERVALS_LEGEND_TEXT,
  INTERVALS_NONE,
  INTERVALS_OPACITY,
  INTERVALS_PREF_KEY,
  IntervalsControls,
  intervalsGeoJson,
  intervalsLayers,
  intervalsAtLeast,
  intervalsStatusText,
  loadIntervals,
  parseIntervals,
  readIntervalsLayer,
  readIntervalsMinutes,
  saveIntervalsMinutes,
  saveIntervalsLayer,
} from "./intervals.ts";
import { DARK_PAINT } from "./darkPaint.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";

const ROW = { id: "a1", l: 2100, r: 30, g: 1.4, line: [[-77, 39], [-76.98, 39]], n: "MacArthur Boulevard" };

test("the file's stretches are read, and a broken entry is left out", () => {
  const found = parseIntervals({ version: 1, intervals: [ROW, { ...ROW, id: "b", w: 1, s: "p", b: 1 }, { id: "c", l: 5, line: [] }] });
  assert.equal(found?.length, 2);
  assert.deepEqual(found?.[0], { id: "a1", lengthM: 2100, riseM: 30, gradePct: 1.4, line: ROW.line, bothWays: false, name: "MacArthur Boulevard", surface: "road", busy: false, minutes: 5.1, bollards: 0 });
  assert.equal(found?.[1].bothWays && found[1].surface === "path" && found[1].busy, true);
  assert.equal(parseIntervals({ version: 2, intervals: [] }), null);
});

test("the shipped file reads, and a failed fetch is null", async () => {
  const shipped = JSON.parse(readFileSync(new URL("../interval-data/intervals.json", import.meta.url), "utf8"));
  assert.ok(Array.isArray(parseIntervals(shipped)));
  assert.equal(await loadIntervals("x", async () => ({ ok: false, json: async () => ({}) })), null);
});

test("the layers are valid, the arrows only on one-way stretches, and the pink reads on both maps", () => {
  const style = {
    version: 8,
    glyphs: "https://x/{fontstack}/{range}.pbf",
    sources: { intervals: { type: "geojson", data: intervalsGeoJson(parseIntervals({ version: 1, intervals: [ROW] }) ?? []) } },
    layers: intervalsLayers(false),
  };
  assert.deepEqual(spec.validateStyleMin(style as never), []);
  const arrows = intervalsLayers(false)[1] as { filter: unknown };
  const one = spec.featureFilter(arrows.filter as never, "f").filter;
  assert.equal(one({ zoom: 14 } as never, { type: 2, properties: { one: true }, geometry: [] } as never), true);
  assert.equal(one({ zoom: 14 } as never, { type: 2, properties: { one: false }, geometry: [] } as never), false);
  // What the rider sees is the colour at the drawn opacity over the map: 3:1 for a map graphic.
  const line = intervalsLayers(false)[0] as { paint: Record<string, unknown> };
  assert.equal(line.paint["line-opacity"], INTERVALS_OPACITY);
  const drawn = (fg: string, bg: string) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(fg.slice(i, i + 2), 16) * INTERVALS_OPACITY + parseInt(bg.slice(i, i + 2), 16) * (1 - INTERVALS_OPACITY)).toString(16).padStart(2, "0")).join("");
  // Shaded by minutes (the owner, 2026-11-18): every shade of both ramps keeps 3:1, and the dark map's steps match.
  assert.deepEqual(line.paint["line-color"], intervalsColour(INTERVALS_RAMP));
  for (const shade of INTERVALS_RAMP) for (const bg of ["#ffffff", "#f2efe9"]) assert.ok(contrastRatio(drawn(shade, bg), bg) >= 3, `${shade} on ${bg}`);
  assert.equal(INTERVALS_RAMP[0], INTERVALS_COLOUR);
  assert.deepEqual(DARK_PAINT["intervals-line"]["line-color"], intervalsColour(INTERVALS_DARK_RAMP));
  assert.deepEqual(DARK_PAINT["intervals-arrows"]["text-color"], intervalsColour(INTERVALS_DARK_RAMP));
  for (const shade of INTERVALS_DARK_RAMP) for (const bg of ["#111827", "#1b1e24"]) assert.ok(contrastRatio(drawn(shade, bg), bg) >= 3, `${shade} on ${bg}`);
  assert.equal(INTERVALS_DARK_RAMP[0], INTERVALS_DARK_COLOUR);
  // No shade reads as a stress level (the review of #1328: a maroon end read as LTS 4): every shade is well clear of
  // every palette's line colours, whole and half steps, by plain RGB distance.
  const rgb = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const apart = (a: string, b: string) => Math.hypot(...rgb(a).map((v, i) => v - rgb(b)[i]));
  const stress = [...Object.values(PALETTES), ...Object.values(HALF_PALETTES)].flatMap((p) => Object.values(p as Record<string, { color: string }>).map((t) => t.color));
  for (const shade of [...INTERVALS_RAMP, ...INTERVALS_DARK_RAMP]) for (const level of stress) assert.ok(apart(shade, level) >= 30, `${shade} near ${level}`);
  // A stretch under 5 minutes takes the first shade, one of 20 or more the last.
  assert.deepEqual(intervalsColour(INTERVALS_RAMP).slice(1, 3), [["to-number", ["get", "t"], 0], INTERVALS_RAMP[0]]);
  assert.deepEqual(intervalsColour(INTERVALS_RAMP).slice(-2), [20, INTERVALS_RAMP[4]]);
});

test("off by default and kept on this device", () => {
  const data = new Map<string, string>();
  const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
  assert.equal(readIntervalsLayer(store), false);
  saveIntervalsLayer(true, store);
  assert.equal(data.get(INTERVALS_PREF_KEY), "on");
  assert.equal(readIntervalsLayer(store), true);
  assert.equal(intervalsStatusText(true, "empty"), INTERVALS_NONE);
  assert.equal(intervalsStatusText(false, "empty"), "");
});

test("the rider sees one switch and its hint; the key only while it is on", async () => {
  const asked: boolean[] = [];
  const off = await render(<IntervalsControls on={false} onChange={(on) => asked.push(on)} />);
  const toggle = off.get("switch", "Interval stretches");
  assert.ok(toggle);
  await click(toggle);
  assert.deepEqual(asked, [true]);
  assert.ok(off.text().includes(INTERVALS_HINT));
  assert.ok(!off.text().includes(INTERVALS_LEGEND_TEXT));
  const on = await render(<IntervalsControls on onChange={() => {}} status={INTERVALS_NONE} />);
  assert.ok(on.text().includes(INTERVALS_LEGEND_TEXT));
  assert.ok(on.text().includes(INTERVALS_NONE));
  for (const band of ["3 to 5 min", "5 to 8 min", "8 to 12 min", "12 to 20 min", "20 min or more"]) assert.ok(on.text().includes(band), band);
});

test("in Spanish Plan the switch, its hint, the minutes and the key are in Spanish (the v0.27.3 review)", async () => {
  // Before: "Interval stretches" and its hint stayed English on a Spanish page.
  await loadLanguage("es");
  setLanguageForTest("es");
  try {
    // A fresh copy, loaded with Spanish in force as the app loads its modules after the catalog.
    const es = (await import(`./intervals.ts?es-${Date.now()}`)) as typeof import("./intervals.ts");
    const screen = await render(<es.IntervalsControls on onChange={() => {}} minutes={5} onMinutesChange={() => {}} status={es.INTERVALS_NONE} />);
    assert.ok(screen.get("switch", "Tramos para intervalos"));
    const text = screen.text();
    for (const words of ["3 minutos o más sin paradas", "Mostrar intervalos desde", "5 minutos", "Brillo rosa", "Aún no hay tramos"]) assert.ok(text.includes(words), words);
    assert.ok(!/Interval stretches|minutes|Pink glow/.test(text), text);
  } finally {
    setLanguageForTest("en");
  }
});

test("by time: a short steady climb holds 3 minutes as a longer flat road does, and the rider picks the least", async () => {
  // The owner, 2026-11-17: "if it's a continuous uphill, you don't need as much distance ... 3 minutes is the minimum".
  const [climb, flat] = parseIntervals({ version: 1, intervals: [{ ...ROW, id: "c", l: 1000, r: 60, t: 3.3 }, { ...ROW, id: "f", l: 2500, r: 0, t: 5.2 }] }) ?? [];
  assert.equal(climb.minutes, 3.3);
  assert.deepEqual(intervalsAtLeast([climb, flat], 3).map((s) => s.id), ["c", "f"]);
  assert.deepEqual(intervalsAtLeast([climb, flat], 5).map((s) => s.id), ["f"]);
  const data = new Map<string, string>();
  const store = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
  assert.equal(readIntervalsMinutes(store), 3);
  saveIntervalsMinutes(8, store);
  assert.equal(readIntervalsMinutes(store), 8);
  const asked: number[] = [];
  const on = await render(<IntervalsControls on onChange={() => {}} minutes={3} onMinutesChange={(m) => asked.push(m)} />);
  const select = on.container.querySelector("select") as HTMLSelectElement;
  assert.equal(on.container.querySelector(`label[for="${select.id}"]`)?.textContent, "Show intervals from");
  assert.deepEqual([...select.options].map((o) => o.textContent), ["3 minutes", "5 minutes", "8 minutes", "12 minutes", "20 minutes"]);
  await act(async () => {
    select.value = "5";
    select.dispatchEvent(new window.Event("change", { bubbles: true }) as unknown as Event);
  });
  assert.deepEqual(asked, [5]);
  const off = await render(<IntervalsControls on={false} onChange={() => {}} minutes={3} onMinutesChange={() => {}} />);
  assert.equal(off.container.querySelector("select"), null);
});
