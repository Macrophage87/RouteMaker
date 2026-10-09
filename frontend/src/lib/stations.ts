/**
 * The nearest stations to take a bike from or return one to (OWNER-DECISIONS 466, 466a), as plain
 * functions so they can be tested without a browser.
 *
 * Picking up (undocking), the three nearest stations that are at least 3/4 full; dropping off
 * (docking), the three nearest that are at most 1/4 full. The list comes from the API
 * (POST /api/bikeshare/stations, `core.bikeshare.nearby_stations`), from the operator's live
 * feed alone: nothing is kept, nothing is ranked beyond distance, and the rider chooses. The
 * words are generic ("Nearby stations"): no programme name, no mark.
 */
import type { Dials } from "./dials.ts";
import { formatStationDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";

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

/** What a screen reader hears for one station, and what its button says: "Station name, 82% full, 0.2 mi (320 m)". */
export function stationLabel(station: Pick<NearbyStation, "name" | "percent_full" | "distance_m">): string {
  return `${station.name}, ${Math.round(station.percent_full)}% full, ${stationDistance(station.distance_m)}`;
}

/** The section's heading. */
export function stationsHeading(action: StationAction): string {
  return action === "pickup" ? "Nearby stations to pick up a bike" : "Nearby stations to return a bike";
}

/** The one line that says what the list is: the criterion, and that the rider chooses. */
export function stationsLede(action: StationAction): string {
  return action === "pickup"
    ? "The 3 nearest stations at least 3/4 full, so a bike is likely to be there. Choose one to start the ride from it."
    : "The 3 nearest stations at most 1/4 full, so a space is likely to be free. Choose one to end the ride at it.";
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
  if (preset !== "bikeshare") return {};
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

/** Which points the lists are for: the start (pick-up) once placed, and the end (drop-off) once a second is. */
export function listPoint(action: StationAction, points: readonly LonLat[]): LonLat | null {
  if (action === "pickup") return points.length >= 1 ? points[0]! : null;
  return points.length >= 2 ? points[points.length - 1]! : null;
}
