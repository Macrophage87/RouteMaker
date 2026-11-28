// The beaches and the beach path (lib/beaches.ts): the file read, a route on the tide line found, its note, the layers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { addBeaches, beachAlongRoute, beachNote, BEACH_FILL_LAYER, BEACH_PATH_LAYER, BEACH_SOURCE_ID, loadBeaches, parseBeaches, type BeachMap } from "./beaches.ts";
import { lowTidesOn, nearestStation, readTides } from "./tides.ts";

const LON = -81.85;
const RAW = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", properties: { kind: "beach", name: "Bonita Beach", osm: "w1" }, geometry: { type: "Polygon", coordinates: [[[LON, 26.302], [LON + 0.0006, 26.302], [LON + 0.0006, 26.307], [LON, 26.307], [LON, 26.302]]] } },
    { type: "Feature", properties: { kind: "path", way: 1000 }, geometry: { type: "LineString", coordinates: [[LON, 26.302], [LON, 26.307]] } },
    { type: "Feature", properties: { kind: "path", way: 2 }, geometry: { type: "LineString", coordinates: [[LON, 26.3]] } },
    { type: "Feature", properties: { kind: "other" }, geometry: { type: "Point", coordinates: [LON, 26.3] } },
  ],
};

test("the file is read, and features not drawn right are left out", () => {
  const data = parseBeaches(RAW);
  assert.deepEqual(data?.features.map((f) => f.properties.kind), ["beach", "path"]);
  assert.equal(parseBeaches({}), null);
});

test("a route along the tide line is on the beach path for that stretch only", () => {
  const data = parseBeaches(RAW);
  // In from the street, along the shore from 26.303 to 26.306 (~334 m), and back out.
  const line: [number, number][] = [[LON + 0.003, 26.303], [LON, 26.303], [LON, 26.304], [LON, 26.305], [LON, 26.306], [LON + 0.003, 26.306]];
  const along = beachAlongRoute(line, data);
  assert.ok(along && Math.abs(along.metres - 334) < 5, String(along?.metres));
  assert.deepEqual(along?.at, [LON, 26.303]);
  assert.equal(beachAlongRoute([[LON + 0.01, 26.3], [LON + 0.01, 26.31]], data), null);
  assert.equal(beachAlongRoute(line, null), null);
});

test("the note is one short line: ride it at low tide, at that day's low tides on the page's clock", () => {
  const along = { metres: 1609.344, at: [LON, 26.303] as [number, number] };
  const lows = [
    { at: new Date("2026-12-23T10:34:00Z"), feet: -1.3 },
    { at: new Date("2026-12-23T22:18:00Z"), feet: 1.4 },
  ];
  assert.equal(beachNote(along, lows, "en-US"), "Beach path, 1.0 mi (1.6 km): ride at low tide (5:34 AM, 5:18 PM).");
  assert.match(beachNote(along, lows, "fr-FR"), /\(5:34 et 17:18\)\.$/, "a 24-hour page's clock, in its own words");
  assert.equal(beachNote(along, [], "en-US"), "Beach path, 1.0 mi (1.6 km): ride at low tide. No low tide that day.");
  assert.equal(beachNote(along, null, "en-US"), "Beach path, 1.0 mi (1.6 km): ride at low tide.", "no tide data says only to ride at low tide");
});

test("a ride day outside the tide file reads as no tide data, not as no low tide that day", () => {
  const data = readTides({ from: "2026-12-23", to: "2027-01-23", stations: [{ id: "8725110", name: "Naples", lon: -81.808, lat: 26.132, lows: [] }] })!;
  const along = { metres: 1609.344, at: [LON, 26.303] as [number, number] };
  const note = beachNote(along, lowTidesOn(data, nearestStation(data, along.at), new Date("2027-06-01T15:00:00Z")), "en-US");
  assert.equal(note, "Beach path, 1.0 mi (1.6 km): ride at low tide.");
  assert.doesNotMatch(note, /No low tide/);
});

test("the beaches and the tide line are drawn once, under the route", () => {
  const added: { id: string; beforeId?: string }[] = [];
  const sources = new Set<string>();
  const map: BeachMap = {
    getSource: (id) => (sources.has(id) ? {} : undefined),
    addSource: (id) => void sources.add(id),
    addLayer: (layer, beforeId) => void added.push({ id: (layer as { id: string }).id, beforeId }),
    getLayer: (id) => (id === "route-casing" ? {} : undefined),
  };
  const data = parseBeaches(RAW)!;
  assert.equal(addBeaches(map, data, "route-casing"), true);
  assert.equal(addBeaches(map, data, "route-casing"), false);
  assert.ok(sources.has(BEACH_SOURCE_ID));
  assert.deepEqual(added, [{ id: BEACH_FILL_LAYER, beforeId: "route-casing" }, { id: BEACH_PATH_LAYER, beforeId: "route-casing" }]);
});

test("the file is fetched once", async () => {
  let calls = 0;
  const serving = (async () => {
    calls++;
    return new Response(JSON.stringify(RAW));
  }) as unknown as typeof fetch;
  assert.equal((await loadBeaches("/b.json", serving))?.features.length, 2);
  await loadBeaches("/b.json", serving);
  assert.equal(calls, 1);
});
