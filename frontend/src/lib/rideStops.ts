/**
 * A ride's stops (Stephen 2026-10-24): "If a reroute needs to be done assume via points are guides and stops are
 * mandatory, though add the option to skip a stop or go to a different one. Stops should appear on the map when
 * riding." Neither adds a ride button: Skip this stop, in the ride's More panel with the settings (Stephen 2026-10-24),
 * re-plans from here without it; a nearest place's "Instead", in the Detour menu, re-plans to that place in its stead.
 */
import type { LonLat } from "./geo.ts";
import type { RideStopMark } from "./pointKinds.ts";

/** The next stop's line in the More panel: "Next stop: Stop 2, Union Market". */
export function nextStopLine(stop: RideStopMark): string {
  return `Next stop: ${stopWords(stop)}`;
}

/** "Stop 2, Union Market", or "Stop 2" with no name. */
export function stopWords(stop: RideStopMark): string {
  return stop.name ? `Stop ${stop.number}, ${stop.name}` : `Stop ${stop.number}`;
}

export const SKIP_STOP = "Skip this stop";

/** Said as Skip this stop is pressed. */
export function skippingSaid(stop: RideStopMark): string {
  return `Skipping ${stopWords(stop)}. Finding a new route.`;
}

/** A nearest place's second button while a stop is ahead: its words, and its name for a screen reader. */
export function insteadLabel(stop: RideStopMark): string {
  return `Instead of stop ${stop.number}`;
}
export function insteadName(place: string, stop: RideStopMark): string {
  return `Go to ${place} instead of ${stopWords(stop).replace(/^Stop/, "stop")}`;
}

/** Said as a place is chosen instead of the next stop. */
export function insteadSaid(place: string, stop: RideStopMark): string {
  return `Finding a way to ${place} instead of stop ${stop.number}.`;
}

/** The Detour button's name: what it offers, the next stop's options too while one is ahead. */
export function detourButtonName(summary: string, stop: RideStopMark | null): string {
  return stop ? `Detour: ${summary.toLowerCase()}, or change stop ${stop.number}` : `Detour: ${summary.toLowerCase()}`;
}

/** The re-plan's points without the stop at `skip` (its index in the plan): the rider's place stays first. */
export function withoutStop(points: readonly LonLat[], kept: readonly number[], here: LonLat, skip: number): LonLat[] {
  return [here, ...kept.filter((i) => i !== skip).map((i) => points[i])];
}
