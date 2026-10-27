// The state and county lines (stressStyle.js, BOUNDARY_LINE; the owner, 2026-10-27: "Add state and county lines to
// the map."): the base map's boundaries layer, as this app ships it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { featureFilter, validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { BOUNDARY_LAYER_ID, BOUNDARY_LINE, ZOOMED_OUT_NEAR_ZOOM, contrastRatio, currentTiers, withClearRoadLabels, zoomedOutLine } from "./stressStyle.js";

type Layer = { id: string; type: string; filter?: unknown; paint?: Record<string, unknown> };
const base = () => protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }) as Layer[];
const shipped = () => withClearRoadLabels(base(), false) as Layer[];
const EARTH = namedFlavor("light").earth;
/** A zoom ramp's [zoom, width] stops. */
const stops = (ramp: unknown) => {
  const flat = (ramp as number[]).slice(3);
  return flat.flatMap((zoom, i) => (i % 2 === 0 ? [[zoom, flat[i + 1]]] : []));
};
/** A ramp's width at `zoom`, linear between its stops as MapLibre draws it. */
const widthAt = (ramp: unknown, zoom: number) => {
  const s = stops(ramp);
  if (zoom <= s[0][0]) return s[0][1];
  for (let i = 1; i < s.length; i++) {
    const [z0, w0] = s[i - 1];
    const [z1, w1] = s[i];
    if (zoom <= z1) return w0 + ((w1 - w0) * (zoom - z0)) / (z1 - z0);
  }
  return s[s.length - 1][1];
};

test("boundaries: the base map's layer becomes its other lines, then county, then state, in its place", () => {
  const ids = shipped().map((l) => l.id);
  const at = base().findIndex((l) => l.id === BOUNDARY_LAYER_ID);
  assert.ok(at > 0, "the base map has a boundaries layer");
  assert.deepEqual(ids.slice(at, at + 3), [BOUNDARY_LAYER_ID, BOUNDARY_LINE.county.id, BOUNDARY_LINE.state.id]);
  assert.equal(ids.length, base().length + 2);
});

test("boundaries: each admin level is drawn by exactly one boundary layer: 4 a state line, 6 a county line", () => {
  const boundaryLayers = shipped().filter((l) => l.id.startsWith("boundaries"));
  const matches = (layer: Layer, level: number) => featureFilter(layer.filter as never, `layers.${layer.id}.filter`).filter({ zoom: 12 } as never, { type: 2, properties: { kind_detail: level } } as never);
  for (let level = 1; level <= 10; level++) {
    const drawnBy = boundaryLayers.filter((l) => matches(l, level)).map((l) => l.id);
    assert.equal(drawnBy.length, 1, `level ${level} is drawn by ${drawnBy.join(", ") || "nothing"}`);
    if (level === 4) assert.deepEqual(drawnBy, [BOUNDARY_LINE.state.id]);
    if (level === 6) assert.deepEqual(drawnBy, [BOUNDARY_LINE.county.id]);
    if (level > 6) assert.deepEqual(drawnBy, [BOUNDARY_LAYER_ID]);
  }
  // The other lines keep the base map's look.
  const original = base().find((l) => l.id === BOUNDARY_LAYER_ID)!;
  assert.deepEqual(boundaryLayers.find((l) => l.id === BOUNDARY_LAYER_ID)!.paint, original.paint);
});

test("boundaries: a state line is darker and wider than a county line, and both stronger than the base map's", () => {
  const { state, county } = BOUNDARY_LINE;
  const original = base().find((l) => l.id === BOUNDARY_LAYER_ID)!;
  assert.ok(contrastRatio(state.color, EARTH) > contrastRatio(county.color, EARTH));
  assert.ok(contrastRatio(county.color, EARTH) > contrastRatio(original.paint!["line-color"] as string, EARTH));
  for (const zoom of [7, 10, 11, 12, 14, 17]) {
    assert.ok(widthAt(state.width, zoom) > widthAt(county.width, zoom), `z${zoom}: state wider than county`);
    assert.ok(widthAt(county.width, zoom) > (original.paint!["line-width"] as number), `z${zoom}: county wider than before`);
  }
  // Subtle: narrower than LTS 1, the thinnest stress line drawn over it, at every zoom it is drawn, thinned at z10-11.
  const lts1 = currentTiers()[0];
  const lts1At = (zoom: number) => (zoom >= 12 ? lts1.width : zoomedOutLine(lts1, zoom < ZOOMED_OUT_NEAR_ZOOM ? 10 : ZOOMED_OUT_NEAR_ZOOM));
  for (const zoom of [10, 10.5, 11, 11.5, 12, 14, 17]) {
    assert.ok(widthAt(state.width, zoom) < lts1At(zoom), `z${zoom}: state line ${widthAt(state.width, zoom)} px under LTS 1's ${lts1At(zoom)} px`);
  }
});

test("boundaries: the shipped style is valid", () => {
  const style = { version: 8, glyphs: "https://example.org/{fontstack}/{range}.pbf", sources: { protomaps: { type: "vector", url: "pmtiles://x" } }, layers: shipped() };
  assert.deepEqual(validateStyleMin(style as never), []);
});
