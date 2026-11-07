/**
 * Rebalance Ride's drop-off, chosen at the pick-up dock (Stephen, 2026-11-07: "When you start, find the nearest full
 * dock. When at that dock, then search for a destination", "Because in the interim, bikes could be filled", "when you
 * reach the dock, instead of a typical end or switch screen, show the options for a destination").
 *
 * The plan walks to the nearest crowded dock and draws a ride on to the dock that needed bikes when it was planned.
 * Once the rider reaches the crowded dock, the ride holds there and asks the drop-off list again, live (POST
 * /api/bikeshare/stations, "dropoff": at most 1/4 full, nearest first): up to three docks to choose from, never the
 * dock the rider is at. The choice is ridden from that dock; with no list (no signal, none needing bikes) the planned
 * dock is offered instead.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { haversineM, type LonLat } from "./geo.ts";
import { formatStationDistance } from "./format.ts";
import { t } from "./i18n.ts";
import type { NearbyStation } from "./stations.ts";
import type { RouteResponse } from "./api.ts";

/** The walk ended this far from the planned dock (a bike taken at another, the line joined along it): asked from there. */
export const DOCK_AWAY_M = 60;

/** The dock chosen and the ride to it as it stands at the end, so Keep riding carries on to it. */
export interface RebalanceDocked {
  name: string;
  route: RouteResponse;
  points: LonLat[];
}

/** Up to this many docks to choose from. */
export const DOCK_CHOICES = 3;
/** A listed station this near the pick-up dock is that dock (or one beside it): not a drop-off. */
export const SAME_DOCK_M = 40;

/** One dock to choose. */
export interface DockChoice {
  id: string;
  name: string;
  point: LonLat;
  /** Free docks to take a bike, by the live count. */
  docks: number;
  /** Straight line from the pick-up dock, in metres. */
  distanceM: number;
}

/** The drop-off list, without the pick-up dock itself, nearest first, at most DOCK_CHOICES. */
export function dockChoices(stations: readonly NearbyStation[], pickupAt: LonLat, pickupName: string | null = null): DockChoice[] {
  return stations
    .map((s) => ({ id: s.station_id, name: s.name, point: [s.lon, s.lat] as LonLat, docks: s.docks, distanceM: s.distance_m }))
    .filter((s) => haversineM(s.point, pickupAt) >= SAME_DOCK_M && s.name !== pickupName)
    .sort((a, b) => a.distanceM - b.distanceM)
    .slice(0, DOCK_CHOICES);
}

/** Its button: the name, then how far and how much room. */
export function dockChoiceLine(choice: DockChoice): string {
  return t("{distance} away, {count} open docks", { distance: formatStationDistance(choice.distanceM), count: choice.docks });
}

/** What the ride's card says, at each step of choosing. */
export const DOCK_CHOOSE_HEADING = t("Where to dock?");
export const DOCK_CHOOSE_LEDE = t("Docks near here that need bikes, nearest first, from the live counts.");
export const DOCK_FINDING = t("Finding docks that need bikes.");
export const DOCK_NONE_NEEDS = t("No dock near here needs bikes right now.");
export const DOCK_RETRY = t("Try again");
export const dockRouting = (name: string) => t("Finding the way to {place}.", { place: name });
export const dockChosenSaid = (name: string) => t("Ride to {place} and dock there.", { place: name });
export const dockAsPlanned = (name: string) => t("Ride to {place}, as planned", { place: name });
/** Said as the rider reaches the pick-up dock, in place of "Take a bike and ride". */
export const dockReachedSaid = (name: string) => t("At {place}. Take a bike, then choose where to dock.", { place: name });
export const DOCK_ROUTE_FAILED = t("No way there was found. Choose another dock.");
