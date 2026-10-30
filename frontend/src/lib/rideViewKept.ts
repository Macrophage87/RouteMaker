import type { RideStopMark } from "./pointKinds.ts";
import type { RideView } from "../RideMode.tsx";

/**
 * Whether a ride's new view (RideMode's onView) changes anything but the rider's position: if not, App keeps the view
 * it has and does not re-render, and the position goes to the map through its own store (lib/liveValue.ts, fe-perf-1).
 * The stops ahead are worked out again every 10 m of progress, so they are compared by what they show.
 */
export function rideViewKept(was: RideView | null, next: RideView | null): boolean {
  if (!was || !next) return was === next;
  return (
    was.route === next.route &&
    (was.other ?? null) === (next.other ?? null) &&
    (was.vehicle ?? null) === (next.vehicle ?? null) &&
    sameStops(was.stops, next.stops) &&
    (was.lettered ?? null) === (next.lettered ?? null) &&
    was.onLettered === next.onLettered
  );
}

function sameStops(a: RideStopMark[] | undefined, b: RideStopMark[] | undefined): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((stop, i) => {
    const other = b[i];
    return stop.number === other.number && stop.name === other.name && stop.point[0] === other.point[0] && stop.point[1] === other.point[1];
  });
}
