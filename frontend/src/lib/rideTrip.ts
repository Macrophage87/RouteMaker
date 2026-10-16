/**
 * Riding a Bikeshare or transit plan in Ride mode (Stephen, 2026-10-16: "I can't start a bikeshare and
 * transit ride. There's no button"). The plan's line is only its riding leg: a Bikeshare plan's ride
 * from dock to dock, a transit plan's first ride. Start ride follows that leg, and these say what
 * comes either side of it, from what the plan already returns (no new request):
 *
 * - before the line (`approach`): the walk to the first dock, said in place of "off route" until the
 *   rider reaches the line's start; with the dock's bike count where the plan has it;
 * - at its end (`finish`): "Dock at <name>" and the walk on, or the transit plan's own boarding steps
 *   (line, stop, departure), said in place of the plain arrival;
 * - after the transit (`rest`): the trip's last riding leg, which "Ride the rest" plans from where
 *   the rider is to the destination as a normal route request, on the leg's ride type. A later
 *   step's line has no turn-by-turn words, so it is never ridden as it is.
 *
 * Rides longer than RIDE_MAX_M go to a bike computer, as ever: the rule is the riding leg's.
 */
import type { RouteResponse, TransitDeparture, TransitPlan, TransitStep } from "./api.ts";
import { bikeshareOf, dockCountWords } from "./bikeshare.ts";
import { formatDistance, spokenDistance } from "./format.ts";
import { haversineM, pathLengthM, type LonLat } from "./geo.ts";
import { POOR_FIX_M, RIDE_MAX_M, START_M, WINDOW_AHEAD_M, offThreshold, snap, type RideEvent, type RideFix, type RideModel } from "./navigate.ts";
import type { PresetId } from "./presets.ts";
import { drawOf, transitOf } from "./transit.ts";

/** A sentence for the screen (US units, metric in brackets) and the same for speech (US units only). */
export interface TripWords {
  shown: string;
  spoken: string;
}

export interface RideApproach {
  /** The line's start: the dock where the bike is taken. */
  at: LonLat;
  /** The dock's name ("Walk to <name>, <distance>."); null where the steps before the line are said instead. */
  name: string | null;
  /** The walk's length on the plan, where it has one. */
  metres: number | null;
  /** After the walk: the dock's bike count ("5 classic bikes available."), or the steps' own words. */
  extra: string;
  /** Said once the rider reaches it. */
  reached: string;
}

export interface RideRest {
  /** The step's words in the plan, for the panel: "Ride 1 min to your destination." */
  text: string;
  /** Where the transit leaves the rider (the last transit step's last stop), and its name. */
  alight: LonLat | null;
  alightName: string | null;
  /** The last riding leg's own start, where the plan has it: the request's start with no fix. */
  from: LonLat | null;
  to: LonLat;
  /** The leg's ride type: your own bike's, or Bikeshare's for a share bike (its walk and dock come with it). */
  preset: PresetId;
  /** The leg's length on the plan, where its line is drawn; null otherwise. */
  metres: number | null;
}

export interface RideTrip {
  approach: RideApproach | null;
  finish: TripWords | null;
  /** The departure the finish leads to (DepartureTimer), where the plan has one. */
  departure: TransitDeparture | null;
  rest: RideRest | null;
}

export const RIDE_REST = "Ride the rest";
export const RIDE_REST_HINT = "Turn-by-turn from where you are to your destination, for the ride after transit.";
export const RIDE_REST_FINDING = "Finding the ride to your destination…";
/** Said once on the ride screen when the button shows (near or past the stop where the transit ends). */
export function restReadySaid(rest: Pick<RideRest, "alightName">): string {
  return `${rest.alightName ? `Near ${rest.alightName}. ` : ""}${RIDE_REST} plans the ride to your destination.`;
}
/** How near the stop where the transit ends the ride screen offers Ride the rest. */
export const REST_NEAR_M = 400;

function isRiding(step: Pick<TransitStep, "mode">): boolean {
  return drawOf(step) === "ride";
}

function isTransitStep(step: Pick<TransitStep, "mode">): boolean {
  return drawOf(step) === "transit";
}

/** The transit plan's route-line step, the first ride. */
function lineIndex(plan: TransitPlan): number {
  return plan.steps.findIndex((s) => s.route_line);
}

/**
 * Whether Start ride is offered: the line is a riding leg no longer than RIDE_MAX_M. A Bikeshare plan's
 * line is its ride between the docks; a transit plan's is its first ride (not a walk).
 */
export function rideable(route: Pick<RouteResponse, "distance_m" | "transit">): boolean {
  if (route.distance_m > RIDE_MAX_M) return false;
  const plan = transitOf(route);
  if (!plan) return true;
  const index = lineIndex(plan);
  return index < 0 ? plan.direct && plan.mode === "bike-transit" : isRiding(plan.steps[index]);
}

/** Whether the line is a riding leg at all, however long: the too-long note is for those only. */
export function ridesLine(route: Pick<RouteResponse, "transit">): boolean {
  const plan = transitOf(route);
  if (!plan) return true;
  const index = lineIndex(plan);
  return index < 0 || isRiding(plan.steps[index]);
}

function distanceWords(metres: number | null): TripWords {
  return metres === null ? { shown: "", spoken: "" } : { shown: `, ${formatDistance(metres)}`, spoken: `, ${spokenDistance(metres)}` };
}

/**
 * The walk as the card shows it and as it is said: "Walk to <dock>, 0.2 mi (0.3 km). 5 classic bikes
 * available."; the distance is the plan's, then from the rider's fix as the crow flies once there is one.
 */
export function approachWords(approach: RideApproach, here: LonLat | null): TripWords {
  if (approach.name === null) return same(approach.extra);
  const far = distanceWords(here ? haversineM(here, approach.at) : approach.metres);
  const extra = approach.extra ? ` ${approach.extra}` : "";
  return { shown: `Walk to ${approach.name}${far.shown}.${extra}`, spoken: `Walk to ${approach.name}${far.spoken}.${extra}` };
}

function bikeshareTrip(route: RouteResponse): RideTrip | null {
  const plan = bikeshareOf(route);
  if (!plan) return null;
  const { start, end } = plan;
  const at = route.geometry.coordinates[0] as LonLat | undefined;
  let approach: RideApproach | null = null;
  if (at && plan.walk_start) {
    approach = {
      at,
      name: start.kind === "free_bike" ? "the e-bike parked outside a dock" : start.name,
      metres: plan.walk_start.distance_m,
      extra: start.kind === "dock" && start.availability === "known" ? `${dockCountWords(start, plan.bike, true)}.` : "",
      reached: start.kind === "free_bike" ? "At the e-bike. Take it and ride." : `At ${start.name}. Take a bike and ride.`,
    };
  }
  let finish: TripWords | null = null;
  if (end.kind === "dock") {
    const walk = plan.walk_end;
    const on = (far: string) => (walk ? ` Walk${far} to the finish.` : "");
    finish = {
      shown: `Dock at ${end.name}.${on(walk ? ` ${formatDistance(walk.distance_m)}` : "")}`,
      spoken: `Dock at ${end.name}.${on(walk ? ` ${spokenDistance(walk.distance_m)}` : "")}`,
    };
  }
  return { approach, finish, departure: null, rest: null };
}

function same(text: string): TripWords {
  return { shown: text, spoken: text };
}

function transitTrip(route: RouteResponse, destination: LonLat | null): RideTrip | null {
  const plan = transitOf(route);
  if (!plan) return null;
  const line = lineIndex(plan);
  if (line < 0) return null;
  const steps = plan.steps;
  const lineStep = steps[line];
  const at = route.geometry.coordinates[0] as LonLat | undefined;
  // Before the line: a walk to the first dock (its `take` step), or the steps that lead to a later first ride.
  let approach: RideApproach | null = null;
  const before = steps.slice(0, line);
  if (at && before.length > 0) {
    const take = before.length === 1 && before[0].mode === "take" ? before[0] : null;
    if (take && take.to) {
      const metres = take.coordinates.length >= 2 ? pathLengthM(take.coordinates) : null;
      approach = { at, name: take.to, metres, extra: "", reached: `At ${take.to}. Take a bike and ride.` };
    } else {
      approach = { at, name: null, metres: null, extra: before.map((s) => s.text).join(" "), reached: "At the start of the ride." };
    }
  }
  // At the line's end: the plan's own steps to the first transit after it (dock, walk, into the station,
  // board), or with no transit after it, to the trip's end (a share bike's dock and the walk on).
  const boardAt = steps.findIndex((s, i) => i > line && isTransitStep(s));
  const upTo = boardAt > line ? boardAt : steps.length - 1;
  const dock = lineStep.mode === "bikeshare" && lineStep.to ? `Dock at ${lineStep.to}.` : "";
  const words = [dock, ...steps.slice(line + 1, upTo + 1).map((s) => s.text)].filter(Boolean).join(" ");
  const finish = words ? same(words) : null;
  const departure = plan.departure && plan.departure.step > line ? plan.departure : null;
  // After the transit: the last riding leg, if it is not the line itself.
  let lastTransit = -1;
  steps.forEach((s, i) => {
    if (isTransitStep(s)) lastTransit = i;
  });
  let rest: RideRest | null = null;
  const restAt = lastTransit < 0 ? -1 : steps.findIndex((s, i) => i > lastTransit && isRiding(s));
  const to = destination;
  if (restAt > line && to) {
    const step = steps[restAt];
    const off = steps[lastTransit];
    const alight = off.coordinates.length > 0 ? off.coordinates[off.coordinates.length - 1] : null;
    rest = {
      text: step.text,
      alight,
      alightName: off.to,
      from: step.coordinates[0] ?? alight,
      to,
      preset: step.mode === "bikeshare" ? "bikeshare" : "default",
      metres: step.coordinates.length >= 2 ? pathLengthM(step.coordinates) : null,
    };
  }
  return { approach, finish, departure, rest };
}

/** What comes either side of the line on a Bikeshare or transit plan; null for any other route. */
export function rideTripOf(route: RouteResponse, points: readonly LonLat[]): RideTrip | null {
  return bikeshareTrip(route) ?? transitTrip(route, points.length > 0 ? points[points.length - 1] : null);
}

/** Whether the panel offers Ride the rest: a riding leg after transit, not known to be too long to ride here. */
export function restOffered(trip: RideTrip | null): trip is RideTrip & { rest: RideRest } {
  return !!trip?.rest && (trip.rest.metres === null || trip.rest.metres <= RIDE_MAX_M);
}

/**
 * What a ride on this route follows and re-plans with: a Bikeshare or transit plan's leg is the line
 * itself, from its start to its end, re-planned on a plain ride type (the plan's own would plan the
 * whole trip again: a new dock, or transit); any other route as it was planned.
 */
export function rideLegOf(
  route: RouteResponse,
  points: LonLat[],
  loop: boolean,
): { points: LonLat[]; loop: boolean; preset: PresetId; trip: RideTrip | null } {
  const trip = rideTripOf(route, points);
  const line = route.geometry.coordinates as LonLat[];
  if (!trip || line.length < 2) return { points, loop, preset: route.preset, trip };
  // Bikeshare + transit's share bike is a classic one ("take a classic bike").
  const ebike = bikeshareOf(route)?.bike === "ebike";
  return { points: [line[0], line[line.length - 1]], loop: false, preset: ebike ? "ebike" : "default", trip };
}

/**
 * The walk before the line: whether this fix has reached the line's start (within START_M of it), or
 * is riding the line well along it (a bike taken somewhere else). Poor fixes never end the walk.
 */
export function approachReached(model: Pick<RideModel, "coordinates" | "along">, approach: Pick<RideApproach, "at">, fix: Pick<RideFix, "point" | "accuracyM">): boolean {
  if (fix.accuracyM > POOR_FIX_M) return false;
  if (haversineM(fix.point, approach.at) <= START_M) return true;
  const found = snap(model, fix.point);
  return found !== null && found.offM <= offThreshold(fix.accuracyM) && found.alongM >= WINDOW_AHEAD_M;
}

/**
 * Whether the ride screen offers Ride the rest: near the stop where the transit ends, or, once the first
 * ride is done, past it (nearer the destination than that stop is).
 */
export function restNear(rest: Pick<RideRest, "alight" | "to">, here: LonLat | null, firstRideDone: boolean): boolean {
  if (!here || !rest.alight) return false;
  if (haversineM(here, rest.alight) <= REST_NEAR_M) return true;
  return firstRideDone && haversineM(here, rest.to) < haversineM(rest.alight, rest.to);
}

/** Ride the rest's request: from where the rider is (else the leg's own start) to the destination. */
export function restRequest(rest: RideRest, here: LonLat | null): { points: LonLat[]; preset: PresetId } | null {
  const from = here ?? rest.from;
  return from ? { points: [from, rest.to], preset: rest.preset } : null;
}

/** The end of the line said as the plan's finish (the dock, the boarding), in place of the plain arrival. */
export function withFinish(events: RideEvent[], finish: TripWords | null): RideEvent[] {
  return finish ? events.map((e) => (e.cue?.kind === "end" ? { ...e, spoken: finish.spoken } : e)) : events;
}
