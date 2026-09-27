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
import type { LonLat } from "./geo.ts";
import { bikeEntrance, buildStations, type MarcCollection, type Station } from "./railStations.ts";

const marc = JSON.parse(marcText) as MarcCollection;

export const RAIL_STATIONS: readonly Station[] = buildStations(
  JSON.parse(metroStationsText),
  JSON.parse(metroEntrancesText),
  marc,
);

/**
 * The Penn Line's colour: the OSM route relation's colour= tag. Should a
 * regenerated fixture lack one, a slate that is none of Metro's six.
 */
export const PENN_COLOUR: string = marc.colour ?? "#5b6b8c";

const byId = new Map(RAIL_STATIONS.map((station) => [station.id, station]));

export function stationById(id: string): Station | undefined {
  return byId.get(id);
}

/**
 * Where a ride to or from this station should be pointed: its elevator (the
 * bike entrance), or the station when it has none. For any feature that
 * offers a station as a place, the map's tap and the place search alike, so
 * both put the point in the same spot. Null for an id it does not know.
 */
export function stationBikeEntrance(stationId: string): LonLat | null {
  const station = byId.get(stationId);
  return station ? bikeEntrance(station) : null;
}
