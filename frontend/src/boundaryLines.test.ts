// The state and county lines (stressStyle.js, BOUNDARY_LINE; the owner, 2026-10-27: "Add state and county lines to
// the map."): the base map's boundaries layer, as this app ships it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { BOUNDARY_LAYER_ID, BOUNDARY_LINE, contrastRatio, withClearRoadLabels } from "./stressStyle.js";

type Layer = { id: string; type: string; filter?: unknown; paint?: Record<string, unknown> };
const base = () => protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }) as Layer[];
const shipped = () => withClearRoadLabels(base(), false) as Layer[];
const EARTH = namedFlavor("light").earth;
/** A zoom ramp's width at each of its stops. */
const widths = (ramp: unknown) => (ramp as number[]).slice(3).filter((_, i) => i % 2 === 1);

test("boundaries: the base map's layer becomes its other lines, then county, then state, in its place", () => {
  const ids = shipped().map((l) => l.id);
  const at = base().findIndex((l) => l.id === BOUNDARY_LAYER_ID);
  assert.ok(at > 0, "the base map has a boundaries layer");
  assert.deepEqual(ids.slice(at, at + 3), [BOUNDARY_LAYER_ID, BOUNDARY_LINE.county.id, BOUNDARY_LINE.state.id]);
  assert.equal(ids.length, base().length + 2);
});

test("boundaries: state lines are OSM admin level 4 (the District too), county lines level 6, the rest keep the base map's look", () => {
  const layers = shipped();
  const byId = (id: string) => layers.find((l) => l.id === id)!;
  assert.deepEqual(byId(BOUNDARY_LINE.state.id).filter, ["==", ["get", "kind_detail"], 4]);
  assert.deepEqual(byId(BOUNDARY_LINE.county.id).filter, ["==", ["get", "kind_detail"], 6]);
  const others = byId(BOUNDARY_LAYER_ID);
  const original = base().find((l) => l.id === BOUNDARY_LAYER_ID)!;
  assert.deepEqual(others.paint, original.paint);
  assert.deepEqual(others.filter, ["all", [">", ["get", "kind_detail"], 2], ["!=", ["get", "kind_detail"], 4], ["!=", ["get", "kind_detail"], 6]]);
});

test("boundaries: a state line is darker and wider than a county line, and both stronger than the base map's", () => {
  const { state, county } = BOUNDARY_LINE;
  const original = base().find((l) => l.id === BOUNDARY_LAYER_ID)!;
  assert.ok(contrastRatio(state.color, EARTH) > contrastRatio(county.color, EARTH));
  assert.ok(contrastRatio(county.color, EARTH) > contrastRatio(original.paint!["line-color"] as string, EARTH));
  widths(state.width).forEach((w, i) => assert.ok(w > widths(county.width)[i]));
  for (const w of widths(county.width)) assert.ok(w > (original.paint!["line-width"] as number));
  // Subtle: narrower than LTS 1's 2.5 px, the thinnest stress line drawn over it.
  for (const w of widths(state.width)) assert.ok(w < 2.5);
});

test("boundaries: the shipped style is valid", () => {
  const style = { version: 8, glyphs: "https://example.org/{fontstack}/{range}.pbf", sources: { protomaps: { type: "vector", url: "pmtiles://x" } }, layers: shipped() };
  assert.deepEqual(validateStyleMin(style as never), []);
});
