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
  DC_EDGE_TOLERANCE_M,
  MASS_OUTSIDE_DC_NOTICE,
  addDcMask,
  dcMask,
  inDc,
  leavesDc,
  metresToDcEdge,
  nearDc,
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
  assert.match(html, /6 to 8 mph/, "the legend keeps 6 to 8 mph (404), in words a screen reader says as a range");
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

// --- Border roads (OWNER-DECISIONS 420) ---------------------------------------------------------

// Real stretches from the 2026-10-03 build (live.segment, read-only), as tests/test_mass_tiles.py's:
// Western Ave lies just inside the simplified boundary; Eastern and Southern Ave have vertices 9.4 m
// and 19.5 m outside it, the farthest of each road.
const WESTERN_AVE: LonLat[] = [
  [-77.084214, 38.961965], [-77.083929, 38.962188], [-77.083631, 38.96242],
  [-77.082658, 38.963182], [-77.082163, 38.963568], [-77.080491, 38.964888], [-77.080377, 38.964977],
];
const EASTERN_AVE: LonLat[] = [
  [-77.007528, 38.969892], [-77.008622, 38.970748], [-77.008838, 38.970918], [-77.010836, 38.972481],
];
const SOUTHERN_AVE: LonLat[] = [
  [-76.94002, 38.868768], [-76.939425, 38.86923], [-76.938852, 38.86968],
  [-76.938585, 38.869881], [-76.938382, 38.870041], [-76.938249, 38.870143],
];

test("the border tolerance is the simplification's error and half a road (420)", () => {
  assert.equal(DC_EDGE_TOLERANCE_M, 22);
  assert.ok(metresToDcEdge(WHITE_HOUSE) > 2000);
  const outside = (line: LonLat[]) => Math.max(...line.map((p) => (inDc(p) ? 0 : metresToDcEdge(p))));
  assert.equal(outside(WESTERN_AVE), 0);
  assert.ok(outside(EASTERN_AVE) > 5 && outside(EASTERN_AVE) < DC_EDGE_TOLERANCE_M, String(outside(EASTERN_AVE)));
  assert.ok(outside(SOUTHERN_AVE) > 15 && outside(SOUTHERN_AVE) < DC_EDGE_TOLERANCE_M, String(outside(SOUTHERN_AVE)));
});

for (const [name, road] of [["Western Ave", WESTERN_AVE], ["Eastern Ave", EASTERN_AVE], ["Southern Ave", SOUTHERN_AVE]] as const) {
  test(`a Mass Ride along ${name} counts as inside DC: no notice (420)`, () => {
    // Into DC, along the border road and back: the whole route.
    assert.equal(leavesDc(road), false);
    assert.ok(road.every((p) => nearDc(p)));
    const route = { preset: "mass-ride", geometry: { type: "LineString", coordinates: [WHITE_HOUSE, ...road, WHITE_HOUSE] } } as unknown as RouteResponse;
    assert.equal(outsideDcNote(route), null);
  });
}

test("a route clearly outside DC still gets the notice: 60 m over the line, and into Maryland", () => {
  // Straight out from Western Ave's edge, past the tolerance.
  const [lon, lat] = WESTERN_AVE[3];
  const out: LonLat = [lon - 0.0006, lat + 0.0006]; // north-west, into Maryland
  assert.ok(!inDc(out) && metresToDcEdge(out) > 40, String(metresToDcEdge(out)));
  assert.equal(leavesDc([WESTERN_AVE[3], out]), true);
  assert.equal(nearDc(BETHESDA), false);
  const route = { preset: "mass-ride", geometry: { type: "LineString", coordinates: [WHITE_HOUSE, BETHESDA] } } as unknown as RouteResponse;
  assert.equal(outsideDcNote(route), MASS_OUTSIDE_DC_NOTICE);
});
