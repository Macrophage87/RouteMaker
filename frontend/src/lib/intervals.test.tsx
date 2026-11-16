// The Intervals layer (lib/intervals.ts). The owner, 2026-11-16: "a layer that could identify interval-capable
// segments ... in the Plan panel and available for the MCP."
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { click, render } from "../testSupport/render.ts";
import { contrastRatio } from "../stressStyle.js";
import {
  INTERVALS_COLOUR,
  INTERVALS_DARK_COLOUR,
  INTERVALS_HINT,
  INTERVALS_LEGEND_TEXT,
  INTERVALS_NONE,
  INTERVALS_PREF_KEY,
  IntervalsSection,
  intervalsGeoJson,
  intervalsLayers,
  intervalsStatusText,
  loadIntervals,
  parseIntervals,
  readIntervalsLayer,
  saveIntervalsLayer,
} from "./intervals.ts";
import { DARK_PAINT } from "./darkPaint.ts";

const ROW = { id: "a1", l: 2100, r: 30, g: 1.4, line: [[-77, 39], [-76.98, 39]], n: "MacArthur Boulevard" };

test("the file's stretches are read, and a broken entry is left out", () => {
  const found = parseIntervals({ version: 1, intervals: [ROW, { ...ROW, id: "b", w: 1, s: "p", b: 1 }, { id: "c", l: 5, line: [] }] });
  assert.equal(found?.length, 2);
  assert.deepEqual(found?.[0], { id: "a1", lengthM: 2100, riseM: 30, gradePct: 1.4, line: ROW.line, bothWays: false, name: "MacArthur Boulevard", surface: "road", busy: false });
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
  assert.ok(contrastRatio(INTERVALS_COLOUR, "#ffffff") >= 4.5);
  assert.equal(DARK_PAINT["intervals-line"]["line-color"], INTERVALS_DARK_COLOUR);
  assert.ok(contrastRatio(INTERVALS_DARK_COLOUR, "#111827") >= 3);
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

test("the rider sees one switch, its hint, and the key while it is on", async () => {
  const asked: boolean[] = [];
  const off = await render(<IntervalsSection on={false} onChange={(on) => asked.push(on)} />);
  const toggle = off.get("switch", "Interval stretches");
  assert.ok(toggle);
  await click(toggle);
  assert.deepEqual(asked, [true]);
  assert.ok(!off.text().includes(INTERVALS_LEGEND_TEXT));
});

test("opened while on, it says what counts and shows its key", async () => {
  const on = await render(<IntervalsSection on onChange={() => {}} />);
  await click(on.button("Interval stretches layers"));
  assert.ok(on.text().includes(INTERVALS_HINT));
  assert.ok(on.text().includes(INTERVALS_LEGEND_TEXT));
});
