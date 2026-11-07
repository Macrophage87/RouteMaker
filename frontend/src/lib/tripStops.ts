/**
 * Stops on a Walk, transit or Bikeshare trip (Stephen, 2026-11-02: "Add the stops in for all";
 * 2026-11-03: "Each stop starts a new trip"; Bikeshare in v0.22.0, the bike returned at each stop). The API plans each leg between stops as a trip of its own, leaving the stop as the leg before arrives there,
 * and answers them one after another (`stop_steps`). The ride follows one trip at a time: the first, to the first stop;
 * there, "Start the next leg" plans the rest again from where the rider is, leaving then, as a stop takes as long as
 * it takes.
 */
import type { RouteResponse, TransitPlan } from "./api.ts";
import { t } from "./i18n.ts";
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { isTransit, usesBikeshare, type PresetId } from "./presets.ts";

/** The control at a stop, once the trip to it is done. */
export const NEXT_LEG = t("Start the next leg");

/** A trip's key is its legs' keys joined (core/transit.py STOPS_KEY_SEP). */
export const STOPS_KEY_SEP = "+";

/**
 * Whether a ride type takes stops as trips of their own: Walk, the transit types and Bikeshare. Not Rebalance Ride,
 * which has no destination (Stephen, 2026-11-07): one trip from where the rider is, the next from the end screen.
 */
export function stopsAsTrips(preset: PresetId): boolean {
  return isTransit(preset) || (usesBikeshare(preset) && preset !== "rebalance");
}

/** The most stops such a trip takes (core/api.py MAX_TRIP_STOPS): the server refuses a fourth. */
export const MAX_TRIP_STOPS = 3;

/**
 * The most points a route of this ride type takes: the start alone on a Rebalance Ride, a start, its stops and an end
 * for trips of stops, else MAX_POINTS.
 */
export function maxPointsFor(preset: PresetId): number {
  if (preset === "rebalance") return 1;
  return stopsAsTrips(preset) ? MAX_TRIP_STOPS + 2 : MAX_POINTS;
}

/** Whether a route is a trip with stops. */
export function hasStops(route: Pick<RouteResponse, "transit" | "bikeshare">): boolean {
  return (route.transit?.stop_steps?.length ?? 0) > 0 || (route.bikeshare?.later?.length ?? 0) > 0;
}

/**
 * The first trip of a trip with stops, as a trip of its own: its steps to the first stop, its own key (the one the API
 * gives it alone), its own time. A trip with no stops is itself.
 */
export function firstTripOf(route: RouteResponse): RouteResponse {
  // A Bikeshare trip's body is its first trip already: only the later ones go.
  if (route.bikeshare?.later?.length) return { ...route, bikeshare: { ...route.bikeshare, later: [], trip_total_s: null } };
  const plan = route.transit;
  const end = plan?.stop_steps?.[0];
  if (!plan || end === undefined) return route;
  const steps = plan.steps.slice(0, end);
  const totalS = steps.reduce((sum, step) => sum + step.seconds + step.wait_s, 0);
  const key = plan.key.split(STOPS_KEY_SEP)[0];
  const minutes = Math.max(1, Math.round(totalS / 60));
  const options = plan.options.slice(0, 1).map((option) => ({ ...option, key, total_s: totalS, minutes }));
  const departure = plan.departure && plan.departure.step < end ? plan.departure : null;
  const first: TransitPlan = { ...plan, key, stop_steps: [], steps, total_s: totalS, minutes, options, departure };
  return { ...route, transit: first };
}

/** What is left after the trip ridden now: the stop it ends at, the stops after it and the end. */
export interface StopsLeft {
  preset: PresetId;
  points: LonLat[];
}

/** The stops left once the first trip of `route` (planned through `points`) is ridden; null with none left. */
export function stopsLeftOf(route: RouteResponse, points: readonly LonLat[], preset: PresetId): StopsLeft | null {
  if (!hasStops(route) || points.length < 3 || !stopsAsTrips(preset)) return null;
  return { preset, points: points.slice(1) };
}

/** The points the next leg is planned through: from where the rider is (else the stop), on through the rest. */
export function nextLegPoints(left: StopsLeft, riderAt: LonLat | null): LonLat[] {
  return [riderAt ?? left.points[0], ...left.points.slice(1)];
}
