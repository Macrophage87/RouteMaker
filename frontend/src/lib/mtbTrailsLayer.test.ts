// OWNER-DECISIONS 454: "Three map layers for everyone (every mode, signed out too), off until
// clicked on: topo lines, climbs, mountain-bike trails." and "The mountain-bike trail layer
// replaces the always-drawn 'not used for routes' trails (452a); those trails are hidden until
// the layer is turned on." The switch's state and persistence, the map layer's visibility in
// every mode with the stress map on or off, the wiring in MapView and App, and the switch's markup.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  MTB_MIN_ZOOM,
  MTB_TRAILS_STORAGE_KEY,
  MTB_TRAIL_LAYER_ID,
  MTB_LAYER_IDS,
  MTB_LEVELS,
  mtbTrailLayers,
  mtbTrailsOn,
  rememberMtbTrails,
  setMassRide,
  setMtbTrails,
  storedMtbTrails,
  stressFilters,
  stressOverlayLayers,
  subscribeMtbTrails,
} from "../stressStyle.js";
import { massLayerIds } from "../massStyle.js";
import { addStressOverlay, overlayLayerShown, setStressVisibility, type OverlayMap } from "./mapGlue.ts";
import { MTB_LEGEND, MtbTrailLegend, mtbLevelLegend } from "./stressLegend.ts";
import { STRESS_SOURCE_ID } from "./mapStyle.ts";
import { MTB_TRAILS_HINT, MTB_TRAILS_LABEL, MTB_TRAILS_NO_MAP_HINT, MtbTrailsSwitch } from "./mtbTrailsSwitch.ts";
import { appSource } from "../testSupport/appSource.mjs";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

/** A stand-in map with every overlay layer, recording each layer's visibility. */
function fakeMap(): { map: OverlayMap; visibility: Map<string, string> } {
  const visibility = new Map<string, string>();
  const ids = new Set(stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => l.id));
  const map = {
    getLayer: (id: string) => (ids.has(id) ? {} : undefined),
    setLayoutProperty: (id: string, name: string, value: string) => {
      if (name === "visibility") visibility.set(id, value);
    },
  } as unknown as OverlayMap;
  return { map, visibility };
}

// ---- the switch's state -----------------------------------------------------

test("the layer is off until the rider turns it on: nothing remembered reads as off", () => {
  assert.equal(mtbTrailsOn(), false);
  assert.equal(storedMtbTrails(memoryStorage()), null);
});

test("the layer is remembered per browser, as 'on' or 'off', and reads back; a value this page did not write is ignored", () => {
  assert.equal(MTB_TRAILS_STORAGE_KEY, "routemaker.mtbTrails");
  const storage = memoryStorage();
  assert.equal(rememberMtbTrails(true, storage), true);
  assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "on");
  assert.equal(storedMtbTrails(storage), true);
  rememberMtbTrails(false, storage);
  assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "off");
  assert.equal(storedMtbTrails(storage), false);
  assert.equal(storedMtbTrails(memoryStorage({ [MTB_TRAILS_STORAGE_KEY]: "true" })), null);
});

test("storage that throws or is missing never breaks the switch: it lasts the visit", () => {
  const throwing = {
    getItem: (): string | null => {
      throw new Error("SecurityError");
    },
    setItem: (): void => {
      throw new Error("SecurityError");
    },
  };
  assert.equal(storedMtbTrails(throwing), null);
  assert.equal(rememberMtbTrails(true, throwing), false);
  assert.equal(rememberMtbTrails(true, null as never), false);
  try {
    setMtbTrails(true, { storage: throwing });
    assert.equal(mtbTrailsOn(), true);
  } finally {
    setMtbTrails(false, { remember: false });
  }
});

test("turning it on or off tells each subscriber once, saves the choice, and a stopped subscriber hears nothing", () => {
  const heard: boolean[] = [];
  const stop = subscribeMtbTrails((on) => heard.push(on));
  const storage = memoryStorage();
  try {
    setMtbTrails(true, { storage });
    setMtbTrails(true, { storage }); // no change: no second call
    assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "on");
    setMtbTrails(false, { storage });
    assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "off");
    assert.deepEqual(heard, [true, false]);
    stop();
    setMtbTrails(true, { remember: false });
    assert.deepEqual(heard, [true, false]);
  } finally {
    stop();
    setMtbTrails(false, { remember: false });
  }
});

let loads = 0;
/** A fresh copy of stressStyle.js, evaluated as a page load would with this localStorage. */
async function loadedWith(storage: unknown): Promise<{ mtbTrailsOn(): boolean }> {
  const saved = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
  try {
    loads += 1;
    return (await import(`../stressStyle.js?mtb=${loads}`)) as { mtbTrailsOn(): boolean };
  } finally {
    if (saved) Object.defineProperty(globalThis, "localStorage", saved);
    else delete (globalThis as Record<string, unknown>).localStorage;
  }
}

test("on load: off with nothing stored, 'off' or a stray value; on only when 'on' was stored", async () => {
  assert.equal((await loadedWith(memoryStorage())).mtbTrailsOn(), false);
  assert.equal((await loadedWith(memoryStorage({ [MTB_TRAILS_STORAGE_KEY]: "off" }))).mtbTrailsOn(), false);
  assert.equal((await loadedWith(memoryStorage({ [MTB_TRAILS_STORAGE_KEY]: "garbage" }))).mtbTrailsOn(), false);
  assert.equal((await loadedWith(memoryStorage({ [MTB_TRAILS_STORAGE_KEY]: "on" }))).mtbTrailsOn(), true);
  assert.equal((await loadedWith(undefined)).mtbTrailsOn(), false, "no storage at all");
});

// ---- the map ----------------------------------------------------------------

test("in Mass Ride the trails' line still draws a trail that carries a capacity: only the other layers take `massHides`", () => {
  const draws = (filter: unknown, properties: Record<string, unknown>) =>
    spec.featureFilter(filter as never, "layers[mtb-trail].filter").filter({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
  for (const when of ["weekday_offpeak", "weekday_rush", "weekend"]) {
    const filters = stressFilters(when, false, true);
    assert.equal(draws(filters[MTB_TRAIL_LAYER_ID], { mtb: true, trail: true, tier: 1, rpm: 80 }), true, when);
    assert.equal(draws(filters[MTB_TRAIL_LAYER_ID], { mtb: true, trail: true, tier: 1 }), true, when);
    assert.deepEqual(filters[MTB_TRAIL_LAYER_ID], stressFilters(when, false, false)[MTB_TRAIL_LAYER_ID], "the same filter in both modes");
    // A routable layer still drops a feature with a capacity in Mass Ride.
    assert.equal(draws(filters["stress-1"], { tier: 1, rpm: 80 }), false, when);
  }
});

test("the overlay is added with the trails' layer as the switch says, whatever the stress switch", () => {
  try {
    for (const mtb of [false, true]) {
      setMtbTrails(mtb, { remember: false });
      for (const visible of [true, false]) {
        const added: Array<{ id: string; layout?: { visibility?: string } }> = [];
        const map = {
          getSource: () => undefined,
          addSource: () => {},
          getStyle: () => ({ layers: [] }),
          addLayer: (layer: { id: string; layout?: { visibility?: string } }) => void added.push(layer),
          getLayer: () => undefined,
          setLayoutProperty: () => {},
          setFilter: () => {},
          setPaintProperty: () => {},
        } as unknown as OverlayMap;
        addStressOverlay(map, "https://example.test", visible);
        const layer = added.find((l) => l.id === MTB_TRAIL_LAYER_ID);
        assert.equal(layer?.layout?.visibility, mtb ? "visible" : "none", `mtb ${mtb}, stress ${visible}`);
      }
    }
  } finally {
    setMtbTrails(false, { remember: false });
  }
});

test("the not-for-routes line and each level's casing and line are the layers the switch names", () => {
  assert.equal(MTB_TRAIL_LAYER_ID, "mtb-trail");
  assert.deepEqual(
    mtbTrailLayers().map((l: { id: string }) => l.id),
    MTB_LAYER_IDS.slice(0, -2),
  );
  assert.equal(MTB_LAYER_IDS[0], "mtb-trail-ticks", "the shared ticks at the bottom");
  assert.ok(MTB_LAYER_IDS.includes(MTB_TRAIL_LAYER_ID));
  assert.equal(MTB_LAYER_IDS.length, 13, "the ticks, the unrated trails' edge and dashes, four edges and four lines (456), Mountain Bike's zoomed-out line (2026-10-28) and the names (2026-10-10)");
  assert.equal(MTB_LAYER_IDS.at(-2), "mtb-trail-overview");
  assert.equal(MTB_LAYER_IDS.at(-1), "mtb-trail-label");
});

test("the trails show by their own switch alone: with the stress map on or off, in every ride type, Mass Ride too", () => {
  for (const visible of [true, false]) {
    for (const mass of [true, false]) {
      for (const id of MTB_LAYER_IDS) {
        assert.equal(overlayLayerShown(id, visible, mass, true), true, `${id} on, stress ${visible}, mass ${mass}`);
        assert.equal(overlayLayerShown(id, visible, mass, false), false, `${id} off, stress ${visible}, mass ${mass}`);
      }
    }
  }
  // It reads the switch when not told.
  assert.equal(overlayLayerShown(MTB_TRAIL_LAYER_ID, true), false);
  setMtbTrails(true, { remember: false });
  try {
    assert.equal(overlayLayerShown(MTB_TRAIL_LAYER_ID, false), true);
  } finally {
    setMtbTrails(false, { remember: false });
  }
});

test("the switch moves no other layer: each stress and Mass Ride layer shows as it did", () => {
  const ids = stressOverlayLayers(STRESS_SOURCE_ID)
    .map((l: { id: string }) => l.id)
    .filter((id: string) => !MTB_LAYER_IDS.includes(id));
  const mass = new Set<string>(massLayerIds());
  assert.ok(ids.length > 10);
  for (const id of ids) {
    for (const visible of [true, false]) {
      for (const massOn of [true, false]) {
        const before = visible && (mass.has(id) ? massOn : !massOn);
        for (const mtb of [true, false]) assert.equal(overlayLayerShown(id, visible, massOn, mtb), before, `${id} ${visible} ${massOn} ${mtb}`);
      }
    }
  }
});

test("setting the overlay's visibility sets the trails' by the switch, and the rest by the stress switch", () => {
  try {
    for (const mtb of [false, true]) {
      setMtbTrails(mtb, { remember: false });
      for (const visible of [true, false]) {
        const { map, visibility } = fakeMap();
        setStressVisibility(map, visible);
        for (const id of MTB_LAYER_IDS) assert.equal(visibility.get(id), mtb ? "visible" : "none", `${id}: mtb ${mtb}, stress ${visible}`);
        assert.equal(visibility.get("stress-1"), visible ? "visible" : "none");
      }
    }
  } finally {
    setMtbTrails(false, { remember: false });
    setMassRide(false);
  }
});

test("MapView shows or hides the layer in place when the switch changes, and App puts the switch in the Map layers sheet", () => {
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /subscribeMtbTrails\(\(\) => \{\s*const map = mapRef\.current;\s*if \(map && loaded\.current\) setStressVisibility\(map, callbacks\.current\.stressVisible\);/);
  const app = appSource();
  const sheet = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  // The Trails and terrain section (lib/layerSection.ts): its switch turns the three on or off together; the
  // layer's own switch is the first inside.
  assert.match(sheet, /<LayerSection\s+id="terrain"\s+title=\{t\("Trails and terrain"\)\}\s+headingId="terrain-heading"/);
  // Its layers through lib/terrainSection.ts (the trails only with the stress map; terrainSection.test.ts).
  assert.match(app, /const terrain = \{ mtb: showMtbTrails, climbs: climbsOn, topo: showTopoLines, stressAvailable: stressShowable\(stress\), topoReady, climbsStatus \};/);
  assert.match(sheet, /layers=\{terrainLayers\(terrain\)\}/);
  assert.match(sheet, /if \("mtb" in next && next\.mtb !== showMtbTrails\) setMtbTrails\(next\.mtb\);/);
  const terrain = sheet.slice(sheet.indexOf('<LayerSection\n        id="terrain"'));
  assert.match(terrain.slice(0, terrain.indexOf("</LayerSection>")), /\}\s*>\s*<MtbTrailsSwitch on=\{showMtbTrails\} onChange=\{\(on\) => setMtbTrails\(on\)\} overlay=\{stressShowable\(stress\)\} \/>/, "its hint says unavailable only once the stress map is known to be down, not while it is checked");
  // Every ride type: not inside a ride-type condition.
  const at = sheet.indexOf('<LayerSection\n        id="terrain"');
  assert.ok(at > 0 && !/&&|\?\s*$/.test(sheet.slice(at - 40, at).trim().split("\n").pop() ?? ""), "the section is not behind a condition");
});

// ---- the switch -------------------------------------------------------------

test("the switch is a named button with role switch, its state, and a short plain-words description", () => {
  const off = renderToStaticMarkup(createElement(MtbTrailsSwitch, { on: false, onChange: () => {} }));
  assert.match(off, /<button type="button" role="switch" id="mtb-trails-switch" class="switch" aria-checked="false" aria-labelledby="mtb-trails-label" aria-describedby="mtb-trails-hint">/);
  assert.equal(MTB_TRAILS_LABEL, "Mountain-bike trails");
  assert.match(off, /<span id="mtb-trails-label" class="switch-label">Mountain-bike trails<\/span>/);
  assert.match(off, /<span class="switch-state" aria-hidden="true">Off<\/span>/);
  assert.match(off, new RegExp(`<p class="hint" id="mtb-trails-hint">${MTB_TRAILS_HINT}</p>`));
  assert.match(MTB_TRAILS_HINT, new RegExp(`from zoom ${MTB_MIN_ZOOM}`, "i"));
  // One short line (the owner, 2026-10-12: "less wordy"); the levels and the Gravel note are the legend's rows.
  assert.equal(MTB_TRAILS_HINT, `From zoom ${MTB_MIN_ZOOM}. Only off-road ride types route on them.`);
  for (const hint of [MTB_TRAILS_HINT, MTB_TRAILS_NO_MAP_HINT]) assert.ok(hint.length <= 60, `${hint.length} characters`);
  const on = renderToStaticMarkup(createElement(MtbTrailsSwitch, { on: true, onChange: () => {} }));
  assert.match(on, /aria-checked="true"/);
  assert.match(on, />On<\/span>/);
  const noMap = renderToStaticMarkup(createElement(MtbTrailsSwitch, { on: false, onChange: () => {}, overlay: false }));
  assert.ok(noMap.includes(MTB_TRAILS_NO_MAP_HINT));
});

test("pressing the switch asks for the opposite state", () => {
  const got: boolean[] = [];
  for (const on of [false, true]) {
    const element = MtbTrailsSwitch({ on, onChange: (next) => void got.push(next) });
    const button = (element.props.children as Array<{ type?: string; props?: { onClick?: () => void } }>).find((c) => c?.type === "button");
    button?.props?.onClick?.();
  }
  assert.deepEqual(got, [true, false]);
});

// ---- the Mass Ride legend ---------------------------------------------------

test("the trails' key names their line while the layer is on, and nothing while it is off", () => {
  assert.equal(renderToStaticMarkup(createElement(MtbTrailLegend)), "");
  setMtbTrails(true, { remember: false });
  try {
    const html = renderToStaticMarkup(createElement(MtbTrailLegend));
    assert.match(html, /^<ul class="legend" aria-label="Mountain-bike trail legend"><li class="mtb-trail"><svg [^>]*aria-hidden="true"/);
    const text = html.replace(/<svg[\s\S]*?<\/svg>/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const levels = MTB_LEVELS.map((shape: (typeof MTB_LEVELS)[number]) => `${mtbLevelLegend(shape).short} ${mtbLevelLegend(shape).label}`);
    assert.equal(text, [`${MTB_LEGEND!.short} ${MTB_LEGEND!.label}`, ...levels].join(" "));
    // The level rows too, each with its number in words (456).
    for (const level of [1, 2, 3, 4]) assert.match(html, new RegExp(`<li class="mtb-level mtb-level-${level}"><svg [^>]*aria-hidden="true"`));
  } finally {
    setMtbTrails(false, { remember: false });
  }
  const app = appSource();
  // In every ride type, Mass Ride's too, the key is in Layers' Trails and terrain section, under its switch.
  assert.equal((app.match(/<MtbTrailLegend \/>/g) ?? []).length, 1);
  assert.match(app, /<MtbTrailsSwitch [^\n]*\/>\s*\{\/\*[^}]*\*\/\}\s*<MtbTrailLegend \/>/);
});

// ---- the owner, 2026-10-19: a key on the map, and a tap on a trail tells about it ----

import { mtbTrailAt, mtbTrailPressed } from "./mapGlue.ts";
import { MTB_MAP_KEY_HINT, MTB_MAP_KEY_TITLE, MtbMapKey, mtbMapKeyRows } from "./stressLegend.ts";
import { segmentInfoUrl, trailNotRouted, TRAIL_VIA_TEXT, type SegmentInfo } from "./roadInfo.ts";
import { MTB_LINE_LAYER_IDS } from "../stressStyle.js";

test("a press on a drawn trail line is the trail's, at the nearest point on it, unless a road's line is nearer", () => {
  // A flat screen: one pixel a thousandth of a degree, x east and y south.
  const project = ([lon, lat]: [number, number]) => ({ x: lon * 1000, y: -lat * 1000 });
  const unproject = ([x, y]: [number, number]) => ({ lng: x / 1000, lat: -y / 1000 });
  const trail = { properties: { mtb: true }, geometry: { type: "LineString", coordinates: [[0.1, -0.0], [0.1, -0.1]] } };
  const road = { properties: {}, geometry: { type: "MultiLineString", coordinates: [[[0.0, -0.05], [0.2, -0.05]]] } };
  let asked: string[] = [];
  const mapOf = (features: unknown[]) => ({
    getLayer: (id: string) => (id === "ghost" ? undefined : {}),
    queryRenderedFeatures: (_box: unknown, options: { layers: string[] }) => {
      asked = options.layers;
      return features;
    },
    project,
    unproject,
  });
  const layers = [...MTB_LINE_LAYER_IDS, "stress-1", "ghost"];
  // 6 px east of the trail: the panel asks at the point on the trail level with the press.
  const at = mtbTrailPressed(mapOf([trail]), { x: 106, y: 30 }, 8, layers);
  assert.ok(at);
  assert.ok(Math.abs(at[0] - 0.1) < 1e-9 && Math.abs(at[1] + 0.03) < 1e-9);
  assert.deepEqual(asked, [...MTB_LINE_LAYER_IDS, "stress-1"]);
  // A road crossing nearer the press than the trail: the road's press (a point, as before).
  assert.equal(mtbTrailPressed(mapOf([trail, road]), { x: 106, y: 51 }, 8, layers), null);
  // The trail nearer than the road: still the trail's.
  assert.ok(mtbTrailPressed(mapOf([trail, road]), { x: 101, y: 60 }, 8, layers));
  // Nothing drawn under the press, or no layer on the map: nothing.
  assert.equal(mtbTrailPressed(mapOf([]), { x: 106, y: 30 }, 8, layers), null);
  const none = { ...mapOf([]), getLayer: () => undefined, queryRenderedFeatures: () => assert.fail("not asked") };
  assert.equal(mtbTrailPressed(none, { x: 100, y: 50 }, 8, layers), null);
  // The hover card's way: the feature's id, else its first point.
  assert.equal(mtbTrailAt(mapOf([{ ...trail, id: 42 }]), { x: 106, y: 30 }, 8, layers)?.way, "42");
  assert.equal(mtbTrailAt(mapOf([trail]), { x: 106, y: 30 }, 8, layers)?.way, "0.100000,0.000000");
});

test("a trail tap asks the road panel for the trail, and offers Route through this trail only where the ride type uses it", () => {
  assert.equal(segmentInfoUrl("https://x", [-77, 38.9], true), "https://x/api/segment-info?lat=38.900000&lon=-77.000000&trail=true");
  assert.equal(segmentInfoUrl("https://x", [-77, 38.9]), "https://x/api/segment-info?lat=38.900000&lon=-77.000000");
  assert.equal(TRAIL_VIA_TEXT, "Route through this trail");
  const info = (over: Partial<SegmentInfo>) => ({ mtb_trail: true, trail_open: "offroad", trail_level: 3, ...over }) as SegmentInfo;
  const rider = (rideType: string, mtbLevel: number | null = null) => ({ rideType, mtbLevel });
  for (const type of ["gravel", "mountain-goat"]) assert.equal(trailNotRouted(info({}), rider(type)), null);
  assert.equal(trailNotRouted(info({}), rider("mountain-bike", 3)), null);
  assert.match(trailNotRouted(info({}), rider("mountain-bike", 2)) ?? "", /above the level you chose/);
  assert.match(trailNotRouted(info({}), rider("road")) ?? "", /Only Gravel, Mountain Goat and Mountain Bike/);
  assert.match(trailNotRouted(info({ trail_open: null }), rider("mountain-bike", 4)) ?? "", /No ride type/);
  // Above Gravel's level: Mountain Bike's alone.
  assert.match(trailNotRouted(info({ trail_open: "mtb" }), rider("gravel")) ?? "", /Only Mountain Bike/);
  assert.equal(trailNotRouted(info({ trail_open: "mtb" }), rider("mountain-bike", 4)), null);
  // Not a trail: nothing to say.
  assert.equal(trailNotRouted(info({ mtb_trail: false }), rider("road")), null);
  assert.equal(trailNotRouted(null, rider("road")), null);
  assert.match(readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8"), /trail: true/);
});

test("the map key names each look the layer draws, while it draws", () => {
  assert.deepEqual(
    mtbMapKeyRows().map((r) => r.name),
    ["Unrated", "1 Green", "2 Blue", "3 Black", "4 Red"],
  );
  setMtbTrails(true);
  try {
    const shown = renderToStaticMarkup(createElement(MtbMapKey, { drawn: true }));
    assert.match(shown, new RegExp(`aria-label="${MTB_MAP_KEY_TITLE} key"`));
    assert.match(shown, new RegExp(MTB_MAP_KEY_HINT));
    assert.equal((shown.match(/<li>/g) ?? []).length, 5);
    assert.equal(renderToStaticMarkup(createElement(MtbMapKey, { drawn: false })), "");
  } finally {
    setMtbTrails(false);
  }
  assert.equal(renderToStaticMarkup(createElement(MtbMapKey, { drawn: true })), "");
});
