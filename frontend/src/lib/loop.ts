/**
 * Make it a loop (OWNER-DECISIONS 266): out to the destination and back to the start
 * by a different way. A ride that ends where it starts is one without asking.
 */
import type { RouteResponse } from "./api.ts";
import type { PresetId } from "./presets.ts";
import { formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";

/** A ride ends where it starts within this (metres): `core.routing.LOOP_SAME_M`, held equal by tests/test_plan_constants.py. */
export const LOOP_SAME_M = 50;

/** Whether the points start and end in the same place, with a place between. */
export function isRoundTrip(points: readonly LonLat[]): boolean {
  return points.length >= 3 && haversineM(points[0], points[points.length - 1]) <= LOOP_SAME_M;
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

/** The toggle, or null where it does not apply (Mass Ride; fewer than two points). */
export function loopView(preset: PresetId, loop: boolean | undefined, points: readonly LonLat[]): LoopView | null {
  if (preset === "mass-ride" || points.length < 2) return null;
  const implied = isRoundTrip(points);
  return {
    label: LOOP_LABEL,
    checked: implied || loop === true,
    implied,
    hint: implied
      ? "This ride ends where it starts, so it is planned as a loop: the way back avoids the roads the way out used, where there is another way."
      : "Plans the way to your end point, then a different way back to the start. The way back avoids the roads the way out used where there is another way.",
  };
}

/** What the route summary says of a loop's way back, or null where the route is not a loop. */
export function loopNote(route: Pick<RouteResponse, "loop">): string | null {
  const loop = route.loop;
  if (!loop) return null;
  if (loop.fallback === "out_and_back") {
    return "There is no other way back that fits, so this loop returns the way it went out.";
  }
  if (loop.fallback) return "This loop could not look for another way back in time, so the way back is the router's own.";
  if (loop.overlap_pct == null || loop.shared_m == null) return null;
  if (loop.shared_m <= 0) return "The way back shares no road with the way out.";
  return `${Math.round(loop.overlap_pct)}% of the way back (${formatDistance(loop.shared_m)}) is on roads the way out used.`;
}
