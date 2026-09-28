/**
 * The bundled rail fixtures (src/rail-data/README.md) to stations: the one
 * call railData.ts makes at load and vite.config.ts makes before a build, so
 * both are the same code and node --test runs it.
 */
import { buildStations, type Station } from "./railStations.ts";

/** The fixtures, by what they are, as their file names in src/rail-data/. */
export const RAIL_FIXTURE_FILES = {
  metroStations: "metro-stations.geojson",
  metroEntrances: "metro-entrances.geojson",
  marc: "marc-penn-stations.geojson",
  osmElevators: "metro-osm-elevators.geojson",
  corrections: "metro-line-corrections.json",
} as const;

export type RailTexts = Record<keyof typeof RAIL_FIXTURE_FILES, string>;

/**
 * Every station, with the line corrections and OSM's fallback elevators
 * applied. Throws where a fixture no longer fits: an unknown line, or a
 * correction that is stale (railStations.ts, applyCorrections).
 */
export function stationsFromTexts(texts: RailTexts): Station[] {
  return buildStations(JSON.parse(texts.metroStations), JSON.parse(texts.metroEntrances), JSON.parse(texts.marc), {
    corrections: JSON.parse(texts.corrections),
    osmElevators: JSON.parse(texts.osmElevators),
  });
}

/**
 * The same, for the running app: a fixture that no longer fits costs the rail
 * stations, with a warning, and not the whole planner. The build refuses such
 * a fixture before it gets here (vite.config.ts), so this is the second line.
 */
export function loadRailStations(
  texts: RailTexts,
  warn: (message: string) => void = (message) => console.warn(message),
): Station[] {
  try {
    return stationsFromTexts(texts);
  } catch (error) {
    warn(`Rail stations left off the map: ${error instanceof Error ? error.message : String(error)}`);
    return [];
  }
}
