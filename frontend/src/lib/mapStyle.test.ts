import { test } from "node:test";
import assert from "node:assert/strict";
import { MAP_ATTRIBUTION, MAP_CREDITS, RAIL_CREDITS, STRESS_ZOOMS, buildStyle, stressSource, STRESS_SOURCE_ID } from "./mapStyle.ts";
import { STRESS_PROTOCOL, httpUrl } from "./stressProtocol.ts";

const ORIGIN = "https://routes.example.org";

test("every map carries both base map credits and the volume sources' credits", () => {
  const all = MAP_CREDITS.join(" ");
  assert.match(all, /OpenStreetMap contributors/);
  assert.match(all, /ODbL/);
  assert.match(all, /Protomaps/);
  assert.match(all, /District Department of Transportation|DDOT/);
  assert.match(all, /CC BY 4\.0/);
  assert.match(all, /Virginia Department of Transportation|VDOT/);
  assert.match(all, /Architect of the Capitol boundary, District of Columbia \(Open Data DC\)/);
});

test("the base map source states its own credit, not the archive's half of it", () => {
  // The archive's embedded attribution names OpenStreetMap only.
  const style = buildStyle(ORIGIN, []);
  const source = style.sources.protomaps as { attribution?: string };
  assert.match(source.attribution ?? "", /OpenStreetMap/);
  assert.match(source.attribution ?? "", /Protomaps/);
});

test("everything the style loads comes from this site", () => {
  const style = buildStyle(ORIGIN, []);
  const urls = [style.glyphs, style.sprite, (style.sources.protomaps as { url: string }).url];
  for (const url of urls) {
    assert.ok(
      url.startsWith(`${ORIGIN}/basemap/`) || url.startsWith("pmtiles:///basemap/"),
      url,
    );
  }
  assert.ok(style.glyphs.includes("{fontstack}") && style.glyphs.includes("{range}"));
  assert.match(String(style.sprite), /\/sprites\/v4\/light$/);
});

test("the stress tiles are the contract's path, absolute, within its zooms", () => {
  const source = stressSource(ORIGIN);
  assert.deepEqual(source.tiles.map(httpUrl), [`${ORIGIN}/tiles/stress/{z}/{x}/{y}.pbf`]);
  assert.ok(source.tiles.every((url) => url.startsWith(`${STRESS_PROTOCOL}://`)));
  // SHARED API CONTRACT: served for z 10-16.
  assert.equal(source.minzoom, 10);
  assert.equal(source.maxzoom, 16);
  assert.equal(STRESS_SOURCE_ID.length > 0, true);
});

test("the base map layers are passed through untouched", () => {
  const layers = [{ id: "background", type: "background" }] as never[];
  assert.deepEqual(buildStyle(ORIGIN, layers).layers, layers);
});

test("the credits read as one line with OpenStreetMap first", () => {
  // MapLibre orders separate attribution entries by length, which put VDOT
  // first; one combined entry keeps the order written here.
  const order = [
    "OpenStreetMap",
    "Protomaps",
    "District Department of Transportation",
    "Virginia Department of Transportation",
  ];
  const at = order.map((name) => MAP_ATTRIBUTION.indexOf(name));
  assert.ok(at.every((i) => i >= 0), JSON.stringify(at));
  assert.deepEqual([...at].sort((x, y) => x - y), at);
  assert.ok(MAP_ATTRIBUTION.includes(MAP_CREDITS[0]), "the base map's own credit is a part of it");
});

test("the licence notices are linked from the credits", () => {
  assert.match(MAP_ATTRIBUTION, /href="\/licenses\.txt"/);
});

test("the rail stations' source is credited on every map, after the base map's", () => {
  const all = MAP_CREDITS.join(" ");
  assert.match(all, /Open Data DC/);
  const at = MAP_ATTRIBUTION.indexOf("Open Data DC");
  assert.ok(at > MAP_ATTRIBUTION.indexOf("OpenStreetMap"));
  assert.match(MAP_ATTRIBUTION.slice(at), /CC BY 4\.0/);
});

test("the rail credit links the CC BY 4.0 licence itself", () => {
  assert.match(RAIL_CREDITS.join(" "), /href="https:\/\/creativecommons\.org\/licenses\/by\/4\.0\/"/);
});

test("the stress source starts and ends where the zoom levels say", () => {
  const source = stressSource("https://example.test");
  assert.equal(source.minzoom, STRESS_ZOOMS.min);
  assert.equal(source.maxzoom, STRESS_ZOOMS.max);
  assert.ok(STRESS_ZOOMS.min < STRESS_ZOOMS.streets && STRESS_ZOOMS.streets < STRESS_ZOOMS.full);
  assert.ok(STRESS_ZOOMS.full <= STRESS_ZOOMS.max);
});
