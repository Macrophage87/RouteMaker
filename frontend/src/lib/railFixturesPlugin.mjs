/**
 * The build refuses rail fixtures that no longer fit (src/rail-data/README.md).
 *
 * The running app would leave the rail stations off the map, with a console
 * warning, when a fixture no longer fits: a line correction gone stale after
 * a refresh, or an unknown line (railFixtures.ts, loadRailStations). That is
 * the right thing in a browser and the wrong thing to ship, so `npm run build`
 * builds the stations from the committed files first, with the same code, and
 * fails on the same error - whether or not `npm test` ran before it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { RAIL_FIXTURE_FILES, stationsFromTexts } from "./railFixtures.ts";

/** The stations the fixtures in `dataDir` make; throws where one no longer fits. */
export function checkRailFixtures(dataDir) {
  const texts = Object.fromEntries(
    Object.entries(RAIL_FIXTURE_FILES).map(([key, file]) => [key, readFileSync(join(dataDir, file), "utf8")]),
  );
  const stations = stationsFromTexts(texts);
  if (stations.length === 0) throw new Error(`no rail stations in ${dataDir}`);
  return stations;
}

/**
 * Properties of DC's files that nothing reads (railStations.ts): left out of what the app bundles, with
 * the coordinates cut to 6 decimals (about 4 in, 0.1 m), so the app's script carries less (review fe-perf-7).
 */
export const UNUSED_RAIL_PROPERTIES = {
  "metro-stations.geojson": ["ADDRESS"],
  "metro-entrances.geojson": ["EXIT_TO_ST", "CAPTUREYEAR"],
};

/** A GeoJSON fixture's text, slimmed: `drop`'s properties gone, the coordinates rounded, no spaces. */
export function slimRailFixture(text, drop = []) {
  const data = JSON.parse(text);
  for (const feature of data.features ?? []) {
    for (const key of drop) delete feature.properties?.[key];
    const c = feature.geometry?.coordinates;
    if (Array.isArray(c)) feature.geometry.coordinates = c.map((n) => (typeof n === "number" ? Math.round(n * 1e6) / 1e6 : n));
  }
  return JSON.stringify(data);
}

/** The Vite plugin: the check, before anything is built, and the slimmed GeoJSON fixtures for the bundle. */
export function railFixtures(dataDir) {
  const dir = dataDir.replace(/\/$/, "");
  return {
    name: "rail-fixtures",
    // Before Vite's own ?raw loader, so the bundle gets the slimmed text.
    enforce: "pre",
    load(id) {
      const [path, query] = id.split("?");
      if (query !== "raw" || !path.startsWith(`${dir}/`) || !path.endsWith(".geojson")) return null;
      const name = path.slice(dir.length + 1);
      return `export default ${JSON.stringify(slimRailFixture(readFileSync(path, "utf8"), UNUSED_RAIL_PROPERTIES[name] ?? []))};`;
    },
    buildStart() {
      try {
        checkRailFixtures(dataDir);
      } catch (error) {
        this.error(`rail fixtures (src/rail-data/README.md): ${error instanceof Error ? error.message : error}`);
      }
    },
  };
}
