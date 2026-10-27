// v0.8.0's Scenic layer (lib/scenicLayer.ts). The owner, 2026-10-16: "Name in the road panel and have as a layer."
// and "Basically looking for a scenic layer in general. Off by default. How about including covered bridges".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FACILITIES, MTB_LEVELS, MTB_TRAIL, PALETTES, casingWidth, contrastRatio, tiersFor } from "../stressStyle.js";
import { baseSurfaces } from "../testSupport/baseSurfaces.ts";
import { parsePlaces, type SightPlace } from "./places.ts";
import {
  SCENIC_BRIDGE_LABEL_LAYER,
  SCENIC_CASING_LAYER,
  SCENIC_COLOUR,
  SCENIC_FILTER,
  SCENIC_LABEL,
  SCENIC_LEGEND_TEXT,
  SCENIC_NO_PLACES,
  SCENIC_NO_STRESS,
  SCENIC_PLACES_NONE,
  SCENIC_VIEWPOINT_LAYER,
  SCENIC_BRIDGE_LAYER,
  SCENIC_PREF_KEY,
  ScenicLegend,
  ScenicSection,
  readScenicLayer,
  saveScenicLayer,
  scenicCasingLayer,
  scenicGap,
  scenicPointCard,
  scenicPointLayers,
  scenicPointsGeoJson,
  scenicShown,
  scenicStatus,
} from "./scenicLayer.ts";

const STYLE = { version: 8, glyphs: "https://x/{fontstack}/{range}.pbf" };

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

function draws(filter: unknown, properties: Record<string, unknown>): boolean {
  const compiled = spec.featureFilter(filter as never, "layers[0].filter").filter;
  return compiled({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

function gapFor(properties: Record<string, unknown>, tiers = tiersFor("twotone")): number {
  const compiled = spec.expression.createExpression(scenicGap(tiers, false) as never, spec.latest.paint_line["line-gap-width"] as never, "gap" as never);
  assert.equal(compiled.result, "success");
  return (compiled.value as { evaluate: (g: unknown, f: unknown) => number }).evaluate({ zoom: 14 }, { properties, type: 2 });
}

test("off by default, kept on this device, and only in Plan off the Mass Ride map", () => {
  assert.equal(readScenicLayer(memoryStorage()), false);
  assert.equal(readScenicLayer(null), false);
  const storage = memoryStorage();
  saveScenicLayer(true, storage);
  assert.equal(storage.data.get(SCENIC_PREF_KEY), "on");
  assert.equal(readScenicLayer(storage), true);
  assert.equal(scenicShown(true, "plan", false), true);
  assert.equal(scenicShown(true, "go", false), false, "not in Go");
  assert.equal(scenicShown(true, "plan", true), false, "not on the Mass Ride map");
  assert.equal(scenicShown(false, "plan", false), false);
});

test("the casing draws on the tiles' scenic ways only, never a mountain-bike trail", () => {
  const layer = scenicCasingLayer("stress") as { id: string; type: string; filter: unknown; paint: Record<string, unknown> };
  assert.equal(layer.id, SCENIC_CASING_LAYER);
  assert.equal(layer.type, "line");
  assert.deepEqual(layer.filter, SCENIC_FILTER);
  assert.equal(draws(SCENIC_FILTER, { tier: 2, scenic: true }), true);
  assert.equal(draws(SCENIC_FILTER, { tier: 2 }), false);
  assert.equal(draws(SCENIC_FILTER, { tier: 2, scenic: true, mtb: true }), false);
  const errors = spec.validateStyleMin({ ...STYLE, sources: { stress: { type: "vector", tiles: ["https://x/{z}/{x}/{y}"] } }, layers: [layer] } as never);
  assert.deepEqual(errors, []);
});

test("the casing sits outside the stress line, its casing, ring and rails: the stress stays on top", () => {
  const tiers = tiersFor("twotone");
  for (const tier of tiers) {
    assert.ok(gapFor({ tier: tier.tier }, tiers) >= casingWidth(tier) + 2, `tier ${tier.tier}`);
    for (const facility of FACILITIES) {
      assert.ok(gapFor({ tier: tier.tier, facility: facility.facility }, tiers) >= casingWidth(tier) + 2 * facility.rail, `${facility.facility} on tier ${tier.tier}`);
    }
  }
  // A thin line: 1.5 px each side.
  assert.equal((scenicCasingLayer("stress", tiers, false) as { paint: Record<string, unknown> }).paint["line-width"], 1.5);
});

test("the teal is no stress, rail, route-blue or mountain-bike colour, and reads on the base map", () => {
  const taken = new Set<string>();
  for (const palette of Object.values(PALETTES) as Array<Record<string, Record<string, string>>>) {
    for (const tier of Object.values(palette)) for (const value of Object.values(tier)) taken.add(value.toLowerCase());
  }
  for (const f of FACILITIES as Array<{ color: string }>) taken.add(f.color.toLowerCase());
  for (const l of MTB_LEVELS as Array<{ color: string }>) taken.add(l.color.toLowerCase());
  taken.add(MTB_TRAIL.color);
  assert.ok(!taken.has(SCENIC_COLOUR), SCENIC_COLOUR);
  const found = baseSurfaces();
  const failures = Object.entries(found)
    .map(([name, hex]) => [name, contrastRatio(SCENIC_COLOUR, hex)] as const)
    .filter(([, ratio]) => ratio < 3)
    .map(([name, ratio]) => `${name} ${ratio.toFixed(2)}:1`);
  assert.deepEqual(failures, []);
  assert.ok(contrastRatio(SCENIC_COLOUR, "#ffffff") >= 4.5, "the bridges' names on their white halo");
});

const place = (id: string, category: string, name: string, extra: Record<string, unknown> = {}) => ({ id, x: -77.4, y: 39.5, k: category, n: name, ...extra });

test("covered bridges (named) and viewpoints only, from Places to see's file", () => {
  const places = parsePlaces({
    points: [
      place("w1", "bridge", "Roddy Road Covered Bridge", { cv: 1 }),
      place("w2", "bridge", "Notable Viaduct"),
      place("n3", "viewpoint", "Weverton Cliffs"),
      place("n4", "museum", "Rail Museum", { cv: 1 }),
    ],
  }) as SightPlace[];
  assert.equal(places[0].covered, true);
  assert.equal(places[1].covered, undefined);
  assert.equal(places[3].covered, undefined, "only a bridge is a covered bridge");
  const { features } = scenicPointsGeoJson(places) as { features: Array<{ properties: Record<string, string> }> };
  assert.deepEqual(
    features.map((f) => [f.properties.id, f.properties.kind, f.properties.name]),
    [
      ["w1", "bridge", "Roddy Road Covered Bridge"],
      ["n3", "viewpoint", "Weverton Cliffs"],
    ],
  );
  assert.deepEqual(scenicPointCard(places[0]), ["Roddy Road Covered Bridge", "Covered bridge.", "From OpenStreetMap."]);
  assert.deepEqual(scenicPointCard(places[2]), ["Weverton Cliffs", "Viewpoint.", "From OpenStreetMap."]);
  const layers = scenicPointLayers();
  const errors = spec.validateStyleMin({ ...STYLE, sources: { "scenic-points": { type: "geojson", data: { type: "FeatureCollection", features: [] } } }, layers } as never);
  assert.deepEqual(errors, []);
  // A viewpoint is a ring and a bridge a solid dot: shape, not only size (review, PR #138).
  const paint = (id: string) => (layers.find((l) => l.id === id) as { paint: Record<string, unknown> }).paint;
  assert.equal(paint(SCENIC_VIEWPOINT_LAYER)["circle-color"], "#ffffff");
  assert.equal(paint(SCENIC_VIEWPOINT_LAYER)["circle-stroke-color"], SCENIC_COLOUR);
  assert.equal(paint(SCENIC_BRIDGE_LAYER)["circle-color"], SCENIC_COLOUR);
  const label = layers.find((l) => l.id === SCENIC_BRIDGE_LABEL_LAYER) as { layout: Record<string, unknown> };
  assert.deepEqual(label.layout["text-field"], ["get", "name"]);
});

test("one switch in its own section, its hint inside; the status says what cannot show", () => {
  const html = renderToStaticMarkup(createElement(ScenicSection, { on: false, onChange: () => {} }));
  assert.match(html, /role="switch"/);
  assert.match(html, /aria-checked="false"/);
  assert.match(html, new RegExp(`>${SCENIC_LABEL}<`));
  assert.equal((html.match(/role="switch"/g) ?? []).length, 1, "no other control");
  const viewpoint = parsePlaces({ points: [place("n1", "viewpoint", "Weverton Cliffs")] }) as SightPlace[];
  const museum = parsePlaces({ points: [place("n2", "museum", "Rail Museum")] }) as SightPlace[];
  assert.equal(scenicStatus(false, false, "unavailable"), "");
  assert.equal(scenicStatus(true, true, "loading"), "");
  assert.equal(scenicStatus(true, true, viewpoint), "");
  assert.equal(scenicStatus(true, false, "unavailable"), `${SCENIC_NO_STRESS} ${SCENIC_NO_PLACES}`);
  // The file ships empty (review, PR #138): said, not silent; and one with places but none of these is the same.
  assert.equal(scenicStatus(true, true, []), SCENIC_PLACES_NONE);
  assert.equal(scenicStatus(true, true, museum), SCENIC_PLACES_NONE);
});

test("the legend has one entry, in words", () => {
  const html = renderToStaticMarkup(createElement(ScenicLegend));
  assert.equal((html.match(/<li[ >]/g) ?? []).length, 1);
  assert.match(html, /aria-hidden="true"/);
  assert.ok(html.includes(SCENIC_LEGEND_TEXT));
  assert.match(SCENIC_LEGEND_TEXT, /road panel names each/);
});

test("the page wires it: Plan's Layers after Trails and terrain, not in Go, under the stress layers", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  const sheets = read("../app/Sheets.tsx");
  const app = read("../App.tsx");
  const overlay = read("../app/ScenicOverlay.tsx");
  assert.ok(sheets.indexOf('title={t("Trails and terrain")}') < sheets.indexOf("<ScenicSection"));
  assert.match(sheets, /\{scenic && <ScenicSection \{\.\.\.scenic\} drawn=\{scenicDrawn\} \/>\}/);
  assert.match(app, /scenic: mode === "go" \? null :/);
  assert.match(app, /on=\{scenicShown\(scenicOn, mode, massMap\)\}/);
  // Its key is inside its section while it is drawn (the owner, 2026-10-19).
  assert.match(app, /scenicDrawn: scenicShown\(scenicOn, mode, massMap\)/);
  assert.match(overlay, /map\.addLayer\(scenicCasingLayer\(STRESS_SOURCE_ID\) as never, lowestStressLayer\(map\)\)/);
});
