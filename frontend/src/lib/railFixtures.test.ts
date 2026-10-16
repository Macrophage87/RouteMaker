// The fixtures to stations, and what a fixture that no longer fits costs:
// the build (railFixturesPlugin.mjs) and, in a browser, only the rail layer.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { RAIL_FIXTURE_FILES, loadRailStations, stationsFromTexts, type RailTexts } from "./railFixtures.ts";
import { checkRailFixtures, railFixtures } from "./railFixturesPlugin.mjs";

const DATA = new URL("../rail-data/", import.meta.url);
const texts = Object.fromEntries(
  Object.entries(RAIL_FIXTURE_FILES).map(([key, file]) => [key, readFileSync(new URL(file, DATA), "utf8")]),
) as RailTexts;

/** The committed fixtures with Cheverly's LINE already carrying Silver: the correction is stale. */
function stale(): RailTexts {
  const metro = JSON.parse(texts.metroStations);
  const cheverly = metro.features.find((f: { properties: { NAME: string } }) => f.properties.NAME === "Cheverly");
  cheverly.properties.LINE = "orange, silver";
  return { ...texts, metroStations: JSON.stringify(metro) };
}

test("the fixtures make every station, corrections and OSM's elevators applied", () => {
  const stations = stationsFromTexts(texts);
  assert.equal(stations.filter((s) => s.metro.length > 0).length, 98);
  assert.ok(stations.find((s) => s.name === "Cheverly")!.metro.includes("silver"));
  assert.ok(stations.some((s) => s.osmElevators.length > 0 && s.metro.length > 0 && s.name !== "Union Station"));
});

test("in the app, a stale correction leaves the rail stations off with a warning, not the planner", () => {
  const warnings: string[] = [];
  assert.deepEqual(loadRailStations(stale(), (m) => warnings.push(m)), []);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /Cheverly/);
  assert.ok(loadRailStations(texts, (m) => warnings.push(m)).length > 100);
  assert.equal(warnings.length, 1, "no warning for fixtures that fit");
});

test("the build stops on a stale correction, and passes the committed fixtures", () => {
  const dir = mkdtempSync(join(tmpdir(), "rail-fixtures-"));
  try {
    cpSync(DATA, dir, { recursive: true });
    assert.ok(checkRailFixtures(dir).length > 100);
    const plugin = railFixtures(dir);
    const context = { error: (m: string) => { throw new Error(m); } };
    plugin.buildStart.call(context);
    writeFileSync(join(dir, RAIL_FIXTURE_FILES.metroStations), stale().metroStations);
    assert.throws(() => checkRailFixtures(dir), /Cheverly/);
    assert.throws(() => plugin.buildStart.call(context), /Cheverly/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the bundle gets slimmed GeoJSON fixtures that make the same stations (review fe-perf-7)", () => {
  const plugin = railFixtures(fileURLToPath(DATA));
  const bundled = (file: string) => {
    const code = plugin.load(`${fileURLToPath(DATA)}${file}?raw`) as string;
    return JSON.parse(code.replace(/^export default /, "").replace(/;$/, "")) as string;
  };
  const slim = { ...texts, metroStations: bundled("metro-stations.geojson"), metroEntrances: bundled("metro-entrances.geojson"), marc: bundled("marc-penn-stations.geojson"), osmElevators: bundled("metro-osm-elevators.geojson") };
  assert.ok(slim.metroStations.length + slim.metroEntrances.length < 0.8 * (texts.metroStations.length + texts.metroEntrances.length));
  assert.doesNotMatch(slim.metroEntrances, /CAPTUREYEAR|EXIT_TO_ST/);
  assert.doesNotMatch(slim.metroStations, /ADDRESS/);
  const full = stationsFromTexts(texts);
  const slimmed = stationsFromTexts(slim);
  assert.deepEqual(slimmed.map((s) => [s.id, s.name, s.metro, s.penn, s.elevators.length, s.osmElevators.length, s.entrances.length]), full.map((s) => [s.id, s.name, s.metro, s.penn, s.elevators.length, s.osmElevators.length, s.entrances.length]));
  for (const [i, s] of slimmed.entries()) assert.ok(Math.abs(s.point[0] - full[i].point[0]) < 1e-6 && Math.abs(s.point[1] - full[i].point[1]) < 1e-6, s.name);
  // Only the rail data's ?raw imports: anything else is Vite's.
  assert.equal(plugin.load(`${fileURLToPath(DATA)}metro-stations.geojson`), null);
  assert.equal(plugin.load(`${fileURLToPath(DATA)}metro-line-corrections.json?raw`), null);
  assert.equal(plugin.load("/elsewhere/x.geojson?raw"), null);
});
