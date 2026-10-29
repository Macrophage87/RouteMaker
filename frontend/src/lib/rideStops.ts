/**
 * A ride's stops (Stephen 2026-10-24): "If a reroute needs to be done assume via points are guides and stops are
 * mandatory, though add the option to skip a stop or go to a different one. Stops should appear on the map when
 * riding." Neither adds a side button: Skip this stop, a bubble More opens (Stephen 2026-10-24; a bubble since 2026-10-26),
 * re-plans from here without it; a nearest place's "Instead", in the Detour menu, re-plans to that place in its stead.
 */
import type { LonLat } from "./geo.ts";
import { ARRIVE_M, type RideModel } from "./navigate.ts";
import type { RideStopMark } from "./pointKinds.ts";
import { t } from "./i18n.ts";

/** The Skip bubble's name beside More: "Skip stop 2, Union Market"; on screen its symbol and the stop's number. */
export function skipStopName(stop: Pick<RideStopMark, "number" | "name">): string {
  return `Skip ${stopWords(stop).replace(/^Stop/, "stop")}`;
}

/** "Stop 2, Union Market", or "Stop 2" with no name. */
export function stopWords(stop: Pick<RideStopMark, "number" | "name">): string {
  return stop.name ? `Stop ${stop.number}, ${stop.name}` : `Stop ${stop.number}`;
}

export const SKIP_STOP = t("Skip this stop");

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
  return stop ? t("Detour: {summary}, or change stop {number}", { summary: summary.toLowerCase(), number: stop.number }) : t("Detour: {summary}", { summary: summary.toLowerCase() });
}

/** The re-plan's points without the stop at `skip` (its index in the plan): the rider's place stays first. */
export function withoutStop(points: readonly LonLat[], kept: readonly number[], here: LonLat, skip: number): LonLat[] {
  return [here, ...kept.filter((i) => i !== skip).map((i) => points[i])];
}

/**
 * Restarting part way (Stephen 2026-10-24: "let people pick the stops that are already done, with the logical defaults
 * selected and continue the rest"): a ride whose first fix is past a stop asks, once, which stops are done. Each stop
 * of the route, the ones behind the rider ticked.
 */
export interface RestartStop {
  /** Its place in the plan's points. */
  index: number;
  number: number;
  name?: string;
  /** Behind the rider on the line: ticked at first. */
  passed: boolean;
}

export const RESTART_HEADING = t("Already done?");
export const RESTART_LEAD = t("Ticked stops are skipped. Untick one to go back to it.");
export const RESTART_CONTINUE = "Continue";
/**
 * Left unanswered while the rider rides this far (about 650 ft) from where it was asked, the question closes with the
 * stops as marked (the ride as it is), so it never holds re-routing back or covers the ride for long (the 2026-10-29
 * review).
 */
export const RESTART_AUTO_M = 200;
export const RESTART_AUTO_SAID = t("Riding on with the stops as marked.");

/** Said as the question shows. */
export function restartSaid(stops: readonly RestartStop[]): string {
  const done = stops.filter((s) => s.passed).length;
  return `You are part way along. ${done === 1 ? "1 stop is" : `${done} stops are`} marked done. ${RESTART_CONTINUE} to ride the rest.`;
}

/** Said when the picks change the route: the ride is planned again from here. */
export function restartReplanSaid(stops: readonly RestartStop[], done: ReadonlySet<number>): string {
  const back = stops.filter((s) => s.passed && !done.has(s.index));
  return back.length ? `Finding a route back to ${back.map(stopWords).join(" and ")}.` : "Finding a new route for the stops left.";
}

/** The route's stops, those behind `progressM` passed; null where none is behind (nothing to ask). */
export function restartStops(model: Pick<RideModel, "cues">, progressM: number): RestartStop[] | null {
  const stops: RestartStop[] = [];
  for (const cue of model.cues) {
    if (cue.kind !== "stop" || cue.stop === null) continue;
    stops.push({ index: cue.point ?? cue.stop, number: cue.stop, ...(cue.stopName ? { name: cue.stopName } : {}), passed: cue.atM <= progressM + ARRIVE_M });
  }
  return stops.some((s) => s.passed) ? stops : null;
}

/** The picks are the defaults: the ride goes on as it is, with no new route. */
export function restartUnchanged(stops: readonly RestartStop[], done: ReadonlySet<number>): boolean {
  return stops.every((s) => s.passed === done.has(s.index));
}

/**
 * The points a restart's re-plan keeps, by their place in the plan (as replanKept's): every stop not marked done,
 * behind the rider or not, in the plan's order; a via point only where it is still ahead; the end (a loop's start).
 */
export function restartKept(model: Pick<RideModel, "passes">, progressM: number, points: readonly LonLat[], loop: boolean, done: ReadonlySet<number>): number[] {
  const last = loop ? points.length : points.length - 1;
  const left: number[] = [];
  for (let i = 1; i < last; i += 1) {
    if (done.has(i)) continue;
    const pass = model.passes?.find((p) => p.point === i);
    if (pass && pass.atM <= progressM + ARRIVE_M) continue;
    left.push(i);
  }
  left.push(loop ? 0 : points.length - 1);
  return left;
}
