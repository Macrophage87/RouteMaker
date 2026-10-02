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

test("the agency street layers are credited as their licences ask", () => {
  const credits = MAP_CREDITS.join(" ");
  // DC's Roadway Block, CC BY 4.0: names DDOT and DC GIS, says it is adapted, links the licence.
  assert.match(credits, /Roadway Block, District Department of Transportation \(DDOT\) \/ DC GIS \(Open Data DC\), adapted, <a href="https:\/\/creativecommons\.org\/licenses\/by\/4\.0\/">CC BY 4\.0<\/a>/);
  // The Roadway Block's AADT fills where no count layer reached a street.
  assert.match(credits, /traffic counts in the District: Roadway Block/);
  // Baltimore's, open by city code: the owner's credit line (OWNER-DECISIONS 159).
  assert.match(credits, /City of Baltimore, Open Baltimore/);
});

test("Montgomery County Planning is credited now its LTS 5 roads are loaded as Avoid", () => {
  // OWNER-DECISIONS 181: the credit goes in the same change as the rows. The layer's
  // licence asks for "attribution to the Montgomery County Planning Department".
  const montgomery = MAP_CREDITS.filter((line) => /Montgomery County Planning/.test(line));
  assert.equal(montgomery.length, 1);
  assert.match(montgomery[0], /Bicycle Level of Traffic Stress, Montgomery County Planning Department/);
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
  // SHARED API CONTRACT: served for z 10-16; the map asks for z10-14 and
  // draws z15-16 from the z14 tile (every one of them drawn ahead).
  assert.equal(source.minzoom, 10);
  assert.equal(source.maxzoom, 14);
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
  assert.ok(STRESS_ZOOMS.min < STRESS_ZOOMS.busy && STRESS_ZOOMS.busy < STRESS_ZOOMS.quiet);
  assert.ok(STRESS_ZOOMS.quiet <= STRESS_ZOOMS.max);
});

test("the map asks for no stress tile past z14: z15-16 are drawn from it (owner, 2026-09-28)", () => {
  // Every tile the map asks for is drawn ahead (core/tile_cache.py); a
  // source reaching z16 would ask for 16 times as many, drawn on request.
  assert.equal(stressSource("https://example.test").maxzoom, 14);
  // "Zoom less than 12, show just bike paths and the metro/MARC. 12 and 13,
  // show LTS 3+, 14+ show show the quiet streets." (OWNER-DECISIONS 73)
  assert.equal(STRESS_ZOOMS.busy, 12);
  assert.equal(STRESS_ZOOMS.quiet, 14);
});
