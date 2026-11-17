// The Intervals layer (lib/intervals.ts). The owner, 2026-11-16: "a layer that could identify interval-capable
// segments ... in the Plan panel and available for the MCP."
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { act } from "react";
import { click, render } from "../testSupport/render.ts";
import { contrastRatio } from "../stressStyle.js";
import {
  INTERVALS_COLOUR,
  INTERVALS_DARK_COLOUR,
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

const ROW = { id: "a1", l: 2100, r: 30, g: 1.4, line: [[-77, 39], [-76.98, 39]], n: "MacArthur Boulevard" };

test("the file's stretches are read, and a broken entry is left out", () => {
  const found = parseIntervals({ version: 1, intervals: [ROW, { ...ROW, id: "b", w: 1, s: "p", b: 1 }, { id: "c", l: 5, line: [] }] });
  assert.equal(found?.length, 2);
  assert.deepEqual(found?.[0], { id: "a1", lengthM: 2100, riseM: 30, gradePct: 1.4, line: ROW.line, bothWays: false, name: "MacArthur Boulevard", surface: "road", busy: false, minutes: 5.1 });
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
  for (const bg of ["#ffffff", "#f2efe9"]) assert.ok(contrastRatio(drawn(INTERVALS_COLOUR, bg), bg) >= 3, bg);
  assert.equal(DARK_PAINT["intervals-line"]["line-color"], INTERVALS_DARK_COLOUR);
  assert.ok(contrastRatio(drawn(INTERVALS_DARK_COLOUR, "#111827"), "#111827") >= 3);
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
