import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { ImportedPlan } from "./gpxPlan.ts";
import {
  FIDELITY_WARN_BELOW,
  exportFileName,
  exportName,
  exportOf,
  fidelityNotice,
  importSentences,
  presetNotice,
  rideText,
} from "./gpxText.ts";

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
  // US units first, metric in brackets.
  assert.equal(exportName(ROUTE), "Group Ride route, 7.7 mi (12.3 km)");
  assert.equal(exportName({ preset: "group-ride", distance_m: 7_600 }), "Group Ride route, 4.7 mi (7.6 km)");
  const fileName = exportFileName(ROUTE);
  assert.match(fileName, /^[a-z0-9_-]+\.gpx$/);
  assert.equal(fileName, "routemaker-group-ride-7_7mi.gpx");
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
  assert.equal(out.description, "Group Ride. 7.7 mi (12.3 km), climb 266 ft (81 m), descent 259 ft (79 m). Planned with RouteMaker.");
  // No dials in the answer: none in the file, and the ride type still said.
  assert.equal(out.dials, undefined);
  assert.equal(out.rideText, "Ride type: Group Ride.");
});

test("the export carries the sliders the route was planned with, and says them", () => {
  const dials = { stress: 50, hills: -50, when: "weekend" as const, carrying: null };
  const out = exportOf({ ...ROUTE, dials }, []);
  assert.deepEqual(out.dials, { stress: 50, hills: -50, when: "weekend", carrying: null, assist: false });
  assert.equal(
    rideText({ preset: "group-ride", dials }),
    "Ride type: Group Ride. Traffic slider 50 of 100 (Balanced); hills slider -50 (Gentler grades); ride time weekend.",
  );
  assert.match(
    rideText({ preset: "cargo", dials: { stress: 100, hills: -60, when: "weekday_rush", carrying: "people", assist: true } }),
    /; cargo with passengers; electric assist\.$/,
  );
});

test("the fidelity notice warns exactly when either share is under the threshold", () => {
  const ok = fidelityNotice({ trackCovered: 0.97, routeOnTrack: 0.95, lengthRatio: 1 });
  assert.equal(ok.warn, false);
  // 30 m is 98 ft: US first, metric in brackets.
  assert.deepEqual(numbers(ok.text), ["97", "98", "30"]);
  const edge = fidelityNotice({ trackCovered: FIDELITY_WARN_BELOW, routeOnTrack: FIDELITY_WARN_BELOW, lengthRatio: 1 });
  assert.equal(edge.warn, false);
  const low = fidelityNotice({ trackCovered: 0.7, routeOnTrack: 0.95, lengthRatio: 1 });
  assert.equal(low.warn, true);
  assert.equal(numbers(low.text)[0], "70");
  const spur = fidelityNotice({ trackCovered: 0.99, routeOnTrack: 0.8, lengthRatio: 1.3 });
  assert.equal(spur.warn, true);
  // 99% followed, 20% of the route off it.
  assert.deepEqual(numbers(spur.text).slice(0, 4), ["99", "98", "30", "20"]);
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
  // 42.4 km is 26.3 mi.
  assert.deepEqual(numbers(sentences[0]), ["26.3", "42.4"]);
  assert.deepEqual(numbers(sentences[1]), ["12"]);
  assert.deepEqual(numbers(sentences[2]), ["3"]);
  assert.deepEqual(numbers(sentences[3]), ["4"]);
  const route = importSentences({ ...PLAN, source: "route", preset: "mass-ride", points: PLAN.points.slice(0, 5), notes: [] });
  assert.equal(route.length, 1);
  assert.ok(route[0].includes("Mass Ride"));
  assert.deepEqual(numbers(route[0]), ["5"]);
  const gone = { ...PLAN, source: "route" as const, preset: "default" as const, notes: [{ kind: "preset-gone" as const, id: "rocket" }] };
  // The ride type no longer offered is the notice, not one of the sentences.
  assert.equal(importSentences(gone).length, 1);
  assert.match(presetNotice(gone) ?? "", /"rocket".*no longer offers.*opened as Default/);
  assert.equal(presetNotice(PLAN), null);
  const unnamed = importSentences({ ...PLAN, name: undefined, notes: [] });
  assert.equal(unnamed.length, 1);
  assert.doesNotMatch(unnamed[0], /undefined/);
});
