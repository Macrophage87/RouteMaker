/**
 * The bundled rail fixtures (src/rail-data/README.md), parsed once.
 *
 * Imported as text so Vite puts them inside the app's script: no request of
 * their own, no path for the edge to serve, nothing for the
 * Content-Security-Policy to allow. railData.test.ts loads this module as the
 * app does.
 */
import metroStations from "../rail-data/metro-stations.geojson?raw";
import metroEntrances from "../rail-data/metro-entrances.geojson?raw";
import marc from "../rail-data/marc-penn-stations.geojson?raw";
import osmElevators from "../rail-data/metro-osm-elevators.geojson?raw";
import corrections from "../rail-data/metro-line-corrections.json?raw";
import wmataSlugs from "../rail-data/wmata-station-slugs.json?raw";
import type { LonLat } from "./geo.ts";
import { loadRailStations } from "./railFixtures.ts";
import { stationIndex, type Station } from "./railStations.ts";
import { parseStationSlugs, type StationSlugs } from "./stationLinks.ts";

export { PENN_COLOUR } from "./railStations.ts";

/** Empty, with a console warning, when a fixture no longer fits (railFixtures.ts). */
export const RAIL_STATIONS: readonly Station[] = loadRailStations({
  metroStations,
  metroEntrances,
  marc,
  osmElevators,
  corrections,
});

const index = stationIndex(RAIL_STATIONS);

export const stationById: (id: string) => Station | undefined = index.station;

/**
 * Where a ride to or from this station should be pointed: DC's elevator
 * nearest the station (the bike entrance); where DC lists none, OSM's; where
 * neither has one, its nearest other entrance; else the station itself
 * (railStations.ts, bikeEntrance). For anything that offers a station as a
 * place - the place search is to use it - so it puts the point where the
 * map's own station tap does. Null for an id it does not know.
 */
export const stationBikeEntrance: (stationId: string) => LonLat | null = index.bikeEntrance;

/**
 * The WMATA station page slugs (OWNER-DECISIONS 441b; lib/stationLinks.ts), checked once
 * against wmata.com; empty, with a console warning, if the fixture does not fit, so a
 * station then offers no WMATA link rather than a guessed one.
 */
export const WMATA_SLUGS: StationSlugs = (() => {
  const parsed = parseStationSlugs(wmataSlugs);
  if (!parsed) console.warn("rail-data/wmata-station-slugs.json does not fit; stations offer no WMATA link");
  return parsed ?? {};
})();
