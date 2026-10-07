// The station panel's links (OWNER-DECISIONS 441b-441f), against the stations the map draws.
import { test } from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";
import { MARC_PENN_TIMETABLE, WMATA_STATION_BASE, parseStationSlugs, stationLinks, stationNearSpot } from "./stationLinks.ts";

register(
  "data:text/javascript," +
    encodeURIComponent(`
import { readFileSync } from "node:fs";
export async function load(url, context, next) {
  if (url.endsWith("?raw")) {
    const text = readFileSync(new URL(url.slice(0, -4)), "utf8");
    return { format: "module", source: "export default " + JSON.stringify(text), shortCircuit: true };
  }
  return next(url, context);
}`),
);

const load = () => import("./railData.ts");

test("every Metro station on the map has a checked WMATA slug, and the table has no stray name", async () => {
  const { RAIL_STATIONS, WMATA_SLUGS } = await load();
  const metro = RAIL_STATIONS.filter((s) => s.metro.length > 0).map((s) => s.name);
  assert.equal(metro.length, 98);
  const missing = metro.filter((name) => !(name in WMATA_SLUGS));
  assert.deepEqual(missing, []);
  const stray = Object.keys(WMATA_SLUGS).filter((name) => !metro.includes(name));
  assert.deepEqual(stray, []);
  // One page per station: no two stations share a slug.
  const slugs = Object.values(WMATA_SLUGS);
  assert.equal(new Set(slugs).size, slugs.length);
  for (const slug of slugs) assert.match(slug, /^[a-z0-9'-]+$/, slug);
});

test("the owner's example: Fort Totten's page", async () => {
  const { WMATA_SLUGS } = await load();
  assert.deepEqual(stationLinks({ name: "Fort Totten", metro: ["red", "green", "yellow"], penn: false }, WMATA_SLUGS), [
    { text: "Fort Totten on WMATA's site", href: "https://www.wmata.com/ridertools/station/fort-totten" },
  ]);
  assert.equal(WMATA_STATION_BASE, "https://www.wmata.com/ridertools/station/");
});

test("every MARC Penn station offers the Penn Line timetable; Union Station offers both pages", async () => {
  const { RAIL_STATIONS, WMATA_SLUGS } = await load();
  const penn = RAIL_STATIONS.filter((s) => s.penn);
  assert.equal(penn.length, 9);
  for (const station of penn) {
    const links = stationLinks(station, WMATA_SLUGS);
    assert.ok(links.some((l) => l.href === MARC_PENN_TIMETABLE), station.name);
  }
  const union = RAIL_STATIONS.find((s) => s.name === "Union Station")!;
  assert.deepEqual(
    stationLinks(union, WMATA_SLUGS).map((l) => l.href),
    ["https://www.wmata.com/ridertools/station/union-station", MARC_PENN_TIMETABLE],
  );
  const bwi = RAIL_STATIONS.find((s) => s.name === "BWI Thurgood Marshall Airport")!;
  assert.deepEqual(stationLinks(bwi, WMATA_SLUGS).map((l) => l.href), [MARC_PENN_TIMETABLE]);
  assert.equal(MARC_PENN_TIMETABLE, "https://www.mta.maryland.gov/schedule/timetable/marc-penn");
});

test("a link names its page in words, never a logo or a bare URL", async () => {
  const { WMATA_SLUGS } = await load();
  for (const link of stationLinks({ name: "New Carrollton", metro: ["orange", "silver"], penn: true }, WMATA_SLUGS)) {
    assert.ok(!link.text.startsWith("http"));
    assert.match(link.text, /WMATA|MARC Penn Line/);
  }
});

test("a slug table that does not fit offers no link rather than a guessed one", () => {
  assert.equal(parseStationSlugs("not json"), null);
  assert.equal(parseStationSlugs(JSON.stringify({ slugs: { Pentagon: "../evil" } })), null);
  assert.deepEqual(stationLinks({ name: "Pentagon", metro: ["blue"], penn: false }, {}), []);
});

test("the road panel offers the nearest shown station within a short walk", async () => {
  const { RAIL_STATIONS, WMATA_SLUGS } = await load();
  const totten = RAIL_STATIONS.find((s) => s.name === "Fort Totten")!;
  const near: [number, number] = [totten.point[0] + 0.001, totten.point[1]];
  const both = { metro: true, marc: true };
  assert.equal(stationNearSpot(RAIL_STATIONS, both, near, WMATA_SLUGS)?.station.name, "Fort Totten");
  // Hidden from the map, it is not offered.
  assert.equal(stationNearSpot(RAIL_STATIONS, { metro: false, marc: true }, near, WMATA_SLUGS), null);
  const far: [number, number] = [totten.point[0] + 0.02, totten.point[1] + 0.02];
  assert.equal(stationNearSpot(RAIL_STATIONS, both, far, WMATA_SLUGS)?.station.name ?? null, null);
});
