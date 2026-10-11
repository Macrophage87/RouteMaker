// The "Topo lines" layer (OWNER-DECISIONS 454; docs/MTB-TOPO-PLAN.md slice 4). The owner, 2026-10-10:
// "For topo, have the lines scale with zoom." Spacing by zoom (100 ft to zoom 12, 40 ft at 13, 20 ft
// from 14), every fifth line an index line with a feet-first label, widths growing with zoom; the
// switch's state and persistence, lazy adding and visibility, and the wiring in App and MapView.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { contrastRatio } from "../stressStyle.js";
import {
  TOPO_BANDS,
  TOPO_COLOURS,
  TOPO_INDEX_EVERY,
  TOPO_LINES_HINT,
  TOPO_LINES_LABEL,
  TOPO_LINES_UNAVAILABLE_HINT,
  TOPO_SOURCE_ID,
  TOPO_SOURCE_LAYERS,
  TOPO_STORAGE_KEY,
  TOPO_WIDTHS,
  TopoLinesSwitch,
  rememberTopoLines,
  setTopoLines,
  storedTopoLines,
  subscribeTopoLines,
  syncTopoLines,
  topoAvailable,
  topoBeforeId,
  topoLabel,
  topoLayerIds,
  topoLayers,
  topoLinesOn,
  topoSource,
  type TopoMap,
} from "./topoLines.ts";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

/** What each archive layer holds: elevations whose coarsest spacing is its own (scripts/build_contours.py band_of). */
function holds(layer: string, feet: number): boolean {
  const coarsest = TOPO_SOURCE_LAYERS.find((s) => feet % s.intervalFt === 0);
  return coarsest?.layer === layer;
}

/** Evaluate a layer's filter on one feature at one zoom, with MapLibre's own expression engine. */
function shows(layer: Record<string, unknown>, feet: number, zoom: number): boolean {
  if (zoom < (layer.minzoom as number) || zoom >= (layer.maxzoom as number)) return false;
  if (!holds(layer["source-layer"] as string, feet)) return false;
  const filter = spec.featureFilter(layer.filter as never, `layers[${layer.id as string}].filter` as never);
  return filter.filter({ zoom }, { type: 2, properties: { ele_ft: feet }, geometry: [] } as never);
}

const kinds = (feet: number, zoom: number) => {
  const drawn = topoLayers().filter((l) => shows(l, feet, zoom));
  return new Set(drawn.map((l) => (l.id as string).replace(/^topo-\d+-c\d+-/, "")));
};

test("the layers are valid MapLibre style layers with one source", () => {
  const style = {
    version: 8,
    glyphs: "https://x.example/{fontstack}/{range}.pbf",
    sources: { [TOPO_SOURCE_ID]: topoSource() },
    layers: topoLayers(),
  };
  assert.deepEqual(spec.validateStyleMin(style as never), []);
  assert.equal(new Set(topoLayerIds()).size, topoLayerIds().length, "ids are unique");
});

test("the spacing follows the zoom: 100 ft to zoom 12, 40 ft at zoom 13, 20 ft from zoom 14 (the owner, 2026-10-10)", () => {
  const drawnAt = (zoom: number) => {
    const out: number[] = [];
    for (let feet = 20; feet <= 1200; feet += 20) if (kinds(feet, zoom).has("line") || kinds(feet, zoom).has("index")) out.push(feet);
    return out;
  };
  for (const zoom of [10, 11, 12, 12.9]) assert.deepEqual(drawnAt(zoom), Array.from({ length: 12 }, (_, i) => (i + 1) * 100), `zoom ${zoom}`);
  assert.deepEqual(drawnAt(13), Array.from({ length: 30 }, (_, i) => (i + 1) * 40));
  for (const zoom of [14, 16, 20]) assert.deepEqual(drawnAt(zoom), Array.from({ length: 60 }, (_, i) => (i + 1) * 20), `zoom ${zoom}`);
  assert.deepEqual(drawnAt(9), [], "nothing below the archive's lowest zoom");
});

test("every fifth line is an index line, drawn once, heavier, and labelled; the rest are plain lines", () => {
  for (const band of TOPO_BANDS) {
    const zoom = band.minzoom;
    for (let k = 1; k <= 20; k++) {
      const feet = k * band.intervalFt;
      const got = kinds(feet, zoom);
      if (k % TOPO_INDEX_EVERY === 0) assert.deepEqual(got, new Set(["index", "label"]), `${feet} ft at ${zoom}`);
      else assert.deepEqual(got, new Set(["line"]), `${feet} ft at ${zoom}`);
    }
  }
  // No line is drawn twice at a zoom: exactly one line layer and at most one label.
  for (let feet = 20; feet <= 2000; feet += 20) {
    for (const zoom of [10, 13, 14, 17]) {
      const lines = topoLayers().filter((l) => l.type === "line" && shows(l, feet, zoom));
      assert.ok(lines.length <= 1, `${feet} ft at ${zoom}: ${lines.map((l) => l.id)}`);
    }
  }
});

test("widths grow with zoom, and an index line is heavier than a plain one at every zoom", () => {
  for (const stops of [TOPO_WIDTHS.line, TOPO_WIDTHS.index]) {
    for (let i = 3; i < stops.length; i += 2) assert.ok(stops[i] > stops[i - 2], `widths rise: ${stops}`);
  }
  for (let i = 1; i < TOPO_WIDTHS.line.length; i += 2) assert.ok(TOPO_WIDTHS.index[i] >= 1.8 * TOPO_WIDTHS.line[i]);
  const line = topoLayers().find((l) => (l.id as string).endsWith("-line")) as { paint: Record<string, unknown> };
  assert.deepEqual((line.paint["line-width"] as unknown[]).slice(0, 3), ["interpolate", ["linear"], ["zoom"]]);
});

test("labels are feet first with metres in brackets, legible on their halo, and the look is not colour alone", () => {
  assert.equal(topoLabel(500), "500 ft (152 m)");
  assert.equal(topoLabel(100), "100 ft (30 m)");
  const label = topoLayers().find((l) => l.type === "symbol") as { layout: Record<string, unknown> };
  const expr = spec.expression.createExpression(label.layout["text-field"] as never, spec.latest.layout_symbol["text-field"] as never, "layers[0].layout.text-field" as never);
  assert.equal(expr.result, "success");
  const value = (expr as { value: { evaluate: (g: unknown, f: unknown) => unknown } }).value.evaluate(
    { zoom: 14 },
    { type: 2, properties: { ele_ft: 1200 } },
  );
  assert.equal(String(value), topoLabel(1200));
  assert.ok(contrastRatio(TOPO_COLOURS.label, TOPO_COLOURS.halo) >= 4.5);
  assert.ok(contrastRatio(TOPO_COLOURS.index, "#ffffff") > contrastRatio(TOPO_COLOURS.line, "#ffffff"), "index darker");
});

test("the archive's layers are the build script's: names, spacings and tile zooms", () => {
  const script = readFileSync(new URL("../../../scripts/build_contours.py", import.meta.url), "utf8");
  for (const { layer, intervalFt, minzoom } of TOPO_SOURCE_LAYERS) {
    assert.match(script, new RegExp(`Band\\("${layer}", ${intervalFt}, ${minzoom}\\)`), layer);
  }
  assert.match(script, /^MAXZOOM = 14$/m);
  assert.match(script, /^OUTPUT_NAME = "contours\.pmtiles"$/m);
  // A band reads every archive layer that holds a line it draws, and none that holds none.
  for (const band of TOPO_BANDS) {
    for (const { layer, minzoom } of TOPO_SOURCE_LAYERS) {
      let any = false;
      for (let feet = 20; feet <= 2000; feet += 20) if (holds(layer, feet) && feet % band.intervalFt === 0) any = true;
      assert.equal(band.sourceLayers.includes(layer), any, `${layer} at ${band.intervalFt} ft`);
      if (any) assert.ok(minzoom <= band.minzoom, `${layer} is tiled by zoom ${band.minzoom}`);
    }
  }
});

test("the source is the archive beside the base map, credits the look, and goes under the roads", () => {
  const source = topoSource() as { url: string; attribution: string };
  assert.equal(source.url, "pmtiles:///basemap/contours.pmtiles");
  assert.match(source.attribution, /OpenTopoMap/);
  assert.equal(topoBeforeId(["background", "earth", "water", "roads_tunnels_other_casing", "places_country"]), "roads_tunnels_other_casing");
  assert.equal(topoBeforeId(["background", "places_locality"]), "places_locality");
  assert.equal(topoBeforeId(["background"]), undefined);
});

/** A stand-in map recording what is added and each layer's visibility. */
function fakeMap() {
  const sources = new Map<string, unknown>();
  const layers: { id: string; before?: string }[] = [{ id: "earth" }, { id: "roads_minor" }];
  const visibility = new Map<string, unknown>();
  const map: TopoMap = {
    getSource: (id) => sources.get(id),
    getLayer: (id) => layers.find((l) => l.id === id),
    addSource: (id, s) => void sources.set(id, s),
    addLayer: (layer, before) => void layers.push({ id: (layer as { id: string }).id, before }),
    setLayoutProperty: (id, name, value) => {
      if (name === "visibility") visibility.set(id, value);
    },
    getStyle: () => ({ layers }),
  };
  return { map, sources, layers, visibility };
}

test("nothing is fetched until the layer is first shown; then it is shown and hidden in place", () => {
  const { map, sources, layers, visibility } = fakeMap();
  syncTopoLines(map, false);
  assert.equal(sources.size, 0, "off: no source, so no archive request");
  syncTopoLines(map, true);
  assert.ok(sources.has(TOPO_SOURCE_ID));
  const added = layers.filter((l) => l.id.startsWith("topo-"));
  assert.deepEqual(added.map((l) => l.id), topoLayerIds());
  assert.ok(added.every((l) => l.before === "roads_minor"), "under the base map's roads");
  syncTopoLines(map, false);
  assert.ok(topoLayerIds().every((id) => visibility.get(id) === "none"));
  syncTopoLines(map, true);
  assert.ok(topoLayerIds().every((id) => visibility.get(id) === "visible"));
  assert.equal(layers.filter((l) => l.id.startsWith("topo-")).length, topoLayerIds().length, "added once");
});

test("the switch is off until turned on, remembered per browser, and tells its subscribers", () => {
  assert.equal(topoLinesOn(), false);
  assert.equal(TOPO_STORAGE_KEY, "routemaker.topoLines");
  const storage = memoryStorage();
  assert.equal(storedTopoLines(storage), null);
  rememberTopoLines(true, storage);
  assert.equal(storedTopoLines(storage), true);
  rememberTopoLines(false, storage);
  assert.equal(storedTopoLines(storage), false);
  assert.equal(storedTopoLines(memoryStorage({ [TOPO_STORAGE_KEY]: "yes" })), null, "a value this page did not write");
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(storedTopoLines(throwing), null);
  rememberTopoLines(true, throwing);
  const seen: boolean[] = [];
  const stop = subscribeTopoLines((on) => seen.push(on));
  setTopoLines(true, { storage });
  setTopoLines(true, { storage });
  setTopoLines(false, { remember: false, storage });
  stop();
  setTopoLines(true, { remember: false });
  setTopoLines(false, { remember: false });
  assert.deepEqual(seen, [true, false]);
  assert.equal(storedTopoLines(storage), true, "remember: false leaves the stored choice");
});

test("the switch is a real switch with a name, a state and a description; unavailable says so politely", () => {
  const on = renderToStaticMarkup(createElement(TopoLinesSwitch, { on: true, onChange: () => {} }));
  assert.match(on, /role="switch"/);
  assert.match(on, /aria-checked="true"/);
  assert.match(on, /aria-labelledby="topo-lines-label"/);
  assert.match(on, /aria-describedby="topo-lines-hint"/);
  assert.ok(on.includes(TOPO_LINES_LABEL));
  assert.ok(on.includes(TOPO_LINES_HINT.replace(/'/g, "&#x27;")));
  assert.match(on, /aria-live="polite"/);
  assert.ok(TOPO_LINES_HINT.length < 150, "short: read on every focus");
  assert.match(TOPO_LINES_HINT, /100 ft \(30 m\).*40 ft \(12 m\).*20 ft \(6 m\)/);
  const off = renderToStaticMarkup(createElement(TopoLinesSwitch, { on: false, onChange: () => {}, available: false }));
  assert.match(off, /aria-checked="false"/);
  assert.ok(off.includes(TOPO_LINES_UNAVAILABLE_HINT));
});

test("availability is a HEAD of the archive; a 404 or a network failure is unavailable", async () => {
  const asked: unknown[] = [];
  const ok = (async (url: string, init: unknown) => {
    asked.push([url, init]);
    return { ok: true } as Response;
  }) as unknown as typeof fetch;
  assert.equal(await topoAvailable(ok), true);
  assert.deepEqual(asked, [["/basemap/contours.pmtiles", { method: "HEAD" }]]);
  assert.equal(await topoAvailable((async () => ({ ok: false }) as Response) as unknown as typeof fetch), false);
  assert.equal(await topoAvailable((async () => { throw new Error("offline"); }) as unknown as typeof fetch), false);
});

test("App puts the switch under Trails and terrain; MapView keeps the map in line with it", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const section = app.slice(app.indexOf('<h3 id="terrain-heading">'), app.indexOf("</section>", app.indexOf('<h3 id="terrain-heading">')));
  assert.match(section, /<TopoLinesSwitch on=\{showTopoLines\} onChange=\{\(on\) => setTopoLines\(on\)\} available=\{topoReady\} \/>/);
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(mapView, /subscribeTopoLines\(sync\)/);
  assert.match(mapView, /syncTopoLines\(map as unknown as TopoMap, topoLinesOn\(\)\)/);
  assert.match(mapView, /map\.on\("load", sync\)/);
});
