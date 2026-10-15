/**
 * The nearest stations to take a bike from or return one to (OWNER-DECISIONS 466, 466a), as plain
 * functions so they can be tested without a browser.
 *
 * Picking up (undocking), three stations that are at least 3/4 full; dropping off (docking),
 * three that are at most 1/4 full. The list comes from the API (POST /api/bikeshare/stations,
 * `core.bikeshare.nearby_stations`), from the operator's live feed alone: nothing is kept, and
 * the rider chooses. Once both ends are placed the stations on the rider's way come first (the
 * owner, 2026-10-11): each is ranked by its walk plus the extra riding it adds, and its label
 * says so in words, "on your way" or "adds 0.1 mi (160 m) of riding", never by colour or an
 * arrow alone. The words are generic ("Nearby stations"): no programme name, no mark.
 */
import type { Dials } from "./dials.ts";
import { formatStationDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { usesBikeshare, type PresetId } from "./presets.ts";

export type StationAction = "pickup" | "dropoff";

/** One station of the list (core.api.NearbyStationOut). */
export interface NearbyStation {
  station_id: string;
  name: string;
  lon: number;
  lat: number;
  /** Bikes as a percentage of bikes and free docks. */
  percent_full: number;
  /** Straight line from the point, in metres. */
  distance_m: number;
  bikes: number;
  ebikes: number;
  docks: number;
  /** The riding the station adds, straight-line metres; null (or absent) without the trip's other end. */
  extra_m?: number | null;
  /** It adds under 165 ft (50 m) of riding; null (or absent) without the trip's other end. */
  on_the_way?: boolean | null;
}

/** The answer (core.api.NearbyStationsOut). */
export interface NearbyStationsAnswer {
  action: StationAction;
  availability: "live" | "stale" | "unknown";
  stations: NearbyStation[];
  credit: string;
}

/** "0.2 mi (320 m)": the one formatter of units is lib/format.ts. */
export const stationDistance = formatStationDistance;

/** "2 e-bikes", "1 e-bike", "no e-bikes" (the owner, 2026-10-10: e-bike counts in the station list). */
export function ebikeCount(ebikes: number): string {
  return ebikes === 0 ? "no e-bikes" : ebikes === 1 ? "1 e-bike" : `${ebikes} e-bikes`;
}

/**
 * The counts in words, the map's dock label said (v0.7.0, lib/bikeshareDocks.ts): "7 classic, 2 e-bikes,
 * 2 open docks". `bikes` counts e-bikes too.
 */
export function stationCounts(station: Pick<NearbyStation, "bikes" | "ebikes" | "docks">): string {
  const classic = Math.max(0, station.bikes - station.ebikes);
  const ebikes = station.ebikes === 1 ? "1 e-bike" : `${station.ebikes} e-bikes`;
  const docks = station.docks === 1 ? "1 open dock" : `${station.docks} open docks`;
  return `${classic} classic, ${ebikes}, ${docks}`;
}

/** Why a station sits where it does in the list, in words: "on your way", "adds 0.1 mi (160 m) of riding", or null without the trip's other end. */
export function wayWords(station: Pick<NearbyStation, "extra_m" | "on_the_way">): string | null {
  if (station.on_the_way === true) return "on your way";
  if (station.on_the_way === false && typeof station.extra_m === "number") {
    return `adds ${stationDistance(station.extra_m)} of riding`;
  }
  return null;
}

/**
 * What a screen reader hears for one station, and what its button says: "Station name, 82% full: 7 classic,
 * 2 e-bikes, 2 open docks, 0.2 mi (320 m)", and, once both ends are placed, ", on your way" or ", adds 0.1 mi
 * (160 m) of riding".
 */
export function stationLabel(
  station: Pick<NearbyStation, "name" | "percent_full" | "bikes" | "ebikes" | "docks" | "distance_m" | "extra_m" | "on_the_way">,
): string {
  const base = `${station.name}, ${Math.round(station.percent_full)}% full: ${stationCounts(station)}, ${stationDistance(station.distance_m)}`;
  const why = wayWords(station);
  return why ? `${base}, ${why}` : base;
}

/** The section's heading. */
export function stationsHeading(action: StationAction): string {
  return action === "pickup" ? "Nearby stations to pick up a bike" : "Nearby stations to return a bike";
}

/**
 * The one line that says what the list is: the criterion, the order, and that the rider chooses.
 * `directed`: the trip's other end is placed, so stations on the rider's way come first.
 */
export function stationsLede(action: StationAction, directed = false): string {
  if (!directed) {
    return action === "pickup"
      ? "The 3 nearest stations at least 3/4 full, so a bike is likely to be there. Choose one to start the ride from it."
      : "The 3 nearest stations at most 1/4 full, so a space is likely to be free. Choose one to end the ride at it.";
  }
  return action === "pickup"
    ? "3 stations at least 3/4 full, so a bike is likely to be there. Stations on your way come first; one behind you counts its extra riding as walking. Choose one to start the ride from it."
    : "3 stations at most 1/4 full, so a space is likely to be free. Stations on your way in come first; one past your destination counts its extra riding as walking. Choose one to end the ride at it.";
}

/** What the status line says once a list has loaded. */
export function stationsListed(count: number, directed: boolean): string {
  const what = count === 1 ? "station" : "stations";
  return `${count} nearby ${what} listed, ${directed ? "on your way first" : "nearest first"}.`;
}

/** Said when the list is empty, or could not be had. */
export function stationsEmpty(action: StationAction, availability: NearbyStationsAnswer["availability"]): string {
  if (availability === "unknown") return "Station availability is not available right now, so no list can be shown.";
  return action === "pickup"
    ? "No station nearby is at least 3/4 full right now."
    : "No station nearby is at most 1/4 full right now.";
}

/** The reading's age, said once under a list. */
export function stationsFreshness(availability: NearbyStationsAnswer["availability"]): string {
  return availability === "stale"
    ? "From a minute or two ago: the live count did not answer just now."
    : "Live counts, a minute or so old at most.";
}

/** What is said when a station is chosen, or the choice is cleared. */
export function chosenSaid(action: StationAction, station: NearbyStation | null): string {
  const what = action === "pickup" ? "pick-up" : "drop-off";
  return station ? `${station.name} chosen for the ${what}.` : `The ${what} station is chosen for you again.`;
}

// --- Choosing one ---------------------------------------------------------------

/** A station the rider chose, and the point it was chosen for: moving that point forgets it. */
export interface Pin {
  id: string;
  name: string;
  at: LonLat;
}

export interface Pins {
  pickup?: Pin;
  dropoff?: Pin;
}

function samePoint(a: LonLat, b: LonLat | undefined): boolean {
  return b !== undefined && a[0] === b[0] && a[1] === b[1];
}

/** The pins that still hold: the start and end unmoved, on Bikeshare. */
export function activePins(preset: PresetId, points: readonly LonLat[], pins: Pins): Pins {
  if (!usesBikeshare(preset)) return {};
  const active: Pins = {};
  if (pins.pickup && samePoint(pins.pickup.at, points[0])) active.pickup = pins.pickup;
  if (pins.dropoff && points.length >= 2 && samePoint(pins.dropoff.at, points[points.length - 1])) {
    active.dropoff = pins.dropoff;
  }
  return active;
}

/** The dials a plan is sent with: the chosen stations added, or none. Never in the link. */
export function withStations(dials: Dials, pins: Pins): Dials {
  const { pickupStation: _p, dropoffStation: _d, ...rest } = dials;
  return {
    ...rest,
    ...(pins.pickup ? { pickupStation: pins.pickup.id } : {}),
    ...(pins.dropoff ? { dropoffStation: pins.dropoff.id } : {}),
  };
}

/**
 * The trip's other end, which a list is ranked toward: the destination for the pick-up list and
 * the start for the drop-off list; null until both are placed (the list is then by distance).
 */
export function listToward(action: StationAction, points: readonly LonLat[]): LonLat | null {
  if (points.length < 2) return null;
  return action === "pickup" ? points[points.length - 1]! : points[0]!;
}

/** Which points the lists are for: the start (pick-up) once placed, and the end (drop-off) once a second is. */
export function listPoint(action: StationAction, points: readonly LonLat[]): LonLat | null {
  if (action === "pickup") return points.length >= 1 ? points[0]! : null;
  return points.length >= 2 ? points[points.length - 1]! : null;
}
