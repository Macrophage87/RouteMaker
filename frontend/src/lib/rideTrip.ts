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
import type { RouteResponse, TransitDeparture, TransitOption, TransitPlan, TransitStep, WalkTurn } from "./api.ts";
import { bikeshareOf, dockCountWords } from "./bikeshare.ts";
import { formatDistance, spokenDistance } from "./format.ts";
import { haversineM, pathLengthM, type LonLat } from "./geo.ts";
import { POOR_FIX_M, RIDE_MAX_M, START_M, WINDOW_AHEAD_M, offThreshold, snap, startState, step, type RideEvent, type RideFix, type RideModel, type RideState, type Verbosity } from "./navigate.ts";
import { isTransit, onFoot, usesBikeshare, type PresetId } from "./presets.ts";
import { isBike, type Bike, type Dials } from "./dials.ts";
import { ridesHidden } from "./nativeShell.ts";
import { pointAlong } from "./lightTimes.ts";
import { drawOf, transitOf } from "./transit.ts";
import { serverWordsIn, t } from "./i18n.ts";
import { sourceWord, wallClockOf } from "./departure.ts";
import { onwardOf, walkPart, type OnwardPart } from "./onward.ts";
import { walkModel, walkStart, walkStep } from "./walkCues.ts";

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
  /** The walk to it as a line with its turns (lib/walkCues.ts), where the plan routed it: said turn by turn. */
  walk?: RideModel | null;
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
  /** A Rebalance Ride whose drop-off was chosen at its crowded dock (lib/rebalanceDock.ts): that dock's name. */
  docked?: string | null;
  finish: TripWords | null;
  /** The departure the finish leads to (DepartureTimer), where the plan has one. */
  departure: TransitDeparture | null;
  /** The Metro or Metrobus boarding the finish leads to: where its next train or bus is, while waiting (lib/nextVehicle.ts). */
  boarding?: NextVehicleAsk | null;
  /**
   * On the boarding card, the share bike's dock before the train ("Dock at X."); the way into the station is not shown
   * (Stephen, 2026-11-03: "Not all stations require an elevator, some you can just walk through").
   */
  boardingNote?: string | null;
  /** The plan's step of the first train or bus after the line, by its place; null with none (the departure is its own where `step` matches). */
  boardStep?: number | null;
  rest: RideRest | null;
  /** The line is ridden on a share bike (Ride mode's dock button and undocked time, lib/rideDock.ts). */
  shareBike?: boolean;
  /** The route is ridden as it was planned, its walks only at the ends (`walk_in`), not a leg of a bigger trip. */
  asPlanned?: boolean;
  /**
   * What follows the line, followed on the ride screen once it ends (lib/onward.ts): walks turn by turn and transit
   * stop by stop (Stephen, 2026-11-02), up to a riding leg after the transit (Ride the rest's).
   */
  onward?: OnwardPart[];
  /**
   * Walk and Walk + 🚆🚌 (Stephen, 2026-11-02): the line itself is a walk, followed turn by turn on foot by its turns
   * (lib/walkCues.ts), never off route nor re-planned (a walker crosses where they like).
   */
  onFoot?: { turns: readonly WalkTurn[] };
}

export const RIDE_REST = t("Ride the rest");
// A phone pocketed for longer than RideMode's HIDDEN_STOP_MS (on the train, say) stops the ride's watch: the
// ride screen then offers Resume, and Ride the rest shows again with the next fix (the trip panel's works too).
export const RIDE_REST_HINT = t("Turn-by-turn from where you are to your destination, for the ride after transit.");
export const RIDE_REST_FINDING = t("Finding the ride to your destination…");
/** Said once on the ride screen when the button shows (near or past the stop where the transit ends). */
// These words are built when they are said, not when the module loads (routing audit D30), so they follow the
// language in force (lib/i18n.ts): Spanish riders hear the walk, dock and hand-off lines in Spanish.
export function restReadySaid(rest: Pick<RideRest, "alightName">): string {
  const near = rest.alightName ? `${t("Near {place}.", { place: rest.alightName })} ` : "";
  return `${near}${t("{button} plans the ride to your destination.", { button: t("Ride the rest") })}`;
}
/** Ride the rest pressed again within this, after closures were said, rides it anyway. */
export const REST_ANYWAY_MS = 60_000;
/** Closures on the rest's line, said on the ride screen (its dialog is in the hidden panel). */
export function restClosedSaid(names: readonly string[]): string {
  return t("Closed on the way: {names}. Press {button} again to ride anyway.", { names: [...new Set(names)].join(", "), button: t("Ride the rest") });
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
 * Walk, Walk + 🚆🚌 and Run (2026-11-02): the line is a walk (a run), the trip's first, followed on foot. So is a
 * Bikeshare + 🚶🚆🚌 option that takes no bike.
 */
export function walksLine(route: Pick<RouteResponse, "transit">): boolean {
  const plan = transitOf(route);
  // Bikeshare + 🚶🚆🚌's option with no bike (walk, train, walk) is walked as Walk + 🚆🚌's is (Stephen, 2026-11-03:
  // "When you do bikeshare + transit, it doesn't even give an option to start").
  if (!plan || (plan.mode !== "walk" && plan.mode !== "walk-transit" && plan.mode !== "run" && plan.mode !== "bikeshare-transit")) return false;
  const index = lineIndex(plan);
  return index >= 0 && plan.steps[index].mode === "walk";
}

/** The turns of a Walk line (`walksLine`), from the route's own plan; null on any other route. */
export function walkLineTurns(route: Pick<RouteResponse, "transit">): readonly WalkTurn[] | null {
  if (!walksLine(route)) return null;
  const plan = transitOf(route)!;
  return plan.steps[lineIndex(plan)].turns ?? [];
}

/**
 * Whether Start ride is offered: the line is a riding leg no longer than `rideMaxM`. A Bikeshare plan's
 * line is its ride between the docks; a transit plan's is its first ride (not a walk). Walk and Walk + 🚆🚌's line is
 * its first walk, walked turn by turn.
 */
export function rideable(route: Pick<RouteResponse, "distance_m" | "transit">, maxM: number = rideMaxM()): boolean {
  if (route.distance_m > maxM) return false;
  if (walksLine(route)) return true;
  const plan = transitOf(route);
  if (!plan) return true;
  const index = lineIndex(plan);
  return index < 0 ? plan.direct && plan.mode === "bike-transit" : isRiding(plan.steps[index]);
}

/** Whether the line is a riding leg at all, however long: the too-long note is for those only. */
export function ridesLine(route: Pick<RouteResponse, "transit">): boolean {
  if (walksLine(route)) return true;
  const plan = transitOf(route);
  if (!plan) return true;
  const index = lineIndex(plan);
  return index < 0 ? plan.direct && plan.mode === "bike-transit" : isRiding(plan.steps[index]);
}

/** Whether a transit option rides a bike at all: the whole way, or a leg on your own bike or a share bike. */
export function optionRides(option: Pick<TransitOption, "direct" | "walk" | "legs">): boolean {
  if (option.walk) return false;
  if (option.direct) return true;
  return (option.legs ?? []).some((leg) => leg.mode === "ride" || leg.mode === "bikeshare");
}

/**
 * The line in Start's place on a transit option with no ride (Bikeshare + 🚶🚆🚌 can pick a walk and a train): "No
 * bike on this option. Pick D to ride.", naming the first option that rides (P10; it showed "0.1 mi ridden" and a
 * stress bar 100% not rated). Null where the option rides, or on a route that is not a transit trip.
 */
export function noBikeLine(route: Pick<RouteResponse, "transit">): string | null {
  const plan = transitOf(route);
  // Walk and Walk + 🚆🚌 take no bike, by choice: nothing to say.
  if (!plan || ridesLine(route) || plan.mode === "walk" || plan.mode === "walk-transit" || plan.mode === "run") return null;
  const index = plan.options.findIndex(optionRides);
  return index < 0 ? t("No bike on this option.") : t("No bike on this option. Pick {letter} to ride.", { letter: String.fromCharCode(65 + index) });
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
  return {
    shown: `${t("Walk to {place}{distance}.", { place: approach.name, distance: far.shown })}${extra}`,
    spoken: `${t("Walk to {place}{distance}.", { place: approach.name, distance: far.spoken })}${extra}`,
  };
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
      name: start.kind === "free_bike" ? t("the e-bike parked outside a dock") : start.name,
      metres: plan.walk_start.distance_m,
      extra: start.kind === "dock" && start.availability === "known" ? `${dockCountWords(start, plan.bike, true)}.` : "",
      first: "",
      reached: start.kind === "free_bike" ? t("At the e-bike. Take it and ride.") : t("At {place}. Take a bike and ride.", { place: start.name }),
      walk: walkModel({ coordinates: plan.walk_start.geometry.coordinates, turns: plan.walk_start.turns ?? [], to: start.name }),
    };
  }
  let finish: TripWords | null = null;
  if (end.kind === "dock") {
    const walk = plan.walk_end;
    const on = (far: string) => (walk ? ` ${t("Walk {distance} to the finish.", { distance: far })}` : "");
    const dock = t("Dock at {place}.", { place: end.name });
    finish = {
      shown: `${dock}${on(walk ? formatDistance(walk.distance_m) : "")}`,
      spoken: `${dock}${on(walk ? spokenDistance(walk.distance_m) : "")}`,
    };
  }
  const after = plan.walk_end ? walkPart({ coordinates: plan.walk_end.geometry.coordinates, turns: plan.walk_end.turns ?? [], to: null }, plan.walk_end.duration_s) : null;
  return { approach, finish, departure: null, rest: null, shareBike: true, onward: after ? [after] : [] };
}

/**
 * A boarding step without its "you arrive 7:38 am, 4 min spare" clause: true when planned, stale by the
 * time the ride gets there (DepartureTimer counts down the time left instead).
 */
export function withoutSpare(text: string): string {
  // The API writes the clause in the request's language (src/core/transit.py Leg.words): ": llegada " in Spanish.
  return text.replace(/: (?:you arrive|llegada) [^;]*; (\w)/, (_, first: string) => `. ${first.toUpperCase()}`);
}

/**
 * A plan step's sentence as the ride screen shows and says it: the API's own where it words the language in force
 * (English, Spanish: lib/i18n.ts serverWordsIn), else worded here from the step's fields in the language in force, so
 * the hand-off from the bike to the train is not English in the other 19.
 */
export function stepText(step: TransitStep): string {
  if (serverWordsIn()) return step.text;
  const m = Math.max(1, Math.round(step.seconds / 60));
  const lift = /\bby the elevator\b/.test(step.text);
  switch (step.mode) {
    case "walk":
      return step.to ? t("Walk {m} min to {place}.", { m, place: step.to }) : t("Walk {m} min.", { m });
    case "take":
      return t("Walk {m} min to the bikeshare dock at {place} and take a classic bike.", { m, place: step.to ?? "" });
    case "bikeshare":
      return t("Ride the bikeshare bike {m} min and dock it at {place}.", { m, place: step.to ?? "" });
    case "ride":
      return step.to ? t("Ride {m} min to {place}.", { m, place: step.to }) : t("Ride {m} min.", { m });
    case "enter":
      return lift ? t("About {m} min into the station by the elevator.", { m }) : t("About {m} min into the station.", { m });
    case "exit":
      return lift ? t("About {m} min out of the station by the elevator.", { m }) : t("About {m} min out of the station.", { m });
    default: {
      const line = step.lines.length > 0 ? step.lines.join(" / ") : (step.system ?? "");
      const stops = step.stops ?? [];
      const off = stops.length > 0 ? stops[stops.length - 1].name : (step.to ?? "").replace(/^the stop at /, "") || null;
      const board = step.toward && step.toward !== off ? t("Board {line} toward {place}.", { line, place: step.toward }) : t("Board {line}.", { line });
      const words = [
        step.mode === "bus" && step.with_bike ? t("Put your bike on the bus's front rack.") : "",
        board,
        step.departs ? t("Departs {time}.", { time: `${wallClockOf(step.departs)} ${sourceWord(step)}` }) : "",
        off ? t("About {m} min on board to {place}.", { m, place: off }) : t("About {m} min on board.", { m }),
      ];
      return words.filter(Boolean).join(" ");
    }
  }
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
      approach = { at, name: take.to, metres, extra: "", first: "", reached: t("At {place}. Take a bike and ride.", { place: take.to }), walk: walkOf(take) };
    } else {
      const extra = before.map(stepText).join(" ");
      // A first walk is said turn by turn; the station and the transit after it are said as before.
      const walk = before[0].mode === "walk" || before[0].mode === "take" ? walkOf(before[0]) : null;
      approach = { at, name: null, metres: null, extra, first: stepText(before[0]), reached: t("At the start of the ride."), walk };
    }
  }
  // At the line's end: the plan's own steps to the first transit after it (dock, walk, into the station,
  // board), or with no transit after it, to the trip's end (a share bike's dock and the walk on).
  const boardAt = steps.findIndex((s, i) => i > line && isTransitStep(s));
  const upTo = boardAt > line ? boardAt : steps.length - 1;
  const dock = lineStep.mode === "bikeshare" && lineStep.to ? t("Dock at {place}.", { place: lineStep.to }) : "";
  const words = [dock, ...steps.slice(line + 1, upTo + 1).map((s) => withoutSpare(stepText(s)))].filter(Boolean).join(" ");
  const finish = words ? same(words) : null;
  const departure = plan.departure && plan.departure.step > line ? plan.departure : null;
  // After the transit: the next riding leg after it (where the followed walks and train end, lib/onward.ts), if it is
  // not the line itself. Where more transit follows that leg (a ride between Metro and MARC), the rest is the trip
  // again from where the rider is, on the plan's own ride type: its line is that ride, and the train after it is
  // followed in turn (Stephen, 2026-11-03: "It should start the transit phase", "It should let you switch between modes").
  const firstTransit = steps.findIndex((s, i) => i > line && isTransitStep(s));
  let rest: RideRest | null = null;
  const restAt = firstTransit < 0 ? -1 : steps.findIndex((s, i) => i > firstTransit && isRiding(s));
  const to = destination;
  if (restAt > line && to) {
    const step = steps[restAt];
    let offAt = firstTransit;
    steps.forEach((s, i) => {
      if (i < restAt && isTransitStep(s)) offAt = i;
    });
    const off = steps[offAt];
    const alight = off.coordinates.length > 0 ? off.coordinates[off.coordinates.length - 1] : null;
    const moreTransit = steps.some((s, i) => i > restAt && isTransitStep(s));
    rest = {
      text: stepText(step),
      alight,
      alightName: off.to,
      from: step.coordinates[0] ?? alight,
      to,
      preset: moreTransit ? (plan.mode as PresetId) : step.mode === "bikeshare" ? "bikeshare" : "default",
      // The trip again is its own transit plan: only its line is ridden, whatever the length to the destination.
      metres: moreTransit ? null : step.coordinates.length >= 2 ? pathLengthM(step.coordinates) : null,
    };
  }
  const boarding = boardAt > line ? askOf(steps[boardAt]) : null;
  const onFoot = walksLine(route) ? { turns: lineStep.turns ?? [] } : undefined;
  return { approach, finish, departure, boarding, boardStep: boardAt > line ? boardAt : null, boardingNote: boardAt > line && dock ? dock : null, rest, shareBike: lineStep.mode === "bikeshare", onward: onwardOf(steps, line), ...(onFoot ? { onFoot } : {}) };
}

/** A walk step as a line with its turns, where it was routed. */
function walkOf(step: TransitStep): RideModel | null {
  return walkModel({ coordinates: step.coordinates, turns: step.turns ?? [], to: step.to });
}

/** A plain ride whose ride stops short of its start or end (the API's `walk_in`): the walk to the line first, and the walk on at the finish. */
function walkInTrip(route: RouteResponse): RideTrip | null {
  const walks = route.walk_in;
  if (!walks || (!walks.start && !walks.end)) return null;
  const at = route.geometry.coordinates[0] as LonLat | undefined;
  const approach: RideApproach | null =
    at && walks.start
      ? {
          at,
          name: t("the start of the ride"),
          metres: walks.start.distance_m,
          extra: "",
          first: "",
          reached: t("At the start of the ride. Ride on."),
          walk: walkModel({ coordinates: walks.start.geometry.coordinates, turns: walks.start.turns ?? [], to: null }),
        }
      : null;
  const finish: TripWords | null = walks.end
    ? {
        shown: t("The ride ends here. Walk your bike {distance} to your destination.", { distance: formatDistance(walks.end.distance_m) }),
        spoken: t("The ride ends here. Walk your bike {distance} to your destination.", { distance: spokenDistance(walks.end.distance_m) }),
      }
    : null;
  const after = walks.end ? walkPart({ coordinates: walks.end.geometry.coordinates, turns: walks.end.turns ?? [], to: null }, walks.end.duration_s) : null;
  return { approach, finish, departure: null, rest: null, asPlanned: true, onward: after ? [after] : [] };
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
  // On foot (Walk, Walk + 🚆🚌): the walk is followed as planned, never re-planned on a bike's ride type.
  if (leg.trip?.onFoot) return true;
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
  // A run (2026-11-02) re-plans and saves as it was planned: its stops and its loop, at the runner's pace. A loop
  // from the start alone keeps its shape as stops a third and two thirds along it, so a re-plan still goes round.
  if (route.preset === "run") return { points: points.length === 1 && loop ? runLoopStops(line) : points, loop, preset: "run", trip };
  // On foot: a re-plan the rider asks for (Detour, Road closed, Re-plan from here) walks, to the walk's own end.
  if (trip.onFoot) return { points: [line[0], line[line.length - 1]], loop: false, preset: "walk", trip };
  // Bikeshare + transit's share bike is a classic one ("take a classic bike").
  const ebike = bikeshareOf(route)?.bike === "ebike";
  return { points: [line[0], line[line.length - 1]], loop: false, preset: ebike ? "ebike" : "default", trip };
}

/**
 * A share bike's own pace and weight (core.presets BIKESHARE_BIKES): a heavy three-speed ridden without hurry at 13 km/h
 * (8 mph), the e-bike at 20 km/h (12 mph). A leg re-planned on a plain ride type (`rideLegOf`) sends them as the rider's
 * riding speed and system weight, so the share bike is still timed and weighed as itself.
 */
export const SHARE_BIKE: Readonly<Record<Bike, { speedKmh: number; weightKg: number }>> = {
  classic: { speedKmh: 13, weightKg: 100 },
  ebike: { speedKmh: 20, weightKg: 108 },
};

/**
 * The share bike a ride's leg is on, or null on the rider's own bike: the plan's `bike` dial (Bikeshare, Rebalance
 * Ride), else the plan's bikeshare answer's, else Bikeshare + transit's classic bike ("take a classic bike").
 */
export function shareBikeOf(route: Pick<RouteResponse, "preset" | "bikeshare" | "transit">, dials: Pick<Dials, "bike">): Bike | null {
  if (isBike(dials.bike)) return dials.bike;
  const planned = bikeshareOf(route)?.bike;
  if (isBike(planned)) return planned;
  return route.preset === "bikeshare-transit" || route.transit?.mode === "bikeshare-transit" ? "classic" : null;
}

/**
 * The dials a ride's own request (a re-plan, a detour, the way to the start, Ride the rest) sends on the leg's ride type
 * (`rideLegOf`), which is a plain one for a Bikeshare or transit plan's leg. The plan's fields that the API takes on its
 * own ride types alone are left out, as Roam's detour leaves them out (App.tsx roamDetour): `bike`, `ending` and the
 * stations on Bikeshare and Rebalance Ride only, `novice_legs` on the transit ride types with a bike only,
 * `transit_option` on the transit ride types only (core/api.py RouteIn). The hunt (2026-11-08, R3): every re-route of a
 * share-bike ride came back 422, as did a transit ride's after the Novice offer was taken. A share bike ridden on a plain
 * ride type keeps its own pace and weight (`SHARE_BIKE`), which the API takes on any riding ride type as the rider's
 * riding speed and system weight; its stress and hills are the plan's dials already. Its stress-averse exposure and its
 * heavy-bike gate and surface costs are the Bikeshare ride type's own, which no request field carries, so the plain
 * ride type's are used.
 */
export function legDials(dials: Dials, preset: PresetId, shareBike: Bike | null = null): Dials {
  const share = usesBikeshare(preset);
  const transit = isTransit(preset);
  const novice = preset === "bike-transit" || preset === "bikeshare-transit";
  const out: Dials = { ...dials };
  if (!share) {
    out.bike = undefined;
    out.ending = undefined;
    out.pickupStation = undefined;
    out.dropoffStation = undefined;
  }
  if (!novice) {
    out.noviceLegs = undefined;
    out.noviceHop = undefined;
  }
  if (!transit) out.transitOption = undefined;
  if (shareBike && !share && !transit && !onFoot(preset) && preset !== "run") {
    out.ridingSpeedKmh = SHARE_BIKE[shareBike].speedKmh;
    out.systemWeightKg = SHARE_BIKE[shareBike].weightKg;
  }
  return out;
}

/** How far into a dirt trail stretch of the route the rider is placed on the line before the trail counts as ridden. */
export const DIRT_RIDDEN_M = 30;

/**
 * Whether the rider has now ridden a dirt trail (the owner, 2026-10-21: "If someone goes onto a dirt trail, any
 * reroutes should include dirt"): the rider's place on the line moved from `fromM` to `toM` (line metres; null before
 * the first) and reached DIRT_RIDDEN_M (or half the stretch, on a shorter one) into a stretch of `route` on a
 * mountain-bike trail (`trail_levels`), on a route that rides a dirt trail its ride type skips (`dirt_trails`). The
 * trail stretches are in traced metres, scaled to the line by the spans' own end as the map scales them
 * (routeTrailLayers.ts). The route's `dirt_trails` alone is not enough (the hunt, 2026-11-08, V5): a plan with a stop
 * on a trail, or a re-plan that rides one, had opened every dirt trail to the rest of the ride before the rider rode
 * any. Off the line, nothing is ridden.
 */
export function rodeDirt(
  route: Pick<RouteResponse, "dirt_trails" | "distance_m"> & Partial<Pick<RouteResponse, "trail_levels" | "stress_spans">>,
  lineM: number,
  fromM: number | null,
  toM: number | null,
): boolean {
  if (!route.dirt_trails || toM === null || !(lineM > 0)) return false;
  const spans = route.stress_spans ?? [];
  const traced = spans.length ? spans[spans.length - 1].to_m : route.distance_m;
  if (!(traced > 0)) return false;
  const scale = lineM / traced;
  const low = Math.min(fromM ?? toM, toM);
  const high = Math.max(fromM ?? toM, toM);
  return (route.trail_levels ?? []).some((trail) => {
    const from = trail.from_m * scale;
    const to = trail.to_m * scale;
    const into = from + Math.min(DIRT_RIDDEN_M, (to - from) / 2);
    return to > from && high >= into && low <= to;
  });
}

/** A run loop from its start alone, as that start and the points a third and two thirds along the loop. */
export function runLoopStops(line: readonly LonLat[]): LonLat[] {
  const length = pathLengthM(line);
  const stops = [1 / 3, 2 / 3].map((share) => pointAlong(line, length * share)).filter((p): p is LonLat => p !== null);
  return [line[0], ...stops];
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
  /** The walk to the line's start, turn by turn (the approach's `walk`): where on it the rider is. */
  walk?: RideState | null;
}

export function tripRideStart(trip: RideTrip | null, ride: RideState = startState()): TripRide {
  return { ride, walking: !!trip?.approach, walkSaid: false, lastGood: null, walk: trip?.approach?.walk ? walkStart() : null };
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
      // The walk's turns, said as a ride's are (lib/walkCues.ts), where the plan routed it.
      const walked = approach.walk ? walkStep(approach.walk, s.walk ?? walkStart(), fix, level) : null;
      return { state: { ride, walking: true, walkSaid, lastGood, walk: walked?.state ?? s.walk ?? null }, events: walked?.events ?? [], notes };
    }
    notes.push(approach.reached);
  }
  if (trip?.onFoot) {
    // On foot the line is never off route nor re-planned (lib/walkCues.ts walkStep's rule); its end is the trip's.
    const out = step(model, s.ride, fix, level, false);
    const ride = out.state.off ? { ...out.state, off: false, offSince: null, offCount: 0 } : out.state;
    const events = out.events.filter((e) => e.kind !== "off-route" && e.kind !== "back-on-route");
    return { state: { ride, walking: false, walkSaid, lastGood, walk: s.walk ?? null }, events: withFinish(events, trip.finish), notes };
  }
  const out = step(model, s.ride, fix, level, replan);
  return { state: { ride: out.state, walking: false, walkSaid, lastGood, walk: s.walk ?? null }, events: withFinish(out.events, trip?.finish ?? null), notes };
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

/**
 * Whether Ride the rest may start by itself once the train is behind the rider: a fresh fix (REST_FIX_MAX_AGE_MS) at
 * the stop where the transit ends, or past it. The parts after the line can end on the timetable's clock alone,
 * under ground or on a late train, and a ride started then would be planned for a rider still on board.
 */
export function restAutoReady(rest: Pick<RideRest, "alight" | "to">, fix: { point: LonLat; at: number } | null, now: number): boolean {
  return !!fix && now - fix.at < REST_FIX_MAX_AGE_MS && restNear(rest, fix.point, true);
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
