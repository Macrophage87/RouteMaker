// Public water and restrooms from OpenStreetMap: the switches and what they
// keep, the data file, the icons, the points along a route and everything said in words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  ALONG_ROUTE_M,
  ALONG_ROUTE_TEXT,
  WATER_ICONS,
  WATER_LAYER,
  WATER_PREFS_DEFAULT,
  WATER_PREFS_KEY,
  WATER_SOURCE_ID,
  addWaterRestrooms,
  loadWaterRestrooms,
  parseWaterRestrooms,
  readWaterPrefs,
  saveWaterPrefs,
  setWaterPrefs,
  waterAlongCount,
  waterAlongRoute,
  waterAlongText,
  waterCard,
  waterDetails,
  waterFilter,
  waterGeoJson,
  waterIcon,
  waterIconId,
  waterIconImage,
  waterIconOf,
  waterKindLabel,
  waterLayer,
  waterVisible,
  type WaterIcon,
  type WaterPoint,
  type WaterPrefs,
} from "./waterRestrooms.ts";
import {
  WATER_ALONG_NO_ROUTE,
  WATER_ALONG_NONE,
  WATER_BASIC_SWITCH,
  WATER_LEGEND,
  WATER_LOADING,
  WATER_SWITCH,
  WATER_UNAVAILABLE,
  WATER_UNTREATED_SWITCH,
  WaterAlongList,
  WaterSection,
  waterStatusText,
} from "./waterLegend.ts";
import type { LonLat } from "./geo.ts";

function memoryStore(initial?: string) {
  const items = new Map<string, string>();
  if (initial !== undefined) items.set(WATER_PREFS_KEY, initial);
  return { getItem: (k: string) => items.get(k) ?? null, setItem: (k: string, v: string) => void items.set(k, v), items };
}

test("on by default for every ride type, with basic toilets and untreated water; kept on this device", () => {
  assert.deepEqual(WATER_PREFS_DEFAULT, { on: true, basic: true, untreated: true });
  assert.deepEqual(readWaterPrefs(memoryStore()), WATER_PREFS_DEFAULT);
  assert.deepEqual(readWaterPrefs(null), WATER_PREFS_DEFAULT);
  const store = memoryStore();
  assert.equal(saveWaterPrefs({ on: false, basic: false, untreated: true }, store), true);
  assert.deepEqual(readWaterPrefs(store), { on: false, basic: false, untreated: true });
  // A damaged or partial record falls back field by field.
  assert.deepEqual(readWaterPrefs(memoryStore("{not json")), WATER_PREFS_DEFAULT);
  assert.deepEqual(readWaterPrefs(memoryStore('{"basic":false,"on":"no"}')), { on: true, basic: false, untreated: true });
  // Storage that throws (blocked site data): the defaults, and nothing kept.
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.deepEqual(readWaterPrefs(blocked), WATER_PREFS_DEFAULT);
  assert.equal(saveWaterPrefs(WATER_PREFS_DEFAULT, blocked), false);
});

const ALL: WaterPrefs = { on: true, basic: true, untreated: true };

test("the switches: a point shows for its restroom or for its water", () => {
  const basicWithWater: WaterPoint = { id: "n1", lon: 0, lat: 0, toilet: "b", water: "p" };
  const basic: WaterPoint = { id: "n2", lon: 0, lat: 0, toilet: "b" };
  const spring: WaterPoint = { id: "n3", lon: 0, lat: 0, water: "n" };
  const flush: WaterPoint = { id: "n4", lon: 0, lat: 0, toilet: "f" };
  const none: WaterPrefs = { on: true, basic: false, untreated: false };
  assert.ok([basicWithWater, basic, spring, flush].every((p) => waterVisible(p, ALL)));
  assert.deepEqual([basicWithWater, basic, spring, flush].filter((p) => waterVisible(p, none)).map((p) => p.id), ["n1", "n4"]);
  // The map's filter says the same.
  const filter = JSON.stringify(waterFilter(none));
  assert.ok(filter.includes('["!=",["get","t"],"b"]') && filter.includes('["!=",["get","w"],"n"]'));
  assert.equal(JSON.stringify(waterFilter(ALL)), '["any",["has","t"],["has","w"]]');
});

test("parses the file's short form and drops what it cannot place", () => {
  const points = parseWaterRestrooms({
    source: "x",
    points: [
      { id: "n1", x: -77, y: 38.9, w: "p", b: 1, fee: "no" },
      { id: "w2", x: -77.1, y: 38.8, w: "p", t: "f", n: " Comfort station ", wc: "limited", h: "24/7", s: "summer" },
      { id: "n3", x: -77.2, y: 38.7, t: "b", b: 1, fee: "maybe", wc: "sometimes" },
      { id: "n6", x: -77.3, y: 38.6, w: "n", b: 1 },
      { id: "n4", x: "bad", y: 38.7, t: "u" },
      { id: "n5", x: -77, y: 38.7, w: "x", t: "y" },
      { x: -77, y: 38.7, t: "u" },
    ],
  });
  assert.deepEqual(points, [
    { id: "n1", lon: -77, lat: 38.9, water: "p", fee: "no", bottle: true },
    { id: "w2", lon: -77.1, lat: 38.8, water: "p", toilet: "f", name: "Comfort station", wheelchair: "limited", hours: "24/7", seasonal: "summer" },
    // A bottle filler is said of drinking water only, whatever the file says.
    { id: "n3", lon: -77.2, lat: 38.7, toilet: "b" },
    { id: "n6", lon: -77.3, lat: 38.6, water: "n" },
  ]);
  assert.equal(parseWaterRestrooms({}), null);
  assert.equal(parseWaterRestrooms(null), null);
});

test("load: unavailable when the file fails, is malformed or is empty", async () => {
  const ok = (body: unknown) => async () => ({ ok: true, json: async () => body });
  assert.equal(await loadWaterRestrooms("u", async () => ({ ok: false, json: async () => ({}) })), null);
  assert.equal(await loadWaterRestrooms("u", async () => { throw new Error("offline"); }), null);
  assert.equal(await loadWaterRestrooms("u", ok({ points: [] })), null);
  assert.equal((await loadWaterRestrooms("u", ok({ points: [{ id: "n1", x: -77, y: 38.9, w: "p" }] })))?.length, 1);
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

const outline = (icon: WaterIcon) => {
  const r = waterIcon(icon, 1);
  return Array.from({ length: r.width * r.height }, (_, i) => (r.data[i * 4 + 3] > 127 ? 1 : 0)).join("");
};
const whitePixels = (icon: WaterIcon) => {
  const r = waterIcon(icon, 1);
  return Array.from({ length: r.width * r.height }, (_, i) => r.data[i * 4] > 230 && r.data[i * 4 + 1] > 230 && r.data[i * 4 + 3] > 200).filter(Boolean).length;
};

test("icons: each kind is told apart by shape, not colour alone", () => {
  for (const icon of WATER_ICONS) {
    const r = waterIcon(icon, 1);
    assert.equal(r.width, 18);
    assert.equal(r.data.length, 18 * 18 * 4);
  }
  // Water is a drop, a flush restroom a diamond, a basic toilet a box: three outlines.
  assert.equal(new Set([outline("w-p"), outline("t-f"), outline("t-b")]).size, 3);
  // Untreated water: the drop's outline, struck through in white.
  assert.equal(outline("w-n"), outline("w-p"));
  assert.ok(whitePixels("w-n") > whitePixels("w-p") + 8);
  // Unmapped: the diamond's outline, open (white) inside.
  assert.equal(outline("t-u"), outline("t-f"));
  assert.ok(whitePixels("t-u") > whitePixels("t-f") + 30);
  // With drinking water: the same outline and a drop inside.
  for (const t of ["f", "b"] as const) {
    assert.equal(outline(`t-${t}-w`), outline(`t-${t}`));
    assert.ok(whitePixels(`t-${t}-w`) > whitePixels(`t-${t}`) + 10, t);
  }
  assert.ok(whitePixels("t-u-w") < whitePixels("t-u") - 10, "a blue drop in the open diamond");
  // The drop's tip is up: more ink in the bottom half than the top.
  const w = waterIcon("w-p", 1);
  const ink = (y0: number, y1: number) => {
    let n = 0;
    for (let y = y0; y < y1; y++) for (let x = 0; x < 18; x++) if (w.data[(y * 18 + x) * 4 + 3] > 127) n++;
    return n;
  };
  assert.ok(ink(9, 18) > ink(0, 9));
});

test("which icon a point gets", () => {
  const p = (water?: "p" | "n", toilet?: "f" | "b" | "u"): WaterPoint => ({ id: "n", lon: 0, lat: 0, water, toilet });
  assert.equal(waterIconOf(p("p")), "w-p");
  assert.equal(waterIconOf(p("n")), "w-n");
  assert.equal(waterIconOf(p(undefined, "f")), "t-f");
  assert.equal(waterIconOf(p("p", "b")), "t-b-w");
  assert.equal(waterIconOf(p("n", "u")), "t-u", "untreated water at a restroom is said in words, not drawn");
  // Every row of the legend is an icon the map draws, and every icon the map draws has a row but the two
  // restrooms with a drop, which the "A restroom with drinking water" row covers.
  for (const row of WATER_LEGEND) assert.ok(WATER_ICONS.includes(row.icon));
  assert.deepEqual(
    WATER_ICONS.filter((icon) => !WATER_LEGEND.some((row) => row.icon === icon)),
    ["t-b-w", "t-u-w"],
  );
});

test("the layer: one symbol layer, its icon by name, from street-network zoom, filtered by the switches", () => {
  const layer = waterLayer() as { id: string; type: string; minzoom: number; filter: unknown; layout: Record<string, unknown> };
  assert.equal(layer.id, WATER_LAYER);
  assert.equal(layer.type, "symbol");
  assert.equal(layer.minzoom, 12);
  assert.deepEqual(layer.layout["icon-image"], ["concat", "water-restrooms-", ["get", "icon"]]);
  assert.equal(waterIconId("w-n"), "water-restrooms-w-n");
  assert.deepEqual(layer.filter, waterFilter(WATER_PREFS_DEFAULT));
  const [feature] = waterGeoJson([{ id: "n9", lon: -77, lat: 38.9, water: "n" }]).features;
  assert.deepEqual(feature.properties, { id: "n9", icon: "w-n", w: "n" });
});

function stubMap(layers: string[] = []) {
  const calls: string[] = [];
  const sources = new Map<string, unknown>();
  const images = new Set<string>();
  const added: Array<{ layer: Record<string, any>; before?: string }> = [];
  const visibility = new Map<string, string>();
  const filters = new Map<string, unknown>();
  const icons = new Map<string, unknown>();
  return {
    calls,
    icons,
    added,
    visibility,
    filters,
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
      setLayoutProperty: (id: string, name: string, value: unknown) => {
        if (name === "visibility") visibility.set(id, value as string);
        if (name === "icon-image") icons.set(id, value);
      },
      setFilter: (id: string, filter: unknown) => void filters.set(id, filter),
    },
  };
}

const POINT: WaterPoint = { id: "n1", lon: -77, lat: 38.9, water: "p" };

test("adds the icons, source and layer once, under the route, hidden or shown; the switches reach it", () => {
  const s = stubMap(["route-casing"]);
  assert.equal(addWaterRestrooms(s.map, [POINT], { ...ALL, on: false }, 2, "route-casing"), true);
  assert.deepEqual(s.calls.filter((c) => c.startsWith("image")), WATER_ICONS.map((k) => `image ${waterIconId(k)} @2`));
  assert.ok(s.sources.has(WATER_SOURCE_ID));
  assert.equal(s.added.length, 1);
  assert.equal(s.added[0].before, "route-casing");
  assert.equal(s.added[0].layer.layout.visibility, "none");
  assert.equal(addWaterRestrooms(s.map, [POINT], ALL, 2, "route-casing"), false, "only once");
  const some = { on: true, basic: false, untreated: true };
  setWaterPrefs(s.map, some);
  assert.equal(s.visibility.get(WATER_LAYER), "visible");
  assert.deepEqual(s.filters.get(WATER_LAYER), waterFilter(some));
  assert.deepEqual(s.icons.get(WATER_LAYER), waterIconImage(some));
  // Without the route's layer it goes on top (MapView adds the route's layers at load, so it is there).
  const t = stubMap();
  addWaterRestrooms(t.map, [POINT], ALL, 1, "route-casing");
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
  const near: WaterPoint = { id: "n1", lon: -77.02, lat: 38.9 + 100 / M_PER_DEG_LAT, toilet: "u" };
  const first: WaterPoint = { id: "n2", lon: -77.09, lat: 38.9 - 5 / M_PER_DEG_LAT, water: "p" };
  const far: WaterPoint = { id: "n3", lon: -77.05, lat: 38.9 + 400 / M_PER_DEG_LAT, water: "p" };
  const beyond: WaterPoint = { id: "n4", lon: -77.0 + 200 / M_PER_DEG_LON, lat: 38.9, water: "p", toilet: "u" };
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
  const p: WaterPoint = { id: "n1", lon: -77.08, lat: 38.9 + 190 / M_PER_DEG_LAT, water: "p" };
  const [item] = waterAlongRoute(back, [p]);
  assert.ok(Math.abs(item.offM - 10) < 1);
  assert.ok(item.alongM > 0.1 * M_PER_DEG_LON, "on the way back");
});

test("in words: US units first, metric in brackets, every detail said", () => {
  const p: WaterPoint = { id: "w1", lon: 0, lat: 0, toilet: "f", water: "p", name: "Peirce Mill", fee: "no", wheelchair: "yes", seasonal: "summer", hours: "06:00-22:00" };
  assert.equal(
    waterAlongText({ point: p, alongM: 1609.344 * 4.2, offM: 61 }),
    "At 4.2 mi (6.8 km): Flush restroom, with drinking water, Peirce Mill, 200 ft (61 m) off the route. Free. Wheelchair accessible. Seasonal: summer. Hours: 06:00-22:00.",
  );
  assert.equal(waterAlongText({ point: POINT, alongM: 50, offM: 3 }), "At 160 ft (50 m): Drinking water, on the route.");
  assert.equal(
    waterAlongText({ point: { id: "n2", lon: 0, lat: 0, water: "n" }, alongM: 50, offM: 3 }),
    "At 160 ft (50 m): Untreated water, filter or treat it first, on the route.",
  );
  assert.equal(waterKindLabel({ id: "n", lon: 0, lat: 0, toilet: "b" }), "Portable, pit or composting toilet");
  assert.equal(waterKindLabel({ id: "n", lon: 0, lat: 0, toilet: "u", water: "n" }), "Restroom, type not mapped, with untreated water");
  assert.deepEqual(waterDetails({ ...POINT, bottle: true, fee: "yes", wheelchair: "no", seasonal: "yes", hours: "24/7" }), [
    "Bottle filler.",
    "Fee to use.",
    "Not wheelchair accessible.",
    "Seasonal.",
    "Open 24/7.",
  ]);
  const at = (point: WaterPoint) => ({ point, alongM: 0, offM: 0 });
  assert.equal(
    waterAlongCount([at(POINT), at({ ...POINT, toilet: "f" }), at({ id: "n", lon: 0, lat: 0, toilet: "b" })]),
    "3 along your route: 2 with drinking water, 2 restrooms.",
  );
  assert.equal(
    waterAlongCount([at({ id: "n", lon: 0, lat: 0, water: "n" }), at({ id: "m", lon: 0, lat: 0, toilet: "u" })]),
    "2 along your route: 0 with drinking water, 1 untreated water source, 1 restroom.",
  );
});

test("the section: labelled switches, one status line, the legend and list only when ready", () => {
  const html = (status: "loading" | "ready" | "unavailable", prefs: WaterPrefs = ALL) =>
    renderToStaticMarkup(createElement(WaterSection, { prefs, onChange: () => {}, status, items: null }));
  const loading = html("loading");
  assert.match(loading, /<section aria-labelledby="water-heading"/);
  assert.ok(loading.includes(`<input type="checkbox" checked=""/>${WATER_SWITCH}`));
  assert.ok(loading.includes(`<input type="checkbox" checked=""/>${WATER_BASIC_SWITCH}`));
  assert.ok(loading.includes(`<input type="checkbox" checked=""/>${WATER_UNTREATED_SWITCH}`));
  assert.ok(loading.includes("<legend>Also show</legend>"));
  assert.ok(loading.includes(`role="status">${WATER_LOADING}<`));
  assert.ok(!loading.includes("water-legend"));
  const ready = html("ready");
  assert.ok(ready.includes('aria-label="Water and restrooms legend"'));
  for (const row of WATER_LEGEND) assert.ok(ready.includes(`${row.label}: ${row.shape}`), row.icon);
  assert.ok(ready.includes(WATER_ALONG_NO_ROUTE));
  // A kind switched off leaves the legend too.
  const flushOnly = html("ready", { on: true, basic: false, untreated: false });
  assert.ok(!flushOnly.includes("green upright box") && !flushOnly.includes("struck through"));
  assert.ok(flushOnly.includes(`<input type="checkbox"/>${WATER_BASIC_SWITCH}`));
  assert.ok(html("unavailable").includes(WATER_UNAVAILABLE));
  // Off: the kind switches go, and the status line stays in the page, empty, so the next words are read.
  const off = html("loading", { ...ALL, on: false });
  assert.ok(off.includes('role="status"></p>'));
  assert.ok(!off.includes(WATER_BASIC_SWITCH));
  assert.equal(waterStatusText(false, "unavailable"), "");
});

test("the list: a heading it is labelled by, one item per point, an Add as stop button named for it", () => {
  const items = [{ point: { ...POINT, name: "Mile 4" }, alongM: 1609.344 * 4, offM: 0 }];
  const html = renderToStaticMarkup(createElement(WaterAlongList, { items, onAddStop: () => {}, headingId: "h", level: "h3" }));
  assert.match(html, /<h3 id="h">Water and restrooms along your route<\/h3>/);
  assert.match(html, /<ul aria-labelledby="h">/);
  assert.ok(html.includes("At 4.0 mi (6.4 km): Drinking water, Mile 4, on the route."));
  assert.ok(html.includes('aria-label="Add as stop: Drinking water, Mile 4 at 4.0 mi (6.4 km)"'));
  assert.ok(html.includes(">Add as stop</button>"));
  // Empty, or with no route yet: still the heading, then why there is nothing.
  const none = renderToStaticMarkup(createElement(WaterAlongList, { items: [], headingId: "h" }));
  assert.match(none, /<h4 id="h">Water and restrooms along your route<\/h4><p class="hint">None within 1,000 ft \(305 m\) of your route\.<\/p>/);
  assert.equal(WATER_ALONG_NONE, `None within ${ALONG_ROUTE_TEXT} of your route.`);
  const noRoute = renderToStaticMarkup(createElement(WaterAlongList, { items: null, headingId: "h" }));
  assert.ok(noRoute.includes('<h4 id="h">') && noRoute.includes(WATER_ALONG_NO_ROUTE));
  assert.ok(!renderToStaticMarkup(createElement(WaterAlongList, { items, headingId: "h" })).includes("<button"));
});

// --- As MapLibre itself reads the layer ------------------------------------

const KINDS: WaterPoint[] = [];
for (const water of [undefined, "p", "n"] as const) {
  for (const toilet of [undefined, "f", "b", "u"] as const) {
    if (water || toilet) KINDS.push({ id: `n-${water}-${toilet}`, lon: -77, lat: 38.9, water, toilet });
  }
}
const SWITCHES: WaterPrefs[] = [
  { on: true, basic: true, untreated: true },
  { on: true, basic: false, untreated: true },
  { on: true, basic: true, untreated: false },
  { on: true, basic: false, untreated: false },
];

test("the filter draws exactly the points waterVisible lists, for every kind and every switch", () => {
  for (const prefs of SWITCHES) {
    const { filter } = spec.featureFilter(waterFilter(prefs) as never, "layers[0].filter");
    for (const [k, feature] of waterGeoJson(KINDS).features.entries()) {
      const drawn = filter({ zoom: 14 } as never, { type: 1, properties: feature.properties, geometry: [] } as never);
      assert.equal(drawn, waterVisible(KINDS[k], prefs), `${KINDS[k].id} with ${JSON.stringify(prefs)}`);
    }
  }
});

test("a drawn point never shows an icon its switch hid: a basic toilet with water is its drop when basic is off", () => {
  for (const prefs of SWITCHES) {
    const parsed = spec.expression.createExpression(waterIconImage(prefs) as never, "layers[0].layout.icon-image" as never);
    assert.equal(parsed.result, "success");
    const expr = (parsed as { value: { evaluate(g: unknown, f: unknown): unknown } }).value;
    for (const [k, feature] of waterGeoJson(KINDS).features.entries()) {
      if (!waterVisible(KINDS[k], prefs)) continue;
      const image = String(expr.evaluate({ zoom: 14 }, { type: 1, properties: feature.properties, geometry: [] }));
      const icon = image.replace("water-restrooms-", "") as WaterIcon;
      assert.ok(WATER_ICONS.includes(icon), image);
      if (!prefs.basic) assert.ok(!icon.startsWith("t-b"), `${KINDS[k].id}: ${icon}`);
      if (!prefs.untreated) assert.notEqual(icon, "w-n");
    }
  }
  const basicWithWater = waterGeoJson([{ id: "n1", lon: 0, lat: 0, water: "p", toilet: "b" }]).features[0];
  const off = (spec.expression.createExpression(waterIconImage({ ...ALL, basic: false }) as never, "layers[0].layout.icon-image" as never) as { value: { evaluate(g: unknown, f: unknown): unknown } }).value;
  assert.equal(off.evaluate({ zoom: 14 }, { type: 1, properties: basicWithWater.properties, geometry: [] }), "water-restrooms-w-p");
});

test("the layer validates as MapLibre style, with every switch", () => {
  for (const prefs of SWITCHES) {
    const style = {
      version: 8,
      sources: { [WATER_SOURCE_ID]: { type: "geojson", data: { type: "FeatureCollection", features: [] } } },
      layers: [waterLayer(prefs)],
    };
    assert.deepEqual(spec.validateStyleMin(style as never), []);
  }
});

test("along a bent route: placed on a later segment, counted from the start; a repeated vertex changes nothing", () => {
  // East 0.05 deg, then north 0.02 deg, with the corner given twice.
  const bent: LonLat[] = [
    [-77.1, 38.9],
    [-77.05, 38.9],
    [-77.05, 38.9],
    [-77.05, 38.92],
  ];
  const p: WaterPoint = { id: "n1", lon: -77.05 + 50 / M_PER_DEG_LON, lat: 38.91, water: "p" };
  const [item] = waterAlongRoute(bent, [p]);
  // The bend's own frame is the route's mid-latitude, 38.91; at these sizes that is within a metre or two.
  const kx = 111_320 * Math.cos((38.91 * Math.PI) / 180);
  assert.ok(Math.abs(item.alongM - (0.05 * kx + 0.01 * M_PER_DEG_LAT)) < 1, String(item.alongM));
  assert.ok(Math.abs(item.offM - 50) < 1, String(item.offM));
});

test("the card says the kind, the name, the details and the caution", () => {
  assert.deepEqual(waterCard({ id: "n1", lon: 0, lat: 0, water: "p", name: "Mile 4", bottle: true, fee: "no" }), {
    kind: "Drinking water",
    name: "Mile 4",
    details: ["Bottle filler.", "Free."],
    caution: "From OpenStreetMap: check it is working before you count on it.",
  });
  assert.equal(waterCard({ id: "n2", lon: 0, lat: 0, toilet: "b" }).name, null);
});
