import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  DC_BOUNDARY,
  DC_BOUNDARY_CREDIT,
  DC_MASK_LAYERS,
  DC_MASK_LAYER_IDS,
  DC_MASK_SOURCE_ID,
  MASS_DC_ONLY,
  MASS_OUTSIDE_DC_NOTICE,
  addDcMask,
  dcMask,
  inDc,
  leavesDc,
  outsideDcNote,
  setDcMaskVisibility,
} from "./dcBoundary.ts";
import { MassLegend } from "./massLegend.ts";
import { announceRoute } from "./summary.ts";
import type { LonLat } from "./geo.ts";
import type { RouteResponse } from "./api.ts";

const WHITE_HOUSE: LonLat = [-77.0365, 38.8977];
const CAPITOL: LonLat = [-77.009, 38.8899];
const ROSSLYN: LonLat = [-77.072, 38.896]; // Virginia
const BETHESDA: LonLat = [-77.0947, 38.9807]; // Maryland
const SILVER_SPRING: LonLat = [-77.0261, 38.9907]; // Maryland, just over the line

test("the boundary is OpenStreetMap's District of Columbia, credited", () => {
  assert.equal(DC_BOUNDARY.properties.name, "District of Columbia");
  assert.match(DC_BOUNDARY.properties.source, /ISO3166-2=US-DC/);
  assert.equal(DC_BOUNDARY.properties.credit, "© OpenStreetMap contributors (ODbL)");
  assert.match(DC_BOUNDARY_CREDIT, /© OpenStreetMap contributors \(ODbL\)/);
  // tests/test_mass_tiles.py holds this file to the tiles' clip (src/core/geodata), byte for byte.
  const front = JSON.parse(readFileSync(new URL("../massride-data/dc-boundary.json", import.meta.url), "utf8"));
  assert.deepEqual(front, DC_BOUNDARY);
});

test("inside and outside the District", () => {
  assert.equal(inDc(WHITE_HOUSE), true);
  assert.equal(inDc(CAPITOL), true);
  assert.equal(inDc(ROSSLYN), false);
  assert.equal(inDc(BETHESDA), false);
  assert.equal(inDc(SILVER_SPRING), false);
});

test("a line leaves the District when any vertex, or any stretch's middle, is outside", () => {
  assert.equal(leavesDc([WHITE_HOUSE, CAPITOL]), false);
  assert.equal(leavesDc([WHITE_HOUSE, ROSSLYN]), true);
  assert.equal(leavesDc([ROSSLYN, WHITE_HOUSE, CAPITOL]), true);
  assert.equal(leavesDc([]), false);
  // Both ends in DC (Georgetown, then the Southwest Waterfront), the straight stretch between them across Virginia.
  assert.equal(inDc([-77.07, 38.904]) && inDc([-77.02, 38.874]), true);
  assert.equal(leavesDc([[-77.065, 38.9], [-77.06, 38.86], [-77.02, 38.874]]), true);
});

const route = (preset: string, coordinates: LonLat[]) =>
  ({ preset, geometry: { type: "LineString", coordinates } }) as unknown as RouteResponse;

test("the notice is a Mass Ride's, and only when its route leaves the District (418a)", () => {
  assert.equal(outsideDcNote(route("mass-ride", [WHITE_HOUSE, ROSSLYN])), MASS_OUTSIDE_DC_NOTICE);
  assert.equal(outsideDcNote(route("mass-ride", [WHITE_HOUSE, CAPITOL])), null);
  assert.equal(outsideDcNote(route("commuter", [WHITE_HOUSE, ROSSLYN])), null, "other ride types are unchanged");
  assert.equal(outsideDcNote(null), null);
  assert.equal(MASS_OUTSIDE_DC_NOTICE, "Part of this route is outside the area Mass Ride planning covers (DC only for now).");
});

test("the route's sentence says it, so the route's live region announces it", () => {
  const body = {
    ...route("mass-ride", [WHITE_HOUSE, ROSSLYN]),
    distance_m: 5000,
    duration_s: 1200,
    climb_m: 10,
    descent_m: 10,
  } as RouteResponse;
  assert.match(announceRoute(body), /Part of this route is outside the area Mass Ride planning covers \(DC only for now\)\./);
  assert.doesNotMatch(announceRoute({ ...body, preset: "commuter" } as RouteResponse), /outside the area Mass Ride/);
});

test("the legend says DC only in words, with the boundary's source", () => {
  const html = renderToStaticMarkup(createElement(MassLegend));
  assert.ok(html.includes(MASS_DC_ONLY));
  assert.match(MASS_DC_ONLY, /covers DC only for now/);
  assert.ok(html.includes("District of Columbia boundary: © OpenStreetMap contributors (ODbL)."));
  assert.match(html, /6-8 mph/, "the legend keeps 6-8 mph (404)");
});

test("the mask is the world with the District as its hole, and a dashed edge so shading is not the only cue", () => {
  const mask = dcMask();
  const [hole] = mask.features;
  assert.equal(hole.geometry.type, "Polygon");
  assert.equal((hole.geometry.coordinates as number[][][]).length, 1 + DC_BOUNDARY.geometry.coordinates.length);
  const edge = DC_MASK_LAYERS.find((l) => l.id === "massride-dc-edge")!;
  assert.ok("line-dasharray" in edge.paint);
  for (const layer of DC_MASK_LAYERS) assert.equal(layer.source, DC_MASK_SOURCE_ID);
});

function maskMap() {
  const sources = new Map<string, unknown>();
  const added: Array<{ layer: { id: string; layout?: { visibility?: string } }; before?: string }> = [];
  const layout: Record<string, string> = {};
  const map = {
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, source: object) => sources.set(id, source),
    getStyle: () => ({
      layers: [
        { id: "roads", type: "line" },
        { id: "stress-1", type: "line" },
        { id: "labels", type: "symbol" },
      ],
    }),
    addLayer: (layer: object, before?: string) => added.push({ layer: layer as (typeof added)[number]["layer"], before }),
    getLayer: (id: string) => added.find((a) => a.layer.id === id)?.layer,
    setLayoutProperty: (id: string, _name: string, value: string) => {
      layout[id] = value;
    },
  };
  return { map, added, layout };
}

test("the mask goes over the base map, under the overlays and labels, once, shown only in Mass Ride mode", () => {
  const { map, added, layout } = maskMap();
  assert.equal(addDcMask(map, false, new Set(["stress-1"])), true);
  assert.equal(addDcMask(map, true, new Set(["stress-1"])), false);
  assert.deepEqual(
    added.map((a) => a.layer.id),
    DC_MASK_LAYER_IDS,
  );
  for (const a of added) {
    assert.equal(a.before, "stress-1");
    assert.equal(a.layer.layout?.visibility, "none");
  }
  setDcMaskVisibility(map, true);
  for (const id of DC_MASK_LAYER_IDS) assert.equal(layout[id], "visible");
});
