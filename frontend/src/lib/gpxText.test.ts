import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { ImportedPlan } from "./gpxPlan.ts";
import { FIDELITY_WARN_BELOW, exportFileName, exportName, exportOf, fidelityNotice, importSentences } from "./gpxText.ts";

const numbers = (text: string) => text.match(/\d+(?:\.\d+)?/g) ?? [];

const ROUTE = {
  preset: "group-ride" as const,
  distance_m: 12_345,
  climb_m: 81,
  descent_m: 79,
  geometry: {
    type: "LineString" as const,
    coordinates: [
      [-77.04, 38.9],
      [-77.0, 38.91],
    ] as LonLat[],
  },
  attribution: ["© OpenStreetMap contributors, ODbL", "Elevation: USGS 3D Elevation Program"],
};

test("the export is named for its ride type and distance, and the file name is safe", () => {
  assert.match(exportName(ROUTE), /Group Ride/);
  assert.deepEqual(numbers(exportName(ROUTE)), ["12.3"]);
  const fileName = exportFileName(ROUTE);
  assert.match(fileName, /^[a-z0-9_-]+\.gpx$/);
  assert.ok(fileName.includes("group-ride") && fileName.includes("12_3"), fileName);
});

test("the export carries the route's own line, points, ride type and attribution", () => {
  const points: LonLat[] = [
    [-77.04, 38.9],
    [-77.0, 38.91],
  ];
  const out = exportOf(ROUTE, points);
  assert.equal(out.geometry, ROUTE.geometry.coordinates);
  assert.equal(out.planPoints, points);
  assert.equal(out.preset, "group-ride");
  assert.deepEqual(out.attribution, ROUTE.attribution);
  assert.ok(out.description.includes("Group Ride") && out.description.includes("12.3"), out.description);
});

test("the fidelity notice warns exactly when either share is under the threshold", () => {
  const ok = fidelityNotice({ trackCovered: 0.97, routeOnTrack: 0.95, lengthRatio: 1 });
  assert.equal(ok.warn, false);
  assert.deepEqual(numbers(ok.text), ["97", "30"]);
  const edge = fidelityNotice({ trackCovered: FIDELITY_WARN_BELOW, routeOnTrack: FIDELITY_WARN_BELOW, lengthRatio: 1 });
  assert.equal(edge.warn, false);
  const low = fidelityNotice({ trackCovered: 0.7, routeOnTrack: 0.95, lengthRatio: 1 });
  assert.equal(low.warn, true);
  assert.equal(numbers(low.text)[0], "70");
  const spur = fidelityNotice({ trackCovered: 0.99, routeOnTrack: 0.8, lengthRatio: 1.3 });
  assert.equal(spur.warn, true);
  // 99% followed, 20% of the route off it.
  assert.deepEqual(numbers(spur.text).slice(0, 3), ["99", "30", "20"]);
});

test("a share short of whole is never said as 100%, nor a sliver as 0%", () => {
  assert.equal(numbers(fidelityNotice({ trackCovered: 0.998, routeOnTrack: 1, lengthRatio: 1 }).text)[0], "99");
  assert.equal(numbers(fidelityNotice({ trackCovered: 1, routeOnTrack: 1, lengthRatio: 1 }).text)[0], "100");
  assert.equal(numbers(fidelityNotice({ trackCovered: 0.001, routeOnTrack: 1, lengthRatio: 1 }).text)[0], "1");
});

const PLAN: ImportedPlan = {
  points: Array.from({ length: 25 }, (_, i) => [-77 + i * 0.001, 38.9] as LonLat),
  preset: null,
  source: "track",
  reference: [
    [-77, 38.9],
    [-76.9, 38.9],
  ],
  referenceM: 42_400,
  name: "Sunday loop",
  notes: [
    { kind: "outside", share: 0.12 },
    { kind: "joined", parts: 3 },
    { kind: "waypoints-unused", count: 4 },
  ],
};

test("an opened file is described: its name, its length, then one sentence per note", () => {
  const sentences = importSentences(PLAN);
  assert.equal(sentences.length, 1 + PLAN.notes.length);
  assert.ok(sentences[0].includes("Sunday loop"));
  assert.deepEqual(numbers(sentences[0]), ["42.4"]);
  assert.deepEqual(numbers(sentences[1]), ["12"]);
  assert.deepEqual(numbers(sentences[2]), ["3"]);
  assert.deepEqual(numbers(sentences[3]), ["4"]);
  const route = importSentences({ ...PLAN, source: "route", preset: "mass-ride", points: PLAN.points.slice(0, 5), notes: [] });
  assert.equal(route.length, 1);
  assert.ok(route[0].includes("Mass Ride"));
  assert.deepEqual(numbers(route[0]), ["5"]);
  const unnamed = importSentences({ ...PLAN, name: undefined, notes: [] });
  assert.equal(unnamed.length, 1);
  assert.doesNotMatch(unnamed[0], /undefined/);
});
