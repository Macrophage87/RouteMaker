/**
 * Rebalance Ride's day (Stephen, 2026-11-07: "When you dock, the ride ends, and you get a ride end screen. Maybe add a
 * daily total. Instead of "go back" you start the next one"; "Rebalance totals would be basically the total time and
 * distance on that mode for the day walking and biking, and the total number of trips"; "We'd have "do another trip"
 * and "finish session""). Each Rebalance Ride ended is added to the day's totals, kept on this device only (no place,
 * no time of day: the trips, the walking and the riding), and the day starts again at local midnight. A trip counts as
 * its ride ends, whatever closes the summary after; Keep riding takes it out again.
 *
 * The riding is the ride's own figures (lib/rideStats.ts); the walk to the dock is the plan's, as the ride does not
 * count the walk (statsPause).
 */
import { formatDistance, formatDuration } from "./format.ts";
import { t } from "./i18n.ts";

export const REBALANCE_DAY_KEY = "routemaker.rebalanceDay";

/** One Rebalance Ride: its walk to the dock and its ride to the next one. */
export interface RebalanceTrip {
  walkM: number;
  walkS: number;
  rideM: number;
  rideS: number;
}

/** The day's totals, by the device's own date. */
export interface RebalanceDay extends RebalanceTrip {
  day: string;
  trips: number;
}

type Store = Pick<Storage, "getItem" | "setItem">;

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The device's date, "2026-11-07": the day the totals are for. */
export function localDay(now: number): string {
  const d = new Date(now);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
}

const figure = (value: unknown) => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0);

/** Today's totals: none yet, or kept from another day, start again from nothing. */
export function readDay(store: Store | null = local(), now = Date.now()): RebalanceDay {
  const day = localDay(now);
  const empty: RebalanceDay = { day, trips: 0, walkM: 0, walkS: 0, rideM: 0, rideS: 0 };
  try {
    const kept = JSON.parse(store?.getItem(REBALANCE_DAY_KEY) ?? "null") as Partial<RebalanceDay> | null;
    if (!kept || typeof kept !== "object" || kept.day !== day) return empty;
    return { day, trips: Math.round(figure(kept.trips)), walkM: figure(kept.walkM), walkS: figure(kept.walkS), rideM: figure(kept.rideM), rideS: figure(kept.rideS) };
  } catch {
    return empty;
  }
}

/** The day with one more trip. */
export function withTrip(day: RebalanceDay, trip: RebalanceTrip): RebalanceDay {
  return {
    ...day,
    trips: day.trips + 1,
    walkM: day.walkM + figure(trip.walkM),
    walkS: day.walkS + figure(trip.walkS),
    rideM: day.rideM + figure(trip.rideM),
    rideS: day.rideS + figure(trip.rideS),
  };
}

/** Puts the day back as it was before a trip (Keep riding takes the ride back up, so it is not yet a trip). */
export function restoreDay(day: RebalanceDay, store: Store | null = local(), now = Date.now()): void {
  // Past midnight the kept day is already another's: nothing to put back.
  if (day.day !== localDay(now)) return;
  try {
    store?.setItem(REBALANCE_DAY_KEY, JSON.stringify(day));
  } catch {
    // As recordTrip.
  }
}

/** Adds a trip to today's totals as the ride ends (Keep riding takes it out again: restoreDay). */
export function recordTrip(trip: RebalanceTrip, store: Store | null = local(), now = Date.now()): RebalanceDay {
  const day = withTrip(readDay(store, now), trip);
  try {
    store?.setItem(REBALANCE_DAY_KEY, JSON.stringify(day));
  } catch {
    // Storage full or blocked: the totals are a convenience, the ride is unaffected.
  }
  return day;
}

/** The totals as dt/dd rows: trips, walking, riding, and the time of both. */
export function dayRows(day: RebalanceDay): { name: string; value: string }[] {
  return [
    { name: t("Trips"), value: String(day.trips) },
    { name: t("Walking"), value: `${formatDistance(day.walkM)}, ${formatDuration(day.walkS)}` },
    { name: t("Riding"), value: `${formatDistance(day.rideM)}, ${formatDuration(day.rideS)}` },
    { name: t("Total time"), value: formatDuration(day.walkS + day.rideS) },
  ];
}

export const REBALANCE_TODAY = t("Today's Rebalance Rides");
export const DO_ANOTHER_TRIP = t("Do another trip");
export const FINISH_SESSION = t("Finish session");
/** Where a Rebalance Ride ends before it is planned: it has no destination of its own. */
export const REBALANCE_ENDS_AT_DOCK = t("The nearest dock that needs bikes");

/** One ended Rebalance Ride: its walk to the dock as planned, and its ride as ridden. */
export function tripOf(plan: { walk_m: number; walk_s: number } | null | undefined, ridden: { distanceM: number; movingMs: number }): RebalanceTrip {
  return { walkM: plan?.walk_m ?? 0, walkS: plan?.walk_s ?? 0, rideM: ridden.distanceM, rideS: ridden.movingMs / 1000 };
}

/** Said on Do another trip, as the summary goes. */
export const REBALANCE_NEXT_SAID = t("Planning the next Rebalance Ride from where you docked.");
