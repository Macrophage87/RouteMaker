// Public water and restrooms from OpenStreetMap: when the layer shows, the
// data file, the icons, the points along a route and everything said in words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ALONG_ROUTE_M,
  WATER_KINDS,
  WATER_LAYER,
  WATER_SOURCE_ID,
  addWaterRestrooms,
  loadWaterRestrooms,
  parseWaterRestrooms,
  setWaterVisibility,
  waterAlongCount,
  waterAlongRoute,
  waterAlongText,
  waterDetails,
  waterIcon,
  waterIconId,
  waterLayer,
  waterShown,
  type WaterPoint,
} from "./waterRestrooms.ts";
import {
  WATER_ALONG_NO_ROUTE,
  WATER_ALONG_NONE,
  WATER_LOADING,
  WATER_SWITCH,
  WATER_UNAVAILABLE,
  WaterAlongList,
  WaterSection,
  waterStatusText,
} from "./waterLegend.ts";
import { PRESETS } from "./presets.ts";
import type { LonLat } from "./geo.ts";

test("on by default for Trailmaxxing and Gravel only; the rider's switch wins, per ride type", () => {
  const on = PRESETS.filter((p) => waterShown(p.id, {})).map((p) => p.id);
  assert.deepEqual(on.sort(), ["gravel", "trailmaxxing"]);
  assert.equal(waterShown("gravel", { gravel: false }), false);
  assert.equal(waterShown("default", { default: true }), true);
  // A choice on one ride type leaves the others at their default.
  assert.equal(waterShown("trailmaxxing", { gravel: false }), true);
});

test("parses the file's short form and drops what it cannot place", () => {
  const points = parseWaterRestrooms({
    source: "x",
    points: [
      { id: "n1", x: -77, y: 38.9, k: "w", b: 1, fee: "no" },
      { id: "w2", x: -77.1, y: 38.8, k: "wt", n: " Comfort station ", wc: "limited", h: "24/7", s: "summer" },
      { id: "n3", x: -77.2, y: 38.7, k: "t", b: 1, fee: "maybe", wc: "sometimes" },
      { id: "n4", x: "bad", y: 38.7, k: "t" },
      { id: "n5", x: -77, y: 38.7, k: "x" },
      { x: -77, y: 38.7, k: "t" },
    ],
  });
  assert.deepEqual(points, [
    { id: "n1", lon: -77, lat: 38.9, kind: "w", fee: "no", bottle: true },
    { id: "w2", lon: -77.1, lat: 38.8, kind: "wt", name: "Comfort station", wheelchair: "limited", hours: "24/7", seasonal: "summer" },
    // A restroom alone has no bottle filler, whatever the file says.
    { id: "n3", lon: -77.2, lat: 38.7, kind: "t" },
  ]);
  assert.equal(parseWaterRestrooms({}), null);
  assert.equal(parseWaterRestrooms(null), null);
});

test("load: unavailable when the file fails, is malformed or is empty", async () => {
  const ok = (body: unknown) => async () => ({ ok: true, json: async () => body });
  assert.equal(await loadWaterRestrooms("u", async () => ({ ok: false, json: async () => ({}) })), null);
  assert.equal(await loadWaterRestrooms("u", async () => { throw new Error("offline"); }), null);
  assert.equal(await loadWaterRestrooms("u", ok({ points: [] })), null);
  assert.equal((await loadWaterRestrooms("u", ok({ points: [{ id: "n1", x: -77, y: 38.9, k: "w" }] })))?.length, 1);
});

test("the bundled file parses, every point in the coverage box, ids unique", () => {
  const raw = JSON.parse(readFileSync(new URL("../amenity-data/water-restrooms.json", import.meta.url), "utf8"));
  assert.equal(raw.source, "OpenStreetMap contributors, ODbL 1.0");
  const points = parseWaterRestrooms(raw);
  assert.ok(points);
  assert.equal(points.length, raw.points.length, "every point in the file is one the map can draw");
  assert.equal(new Set(points.map((p) => p.id)).size, points.length);
  for (const p of points) assert.ok(p.lon >= -78 && p.lon <= -76.02 && p.lat >= 38.2 && p.lat <= 39.72, p.id);
});

test("icons: three shapes, told apart without colour", () => {
  const shapes = WATER_KINDS.map((kind) => {
    const r = waterIcon(kind, 1);
    assert.equal(r.width, 18);
    assert.equal(r.data.length, 18 * 18 * 4);
    return Array.from({ length: r.width * r.height }, (_, i) => (r.data[i * 4 + 3] > 127 ? 1 : 0)).join("");
  });
  // A drop and a diamond have different outlines.
  assert.notEqual(shapes[0], shapes[1]);
  // The diamond with a drop has the diamond's outline and a white drop inside it.
  assert.equal(shapes[1], shapes[2]);
  const t = waterIcon("t", 1);
  const wt = waterIcon("wt", 1);
  const white = (r: typeof t) => Array.from({ length: 18 * 18 }, (_, i) => r.data[i * 4] > 230 && r.data[i * 4 + 1] > 230 && r.data[i * 4 + 3] > 200).filter(Boolean).length;
  assert.ok(white(wt) > white(t) + 10);
  // The drop's tip is up: more ink in the bottom half than the top.
  const w = waterIcon("w", 1);
  const ink = (y0: number, y1: number) => {
    let n = 0;
    for (let y = y0; y < y1; y++) for (let x = 0; x < 18; x++) if (w.data[(y * 18 + x) * 4 + 3] > 127) n++;
    return n;
  };
  assert.ok(ink(9, 18) > ink(0, 9));
});

test("the layer: one symbol layer, an icon per kind, from street-network zoom", () => {
  const layer = waterLayer() as { id: string; type: string; minzoom: number; layout: Record<string, unknown> };
  assert.equal(layer.id, WATER_LAYER);
  assert.equal(layer.type, "symbol");
  assert.equal(layer.minzoom, 12);
  const match = layer.layout["icon-image"] as unknown[];
  for (const kind of WATER_KINDS) assert.ok(match.includes(waterIconId(kind)));
});

function stubMap(layers: string[] = []) {
  const calls: string[] = [];
  const sources = new Map<string, unknown>();
  const images = new Set<string>();
  const added: Array<{ layer: Record<string, any>; before?: string }> = [];
  const visibility = new Map<string, string>();
  return {
    calls,
    added,
    visibility,
    sources,
    map: {
      getSource: (id: string) => sources.get(id),
      addSource: (id: string, source: unknown) => {
        sources.set(id, source);
        calls.push(`source ${id}`);
      },
      addLayer: (layer: Record<string, any>, before?: string) => {
        added.push({ layer, before });
        layers.push(layer.id);
      },
      getLayer: (id: string) => (layers.includes(id) ? {} : undefined),
      hasImage: (id: string) => images.has(id),
      addImage: (id: string, _image: unknown, options: { pixelRatio: number }) => {
        images.add(id);
        calls.push(`image ${id} @${options.pixelRatio}`);
      },
      setLayoutProperty: (id: string, name: string, value: string) => {
        if (name === "visibility") visibility.set(id, value);
      },
    },
  };
}

const POINT: WaterPoint = { id: "n1", lon: -77, lat: 38.9, kind: "w" };

test("adds the icons, source and layer once, under the route, hidden or shown", () => {
  const s = stubMap(["route-casing"]);
  assert.equal(addWaterRestrooms(s.map, [POINT], false, 2, "route-casing"), true);
  assert.deepEqual(s.calls.filter((c) => c.startsWith("image")), WATER_KINDS.map((k) => `image ${waterIconId(k)} @2`));
  assert.ok(s.sources.has(WATER_SOURCE_ID));
  assert.equal(s.added.length, 1);
  assert.equal(s.added[0].before, "route-casing");
  assert.equal(s.added[0].layer.layout.visibility, "none");
  assert.equal(addWaterRestrooms(s.map, [POINT], true, 2, "route-casing"), false, "only once");
  setWaterVisibility(s.map, true);
  assert.equal(s.visibility.get(WATER_LAYER), "visible");
  // With no route on the map yet, it goes on top; the route is added over it later.
  const t = stubMap();
  addWaterRestrooms(t.map, [POINT], true, 1, "route-casing");
  assert.equal(t.added[0].before, undefined);
  assert.equal(t.added[0].layer.layout.visibility, "visible");
});

// A straight route due east along 38.9 N, about 5.4 mi (8.7 km).
const LINE: LonLat[] = [
  [-77.1, 38.9],
  [-77.05, 38.9],
  [-77.0, 38.9],
];
const M_PER_DEG_LON = 111_320 * Math.cos((38.9 * Math.PI) / 180);
const M_PER_DEG_LAT = 111_320;

test("along the route: in riding order, with how far along and how far off", () => {
  const near: WaterPoint = { id: "n1", lon: -77.02, lat: 38.9 + 100 / M_PER_DEG_LAT, kind: "t" };
  const first: WaterPoint = { id: "n2", lon: -77.09, lat: 38.9 - 5 / M_PER_DEG_LAT, kind: "w" };
  const far: WaterPoint = { id: "n3", lon: -77.05, lat: 38.9 + 400 / M_PER_DEG_LAT, kind: "w" };
  const beyond: WaterPoint = { id: "n4", lon: -77.0 + 200 / M_PER_DEG_LON, lat: 38.9, kind: "wt" };
  const items = waterAlongRoute(LINE, [near, far, first, beyond]);
  assert.deepEqual(items.map((i) => i.point.id), ["n2", "n1", "n4"]);
  assert.ok(Math.abs(items[0].alongM - 0.01 * M_PER_DEG_LON) < 1);
  assert.ok(Math.abs(items[0].offM - 5) < 0.5);
  assert.ok(Math.abs(items[1].offM - 100) < 0.5);
  // Past the end: measured to the end, and placed there.
  assert.ok(Math.abs(items[2].offM - 200) < 1);
  assert.ok(Math.abs(items[2].alongM - 0.1 * M_PER_DEG_LON) < 1);
  assert.ok(ALONG_ROUTE_M > 300 && ALONG_ROUTE_M < 310);
  assert.deepEqual(waterAlongRoute(LINE.slice(0, 1), [near]), []);
  assert.deepEqual(waterAlongRoute(LINE, []), []);
});

test("an out-and-back keeps the nearer pass", () => {
  const back: LonLat[] = [...LINE, [-77.05, 38.9 + 200 / M_PER_DEG_LAT], [-77.1, 38.9 + 200 / M_PER_DEG_LAT]];
  const p: WaterPoint = { id: "n1", lon: -77.08, lat: 38.9 + 190 / M_PER_DEG_LAT, kind: "w" };
  const [item] = waterAlongRoute(back, [p]);
  assert.ok(Math.abs(item.offM - 10) < 1);
  assert.ok(item.alongM > 0.1 * M_PER_DEG_LON, "on the way back");
});

test("in words: US units first, metric in brackets, every detail said", () => {
  const p: WaterPoint = { id: "w1", lon: 0, lat: 0, kind: "wt", name: "Peirce Mill", fee: "no", wheelchair: "yes", seasonal: "summer", hours: "06:00-22:00" };
  assert.equal(
    waterAlongText({ point: p, alongM: 1609.344 * 4.2, offM: 61 }),
    "At 4.2 mi (6.8 km): Restroom with drinking water, Peirce Mill, 200 ft (61 m) off the route. Free. Wheelchair accessible. Seasonal: summer. Hours: 06:00-22:00.",
  );
  assert.equal(waterAlongText({ point: POINT, alongM: 50, offM: 3 }), "At 160 ft (50 m): Drinking water, on the route.");
  assert.deepEqual(waterDetails({ ...POINT, bottle: true, fee: "yes", wheelchair: "no", seasonal: "yes", hours: "24/7" }), [
    "Bottle filler.",
    "Fee to use.",
    "Not wheelchair accessible.",
    "Seasonal.",
    "Open 24/7.",
  ]);
  assert.equal(
    waterAlongCount([
      { point: POINT, alongM: 0, offM: 0 },
      { point: { ...POINT, kind: "wt" }, alongM: 0, offM: 0 },
      { point: { ...POINT, kind: "t" }, alongM: 0, offM: 0 },
    ]),
    "3 along your route: 2 with drinking water, 2 restrooms.",
  );
});

test("the section: a labelled switch, one status line, the legend and list only when ready", () => {
  const html = (status: "loading" | "ready" | "unavailable", on = true) =>
    renderToStaticMarkup(createElement(WaterSection, { on, onChange: () => {}, status, items: null }));
  const loading = html("loading");
  assert.match(loading, /<section aria-labelledby="water-heading"/);
  assert.ok(loading.includes(`<input type="checkbox" checked=""/>${WATER_SWITCH}`));
  assert.ok(loading.includes(`role="status">${WATER_LOADING}<`));
  assert.ok(!loading.includes("water-legend"));
  const ready = html("ready");
  assert.ok(ready.includes('aria-label="Water and restrooms legend"'));
  assert.ok(ready.includes("Drinking water: blue drop"));
  assert.ok(ready.includes("Restroom: purple diamond"));
  assert.ok(ready.includes(WATER_ALONG_NO_ROUTE));
  assert.ok(html("unavailable").includes(WATER_UNAVAILABLE));
  // Off: the status line stays in the page, empty, so the next words are read.
  assert.ok(html("loading", false).includes('role="status"></p>'));
  assert.equal(waterStatusText(false, "unavailable"), "");
});

test("the list: a heading it is labelled by, one item per point, an Add as stop button named for it", () => {
  const items = [{ point: { ...POINT, name: "Mile 4" }, alongM: 1609.344 * 4, offM: 0 }];
  const html = renderToStaticMarkup(createElement(WaterAlongList, { items, onAddStop: () => {}, headingId: "h", level: "h3" }));
  assert.match(html, /<h3 id="h">Water and restrooms along your route<\/h3>/);
  assert.match(html, /<ul aria-labelledby="h">/);
  assert.ok(html.includes("At 4.0 mi (6.4 km): Drinking water, Mile 4, on the route."));
  assert.ok(html.includes('aria-label="Add as stop: Drinking water at 4.0 mi (6.4 km)"'));
  assert.ok(html.includes(">Add as stop</button>"));
  assert.ok(renderToStaticMarkup(createElement(WaterAlongList, { items: [], headingId: "h" })).includes(WATER_ALONG_NONE));
  assert.ok(!renderToStaticMarkup(createElement(WaterAlongList, { items, headingId: "h" })).includes("<button"));
});
