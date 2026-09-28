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

/** The Vite plugin: the check, before anything is built. */
export function railFixtures(dataDir) {
  return {
    name: "rail-fixtures",
    buildStart() {
      try {
        checkRailFixtures(dataDir);
      } catch (error) {
        this.error(`rail fixtures (src/rail-data/README.md): ${error instanceof Error ? error.message : error}`);
      }
    },
  };
}
