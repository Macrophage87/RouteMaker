// What MapView does to the map, run against a stand-in map that records calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COVERAGE_MASK_LAYERS,
  COVERAGE_SOURCE_ID,
  addCoverageMask,
  addStressOverlay,
  coverageMask,
  fetchCoverage,
  markerDeps,
  setStressVisibility,
  facilitiesOnMap,
  watchForFacilities,
  watchZoom,
  type Coverage,
  type FacilityMap,
  type OverlayMap,
} from "./mapGlue.ts";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";
import { stressOverlayLayers } from "../stressStyle.js";

function fakeMap(styleLayers: Array<{ id: string; type: string }>) {
  const sources = new Map<string, unknown>();
  const added: Array<{ layer: { id: string; layout?: { visibility?: string } }; before: string | undefined }> = [];
  const layout: Array<[string, string, string]> = [];
  const map: OverlayMap = {
    getSource: (id) => sources.get(id),
    addSource: (id, source) => {
      sources.set(id, source);
    },
    getStyle: () => ({ layers: styleLayers }),
    addLayer: (layer, before) => {
      added.push({ layer: layer as (typeof added)[number]["layer"], before });
    },
    getLayer: (id) => added.find((a) => a.layer.id === id)?.layer,
    setLayoutProperty: (id, name, value) => {
      layout.push([id, name, value]);
    },
  };
  return { map, sources, added, layout };
}

const BASE = [
  { id: "water", type: "fill" },
  { id: "roads", type: "line" },
  { id: "road-labels", type: "symbol" },
  { id: "places", type: "symbol" },
];

test("the overlay is added exactly as stressOverlayLayers lists it, in its order", () => {
  const { map, added } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  const expected = stressOverlayLayers(STRESS_SOURCE_ID);
  assert.deepEqual(
    added.map((a) => a.layer.id),
    expected.map((l: { id: string }) => l.id),
  );
  for (const [i, layer] of expected.entries()) {
    const { layout, ...rest } = added[i].layer as Record<string, unknown>;
    assert.deepEqual(rest, layer, layer.id);
    assert.ok(layout);
  }
});

test("the overlay goes under the first label layer, all of it", () => {
  const { map, added } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  assert.ok(added.length > 0);
  for (const a of added) assert.equal(a.before, "road-labels");
});

test("the overlay is added with the toggle's visibility", () => {
  for (const [visible, visibility] of [
    [true, "visible"],
    [false, "none"],
  ] as const) {
    const { map, added } = fakeMap(BASE);
    addStressOverlay(map, "https://example.test", visible);
    for (const a of added) assert.equal(a.layer.layout?.visibility, visibility);
  }
});

test("the overlay reads the stress source, and is added once", () => {
  const { map, sources, added } = fakeMap(BASE);
  assert.equal(addStressOverlay(map, "https://example.test", true), true);
  assert.deepEqual(sources.get(STRESS_SOURCE_ID), stressSource("https://example.test"));
  const count = added.length;
  assert.equal(addStressOverlay(map, "https://example.test", true), false);
  assert.equal(added.length, count);
});

test("the toggle sets every overlay layer that is on the map", () => {
  const { map, layout } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  for (const [visible, visibility] of [
    [false, "none"],
    [true, "visible"],
  ] as const) {
    layout.length = 0;
    setStressVisibility(map, visible);
    assert.deepEqual(
      layout,
      stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => [l.id, "visibility", visibility]),
    );
  }
  const empty = fakeMap(BASE);
  setStressVisibility(empty.map, true);
  assert.equal(empty.layout.length, 0, "a layer not on the map was set");
});

test("the markers are placed again when markerReset changes, even with the same points", () => {
  // React re-runs an effect when any dependency is not Object.is the last.
  const changed = (a: readonly unknown[], b: readonly unknown[]) =>
    a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
  const points: Array<[number, number]> = [
    [-77, 38.9],
    [-76.9, 38.95],
  ];
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 0)), false);
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 1)), true, "a put-back leaves the markers");
  assert.equal(changed(markerDeps(points, 0), markerDeps([...points], 0)), true, "new points leave the markers");
});

// The coverage mask (owner request of 2026-09-27, "grey out all the parts of
// the map that don't have support").
const COVERAGE: Coverage = {
  type: "Feature",
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-78, 38.2],
        [-76.02, 38.2],
        [-76.02, 39.72],
        [-78, 39.72],
        [-78, 38.2],
      ],
    ],
  },
  properties: {},
};

function signedArea(ring: number[][]): number {
  let sum = 0;
  for (let i = 0; i + 1 < ring.length; i += 1) sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  return sum / 2;
}

test("the mask is the world with exactly the coverage cut out, and the edge is the coverage ring", () => {
  const mask = coverageMask(COVERAGE);
  const [fill, edge] = mask.features;
  const [outer, hole] = fill.geometry.coordinates;
  assert.equal(fill.geometry.coordinates.length, 2, "one outer ring, one hole");
  const lons = outer.map((p) => p[0]);
  const lats = outer.map((p) => p[1]);
  assert.deepEqual([Math.min(...lons), Math.max(...lons)], [-180, 180]);
  assert.ok(Math.min(...lats) <= -85 && Math.max(...lats) >= 85);
  const ring = COVERAGE.geometry.coordinates[0];
  assert.deepEqual([...hole].reverse(), ring, "the hole is the coverage ring");
  assert.ok(Math.sign(signedArea(outer)) !== Math.sign(signedArea(hole)), "a hole winds against its ring");
  assert.deepEqual(edge.geometry.coordinates, ring);
  assert.deepEqual(
    COVERAGE_MASK_LAYERS.map((l) => [l.filter[2], mask.features.filter((f) => f.properties.part === l.filter[2]).length]),
    [
      ["mask", 1],
      ["edge", 1],
    ],
  );
});

test("the mask goes over the base map and under its labels, fill before edge, once", () => {
  const { map, added, sources } = fakeMap(BASE);
  assert.equal(addCoverageMask(map, COVERAGE), true);
  assert.deepEqual(
    added.map((a) => [a.layer.id, a.before]),
    COVERAGE_MASK_LAYERS.map((l) => [l.id, "road-labels"]),
  );
  assert.ok(sources.get(COVERAGE_SOURCE_ID));
  assert.equal(addCoverageMask(map, COVERAGE), false);
  assert.equal(added.length, COVERAGE_MASK_LAYERS.length);
});

test("the mask goes under the stress overlay when the overlay reached the map first", () => {
  const overlay = stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string; type: string }) => ({
    id: l.id,
    type: l.type,
  }));
  const { map, added } = fakeMap([BASE[0], BASE[1], ...overlay, BASE[2], BASE[3]]);
  addCoverageMask(map, COVERAGE);
  for (const a of added) assert.equal(a.before, overlay[0].id);
});

test("the coverage is read from the API, and anything else is no mask", async () => {
  const answer = (status: number, body: unknown) => async () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  let asked = "";
  const good = await fetchCoverage("https://example.test", (async (url: string) => {
    asked = url;
    return answer(200, COVERAGE)();
  }) as typeof fetch);
  assert.equal(asked, "https://example.test/api/coverage");
  assert.deepEqual(good, COVERAGE);
  assert.equal(await fetchCoverage("o", answer(429, { error: "slow down" }) as typeof fetch), null);
  assert.equal(await fetchCoverage("o", answer(200, { type: "Feature", geometry: { type: "Point" } }) as typeof fetch), null);
  assert.equal(
    await fetchCoverage("o", (async () => {
      throw new Error("offline");
    }) as typeof fetch),
    null,
  );
});

type Feature = { properties?: Record<string, unknown> | null };

function facilityMap(withSource: boolean, featuresByCall: Feature[][]) {
  const listeners = new Set<() => void>();
  const queries: Array<{ id: string; options: unknown }> = [];
  const map: FacilityMap = {
    getSource: (id) => (withSource && id === STRESS_SOURCE_ID ? {} : undefined),
    querySourceFeatures: (id, options) => {
      queries.push({ id, options });
      return featuresByCall.shift() ?? [];
    },
    on: (_event, listener) => listeners.add(listener),
    off: (_event, listener) => listeners.delete(listener),
  };
  return { map, listeners, queries };
}

const kind = (facility: unknown): Feature => ({ properties: { facility } });

test("the facility legend lists the kinds the map has drawn, as it draws them, and stops once it has all", () => {
  const { map, listeners, queries } = facilityMap(true, [
    [],
    [kind("path"), kind("none"), kind("path")],
    [kind("path")],
    [kind("lane"), kind("protected")],
  ]);
  const reports: string[][] = [];
  watchForFacilities(map, (kinds) => reports.push([...kinds].sort()));
  const settle = () => [...listeners][0]();
  settle();
  assert.deepEqual(reports, [], "no facility data yet");
  settle();
  assert.deepEqual(reports, [["path"]], "'none' is not a kind the legend shows");
  settle();
  assert.equal(reports.length, 1, "nothing new, nothing reported");
  assert.equal(listeners.size, 1);
  settle();
  assert.deepEqual(reports.at(-1), ["lane", "path", "protected"]);
  assert.equal(listeners.size, 0, "every kind seen: the watch ends");
  assert.deepEqual(queries[0], {
    id: STRESS_SOURCE_ID,
    options: { sourceLayer: "stress", filter: ["has", "facility"] },
  });
});

test("before the stress overlay exists there is nothing to ask", () => {
  const { map, queries } = facilityMap(false, [[kind("path")]]);
  assert.equal(facilitiesOnMap(map).size, 0);
  assert.equal(queries.length, 0);
});

test("the zoom is reported at once and after every zoom", () => {
  let z = 8.4;
  const listeners: Array<() => void> = [];
  const seen: number[] = [];
  watchZoom({ getZoom: () => z, on: (_event, listener) => listeners.push(listener) }, (value) => seen.push(value));
  assert.deepEqual(seen, [8.4]);
  z = 11.2;
  for (const listener of listeners) listener();
  assert.deepEqual(seen, [8.4, 11.2]);
});
