/**
 * Make it a loop (OWNER-DECISIONS 266): out to the destination and back to the start
 * by a different way. A ride that ends where it starts is one without asking.
 * With the toggle on, the first point is the start and the finish and every later
 * point is a stop (OWNER-DECISIONS 374): no second point is stacked on the start.
 */
import type { RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import type { PresetId } from "./presets.ts";
import { formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";

/** A ride ends where it starts within this (metres): `core.routing.LOOP_SAME_M`, held equal by tests/test_plan_constants.py. */
export const LOOP_SAME_M = 50;

/** Whether the points start and end in the same place, with a place between. */
export function isRoundTrip(points: readonly LonLat[]): boolean {
  return points.length >= 3 && haversineM(points[0], points[points.length - 1]) <= LOOP_SAME_M;
}

/**
 * Whether Reverse keeps the start (OWNER-DECISIONS 374): in a loop the rider
 * chose, the start is also the finish, so Reverse rides the stops the other
 * way around from the same start. A ride that already ends on its start
 * (isRoundTrip) is reversed whole: its two ends are one place.
 */
export function reverseKeepsStart(points: readonly LonLat[], loop: boolean): boolean {
  return loop && !isRoundTrip(points);
}

/** The points after Reverse: the stops the other way around in a loop, otherwise the whole list. */
export function reversedPoints(points: readonly LonLat[], loop: boolean): LonLat[] {
  if (points.length < 2) return [...points];
  if (reverseKeepsStart(points, loop)) return [points[0], ...points.slice(1).reverse()];
  return [...points].reverse();
}

/** Whether Reverse changes anything: a loop of a start and one stop is the same either way around. */
export function canReverse(points: readonly LonLat[], loop: boolean): boolean {
  return points.length >= (reverseKeepsStart(points, loop) ? 3 : 2);
}

export interface LoopView {
  label: string;
  /** On, whether chosen or because the ride ends where it starts. */
  checked: boolean;
  /** Implied by the points: it cannot be turned off short of moving a point. */
  implied: boolean;
  hint: string;
}

export const LOOP_LABEL = "Make it a loop";

/** The first point of a loop the rider chose, where the ride starts and finishes (OWNER-DECISIONS 374). */
export const LOOP_START_NAME = "Start and finish";

/**
 * Whether points are named and placed as a loop's: the rider turned "Make it a
 * loop" on (OWNER-DECISIONS 374), so the first point is the start and finish and
 * every later one a stop. Mass Ride has no loop. An implied loop (a ride that ends
 * on its start without the toggle) keeps the usual names.
 */
export function loopStops(preset: PresetId, loop: boolean | undefined): boolean {
  return preset !== "mass-ride" && preset !== "bikeshare" && loop === true;
}

/**
 * What to do first when the loop is checked before any point is placed (OWNER-DECISIONS 389). It is the
 * toggle's visible hint then, and what is said once when the box is checked (pointText.ts).
 */
export const LOOP_FIRST_HINT = "Place the starting point, then a stop or two along the way.";

/** The toggle's hint: what it does now, in the state the points are in. */
function loopHint(loop: boolean | undefined, implied: boolean, count: number): string {
  if (implied) {
    return "This ride ends where it starts, so it is planned as a loop: the way back avoids the roads the way out used, where there is another way.";
  }
  if (loop === true) {
    return count === 0
      ? LOOP_FIRST_HINT
      : "Starts and finishes at your first point. Each point you add after it is a stop on the way around, and the way back avoids the roads the way out used where there is another way.";
  }
  if (count < 2) return "Turn on to finish back at the start. Each point you add is then a stop.";
  return "Plans the way to your end point, then a different way back to the start. The way back avoids the roads the way out used where there is another way.";
}

/**
 * The toggle, or null where it does not apply (Mass Ride). It shows with no points placed too
 * (OWNER-DECISIONS 389); with a start alone it can be chosen, and the next click is then a stop
 * (OWNER-DECISIONS 374).
 */
export function loopView(preset: PresetId, loop: boolean | undefined, points: readonly LonLat[]): LoopView | null {
  if (preset === "mass-ride" || preset === "bikeshare") return null;
  const implied = isRoundTrip(points);
  return { label: LOOP_LABEL, checked: implied || loop === true, implied, hint: loopHint(loop, implied, points.length) };
}

/** The dials with the loop on, or off (taken off the object). */
export function withLoop(dials: Dials, on: boolean): Dials {
  const next: Dials = { ...dials };
  if (on) next.loop = true;
  else delete next.loop;
  return next;
}

/** What the route summary says of a loop's way back, or null where the route is not a loop. */
export function loopNote(route: Pick<RouteResponse, "loop">): string | null {
  const loop = route.loop;
  if (!loop) return null;
  if (loop.fallback === "out_and_back") {
    return "There is no other way back that fits, so this loop returns the way it went out.";
  }
  if (loop.fallback) return "This loop could not look for another way back in time, so the way back is the usual route for this ride type.";
  if (loop.overlap_pct == null || loop.shared_m == null) return null;
  if (loop.shared_m <= 0) return "The way back shares no road with the way out.";
  return `${Math.round(loop.overlap_pct)}% of the way back, ${formatDistance(loop.shared_m)}, is on roads the way out used.`;
}
