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
 * In a browser, rides longer than RIDE_MAX_M go to a bike computer: the rule is the riding leg's. The
 * phone app, which rides with the screen locked, has no limit (`rideMaxM`).
 */
import { askOf, type NextVehicleAsk } from "./nextVehicle.ts";
import type { RouteResponse, TransitDeparture, TransitPlan, TransitStep } from "./api.ts";
import { bikeshareOf, dockCountWords } from "./bikeshare.ts";
import { formatDistance, spokenDistance } from "./format.ts";
import { haversineM, pathLengthM, type LonLat } from "./geo.ts";
import { POOR_FIX_M, RIDE_MAX_M, START_M, WINDOW_AHEAD_M, offThreshold, snap, startState, step, type RideEvent, type RideFix, type RideModel, type RideState, type Verbosity } from "./navigate.ts";
import type { PresetId } from "./presets.ts";
import { ridesHidden } from "./nativeShell.ts";
import { drawOf, transitOf } from "./transit.ts";
import { t } from "./i18n.ts";

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
  /** With no dock to name (steps before a later first ride): the first step alone, said at the start. */
  first: string;
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
  /** The Metro or Metrobus boarding the finish leads to: where its next train or bus is, while waiting (lib/nextVehicle.ts). */
  boarding?: NextVehicleAsk | null;
  rest: RideRest | null;
  /** The line is ridden on a share bike (Ride mode's dock button and undocked time, lib/rideDock.ts). */
  shareBike?: boolean;
  /** The route is ridden as it was planned, its walks only at the ends (`walk_in`), not a leg of a bigger trip. */
  asPlanned?: boolean;
}

export const RIDE_REST = t("Ride the rest");
// A phone pocketed for longer than RideMode's HIDDEN_STOP_MS (on the train, say) stops the ride's watch: the
// ride screen then offers Resume, and Ride the rest shows again with the next fix (the trip panel's works too).
export const RIDE_REST_HINT = t("Turn-by-turn from where you are to your destination, for the ride after transit.");
export const RIDE_REST_FINDING = t("Finding the ride to your destination…");
/** Said once on the ride screen when the button shows (near or past the stop where the transit ends). */
export function restReadySaid(rest: Pick<RideRest, "alightName">): string {
  return `${rest.alightName ? `Near ${rest.alightName}. ` : ""}${RIDE_REST} plans the ride to your destination.`;
}
/** Ride the rest pressed again within this, after closures were said, rides it anyway. */
export const REST_ANYWAY_MS = 60_000;
/** Closures on the rest's line, said on the ride screen (its dialog is in the hidden panel). */
export function restClosedSaid(names: readonly string[]): string {
  return `Closed on the way: ${[...new Set(names)].join(", ")}. Press ${RIDE_REST} again to ride anyway.`;
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

/** The longest ride Start ride is offered for: RIDE_MAX_M in a browser, none in the phone app (screen locked is fine). */
export function rideMaxM(hidden: boolean = ridesHidden()): number {
  return hidden ? Infinity : RIDE_MAX_M;
}

/**
 * Whether Start ride is offered: the line is a riding leg no longer than `rideMaxM`. A Bikeshare plan's
 * line is its ride between the docks; a transit plan's is its first ride (not a walk).
 */
export function rideable(route: Pick<RouteResponse, "distance_m" | "transit">, maxM: number = rideMaxM()): boolean {
  if (route.distance_m > maxM) return false;
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
  return index < 0 ? plan.direct && plan.mode === "bike-transit" : isRiding(plan.steps[index]);
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

/** What is said as the walk starts: the walk to the dock, or only the first of the steps before the line (Where am I? says them all). */
export function approachStartSaid(approach: RideApproach): string {
  return approach.name === null ? approach.first : approachWords(approach, null).spoken;
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
      first: "",
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
  return { approach, finish, departure: null, rest: null, shareBike: true };
}

/**
 * A boarding step without its "you arrive 7:38 am, 4 min spare" clause: true when planned, stale by the
 * time the ride gets there (DepartureTimer counts down the time left instead).
 */
export function withoutSpare(text: string): string {
  return text.replace(/: you arrive [^;]*; (\w)/, (_, first: string) => `. ${first.toUpperCase()}`);
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
      approach = { at, name: take.to, metres, extra: "", first: "", reached: `At ${take.to}. Take a bike and ride.` };
    } else {
      const extra = before.map((s) => s.text).join(" ");
      approach = { at, name: null, metres: null, extra, first: before[0].text, reached: "At the start of the ride." };
    }
  }
  // At the line's end: the plan's own steps to the first transit after it (dock, walk, into the station,
  // board), or with no transit after it, to the trip's end (a share bike's dock and the walk on).
  const boardAt = steps.findIndex((s, i) => i > line && isTransitStep(s));
  const upTo = boardAt > line ? boardAt : steps.length - 1;
  const dock = lineStep.mode === "bikeshare" && lineStep.to ? `Dock at ${lineStep.to}.` : "";
  const words = [dock, ...steps.slice(line + 1, upTo + 1).map((s) => withoutSpare(s.text))].filter(Boolean).join(" ");
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
  const boarding = boardAt > line ? askOf(steps[boardAt]) : null;
  return { approach, finish, departure, boarding, rest, shareBike: lineStep.mode === "bikeshare" };
}

/** A plain ride whose ride stops short of its start or end (the API's `walk_in`): the walk to the line first, and the walk on at the finish. */
function walkInTrip(route: RouteResponse): RideTrip | null {
  const walks = route.walk_in;
  if (!walks || (!walks.start && !walks.end)) return null;
  const at = route.geometry.coordinates[0] as LonLat | undefined;
  const approach: RideApproach | null =
    at && walks.start
      ? { at, name: "the start of the ride", metres: walks.start.distance_m, extra: "", first: "", reached: "At the start of the ride. Ride on." }
      : null;
  const finish: TripWords | null = walks.end
    ? {
        shown: `The ride ends here. Walk your bike ${formatDistance(walks.end.distance_m)} to your destination.`,
        spoken: `The ride ends here. Walk your bike ${spokenDistance(walks.end.distance_m)} to your destination.`,
      }
    : null;
  return { approach, finish, departure: null, rest: null, asPlanned: true };
}

/** What comes either side of the line on a Bikeshare or transit plan, or a plain ride's walk-in; null for any other route. */
export function rideTripOf(route: RouteResponse, points: readonly LonLat[]): RideTrip | null {
  return bikeshareTrip(route) ?? transitTrip(route, points.length > 0 ? points[points.length - 1] : null) ?? walkInTrip(route);
}

/** Whether the panel offers Ride the rest: a riding leg after transit, not known to be too long to ride here. */
export function restOffered(trip: RideTrip | null, maxM: number = rideMaxM()): trip is RideTrip & { rest: RideRest } {
  return !!trip?.rest && (trip.rest.metres === null || trip.rest.metres <= maxM);
}

/**
 * Whether a ride keeps to its line, never re-planned on its own: a link shared as a ride, opened unchanged
 * (`opened`), or a Mass Ride or Group Ride unless shared as a route. A Bikeshare or transit leg, or Ride the
 * rest (`rest`), re-plans as before; a route with walks at its ends (`walk_in`, asPlanned) is still the route.
 */
export function fixedRide(
  leg: { preset: PresetId; trip: RideTrip | null },
  opened: { ride?: boolean; own?: boolean } | null,
  rest: boolean,
): boolean {
  if (rest || (leg.trip && !leg.trip.asPlanned)) return false;
  return opened ? !!opened.ride && !opened.own : leg.preset === "mass-ride" || leg.preset === "group-ride";
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
  if (!trip || trip.asPlanned || line.length < 2) return { points, loop, preset: route.preset, trip };
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
  // The dock skipped (a bike taken at another dock, or GPS that never came within START_M of it): on the
  // line at least WINDOW_AHEAD_M along it, the walk is over and the cues take up from there, the ones
  // already passed dropped (navigate.ts step). Nearer the start, a walk beside the line stays a walk.
  const found = snap(model, fix.point);
  return found !== null && found.offM <= offThreshold(fix.accuracyM) && found.alongM >= WINDOW_AHEAD_M;
}

/** How old the last good fix may be for Ride the rest to start from it; older, the leg's own start is used. */
export const REST_FIX_MAX_AGE_MS = 60_000;

/**
 * Ride mode's own state around the line's (navigate.ts RideState): whether the rider is still walking to
 * the dock, whether the walk has been said, and the last good fix, kept after arrival too (the line's
 * state stops taking fixes once arrived), for Ride the rest.
 */
export interface TripRide {
  ride: RideState;
  walking: boolean;
  walkSaid: boolean;
  lastGood: { point: LonLat; at: number } | null;
}

export function tripRideStart(trip: RideTrip | null, ride: RideState = startState()): TripRide {
  return { ride, walking: !!trip?.approach, walkSaid: false, lastGood: null };
}

/**
 * One fix into a ride, on a trip or not: while walking to the dock, the marker moves and nothing is taken
 * as off route (the walk said at the first good fix, unless that fix is already at the dock); at the dock,
 * the line's own step (navigate.ts) takes over, its arrival said as the plan's finish. `notes` are said
 * politely, as Ride mode's notes are.
 */
export function tripStep(
  model: RideModel,
  trip: RideTrip | null,
  s: TripRide,
  fix: RideFix,
  level: Verbosity,
  replan = true,
): { state: TripRide; events: RideEvent[]; notes: string[] } {
  const good = fix.accuracyM <= POOR_FIX_M;
  const lastGood = good ? { point: fix.point, at: fix.at } : s.lastGood;
  const notes: string[] = [];
  const approach = trip?.approach ?? null;
  let walkSaid = s.walkSaid;
  if (s.walking && approach) {
    if (!approachReached(model, approach, fix)) {
      if (good && !walkSaid) {
        notes.push(approachStartSaid(approach));
        walkSaid = true;
      }
      const ride = { ...s.ride, fix, goodFix: good ? fix : s.ride.goodFix };
      return { state: { ride, walking: true, walkSaid, lastGood }, events: [], notes };
    }
    notes.push(approach.reached);
  }
  const out = step(model, s.ride, fix, level, replan);
  return { state: { ride: out.state, walking: false, walkSaid, lastGood }, events: withFinish(out.events, trip?.finish ?? null), notes };
}

/** Where Ride the rest starts: the last good fix while under REST_FIX_MAX_AGE_MS old, else null (the leg's start). */
export function restFrom(lastGood: TripRide["lastGood"], now: number): LonLat | null {
  return lastGood && now - lastGood.at < REST_FIX_MAX_AGE_MS ? lastGood.point : null;
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

/**
 * The end of the line said as the plan's finish (the dock, the boarding), in place of the plain arrival. Only the
 * arrival: the early "The destination is across ..." (D26), said for the same end cue at "advance", stays as it is.
 */
export function withFinish(events: RideEvent[], finish: TripWords | null): RideEvent[] {
  return finish
    ? events.map((e) => (e.cue?.kind === "end" && e.phase === "arrive" ? { ...e, spoken: finish.spoken } : e))
    : events;
}
