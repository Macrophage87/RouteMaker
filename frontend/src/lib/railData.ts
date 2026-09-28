/**
 * The bundled rail fixtures (src/rail-data/README.md), parsed once.
 *
 * Imported as text so Vite puts them inside the app's script: no request of
 * their own, no path for the edge to serve, nothing for the
 * Content-Security-Policy to allow.
 */
import metroStationsText from "../rail-data/metro-stations.geojson?raw";
import metroEntrancesText from "../rail-data/metro-entrances.geojson?raw";
import marcText from "../rail-data/marc-penn-stations.geojson?raw";
import osmElevatorsText from "../rail-data/metro-osm-elevators.geojson?raw";
import correctionsText from "../rail-data/metro-line-corrections.json?raw";
import type { LonLat } from "./geo.ts";
import { buildStations, stationIndex, type Station } from "./railStations.ts";

export { PENN_COLOUR } from "./railStations.ts";

export const RAIL_STATIONS: readonly Station[] = buildStations(
  JSON.parse(metroStationsText),
  JSON.parse(metroEntrancesText),
  JSON.parse(marcText),
  { corrections: JSON.parse(correctionsText), osmElevators: JSON.parse(osmElevatorsText) },
);

const index = stationIndex(RAIL_STATIONS);

export const stationById: (id: string) => Station | undefined = index.station;

/**
 * Where a ride to or from this station should be pointed: its elevator (the
 * bike entrance), else its nearest entrance, else the station. For any
 * feature that offers a station as a place, the map's tap and the place
 * search alike, so both put the point in the same spot. Null for an id it
 * does not know.
 */
export const stationBikeEntrance: (stationId: string) => LonLat | null = index.bikeEntrance;
