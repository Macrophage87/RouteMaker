/**
 * Go's Bikeshare options (the owner, 2026-10-11: "select a destination. It will find the destination then offer
 * the options for routing to it with stations", "only if youre in bikeshare mode"; and 21:04: the options
 * lettered, on the map and by key).
 *
 * A Bikeshare answer lists up to three pick-up and drop-off pairs (`bikeshare.options`, #94), the first being
 * the plan routed. Go shows them as buttons lettered A, B, C, each named by the option's own `text`; a press
 * re-plans that pair (its stations and ending). A re-plan's answer lists only the pair asked for, so the first
 * answer's list is kept for the same start and end. The ranking is the server's, unchanged.
 */
import type { BikeshareOption, BikesharePlan } from "./api.ts";
import type { LonLat } from "./geo.ts";
import type { Pins } from "./stations.ts";

/** The options kept for one trip: its start and end (`key`). */
export interface KeptOptions {
  key: string;
  options: BikeshareOption[];
}

/** The trip a list belongs to: the plan's start and end. */
export function optionsKey(points: readonly LonLat[]): string {
  if (points.length < 2) return "";
  const a = points[0];
  const b = points[points.length - 1];
  return `${a[0]},${a[1]}>${b[0]},${b[1]}`;
}

/**
 * The list to show after an answer: a full list (two or more) is the answer's own, fresh; an answer of one
 * pair (a re-plan of one option, or another ride type's none) keeps the list kept for the same trip.
 */
export function keepOptions(kept: KeptOptions | null, plan: BikesharePlan | null, key: string): KeptOptions | null {
  const fresh = plan?.options ?? [];
  if (!key) return null;
  if (fresh.length > 1) return { key, options: fresh };
  if (kept && kept.key === key) return kept;
  return fresh.length > 0 ? { key, options: fresh } : null;
}

function samePair(a: BikeshareOption, b: BikeshareOption): boolean {
  return a.pickup_station === b.pickup_station && a.dropoff_station === b.dropoff_station && a.ending === b.ending;
}

/** The option the shown plan rides: its answer's chosen pair, found in the kept list; -1 if none. */
export function pickedOption(options: readonly BikeshareOption[], plan: BikesharePlan | null): number {
  const chosen = plan?.options?.find((o) => o.chosen) ?? plan?.options?.[0];
  if (!chosen) return -1;
  return options.findIndex((o) => samePair(o, chosen));
}

/**
 * The station pins that plan an option (lib/stations.ts withStations): each end's station, held to the trip's
 * start and end; none where the option has no station (a free e-bike, or an outside-dock ending), so the
 * server picks as it did for the first answer.
 */
export function optionPins(option: BikeshareOption, points: readonly LonLat[]): Pins {
  const pins: Pins = {};
  if (points.length < 2) return pins;
  if (option.pickup_station) pins.pickup = { id: option.pickup_station, name: option.pickup.name, at: points[0] };
  if (option.dropoff_station) pins.dropoff = { id: option.dropoff_station, name: option.dropoff.name, at: points[points.length - 1] };
  return pins;
}

/** A lettered option's name, shown and read alike: "B: <the option's text>". */
export function optionName(letter: string, option: BikeshareOption): string {
  return `${letter}: ${option.text}`;
}

/** What is said when an option is picked (always: it re-plans). */
export function optionSaid(letter: string, option: BikeshareOption): string {
  return `Option ${letter}: picking up at ${option.pickup.name}. Planning it.`;
}

// ---- A free-floating e-bike (follow-up review of PR #95) ----

/**
 * Whether an option is replayed from the first answer instead of re-planned: a free-floating e-bike has no
 * pick-up station id to ask for again, so its pins would leave the pick-up to the server, which may plan the
 * best option again (another e-bike, or a dock). The server offers such an option only as the plan's own
 * start, the first answer's (`core.bikeshare._options`, #94), so that answer is the option's plan.
 */
export function replaysFirst(option: BikeshareOption): boolean {
  return option.pickup_station === null;
}

/** The pins that replay the first answer: none, as the first answer was asked for. */
export const FIRST_ANSWER_PINS: Pins = {};

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((k) => [k, stable((value as Record<string, unknown>)[k])]),
    );
  }
  return value;
}

/**
 * A plan as sent (its points, ride type and dials, the chosen stations with them), for matching a request to
 * the first answer. Unlike the link's key it holds the stations, so a pinned re-plan never matches it.
 */
export function sentPlanKey(points: readonly LonLat[], preset: string, dials: object): string {
  return JSON.stringify(stable([points, preset, dials]));
}

/** The answer that listed a trip's options, kept to replay a free-floating e-bike's option. */
export interface FirstAnswer<R> {
  /** sentPlanKey of the plan it answered. */
  key: string;
  /** optionsKey of its trip. */
  trip: string;
  route: R;
}

/**
 * Whether an answer is kept as the first answer: a Bikeshare answer listing two or more options is the
 * answer the list is kept from (keepOptions' "fresh" rule), so it is the one to replay.
 */
export function keepsFirst(plan: BikesharePlan | null): boolean {
  return (plan?.options?.length ?? 0) > 1;
}

/**
 * The route to answer a request with, without asking the planner: the first answer, only when a free e-bike's
 * option asked for it (`asked`, its key) and the request is exactly the plan it answered. Else null (sent).
 */
export function replayFor<R>(first: FirstAnswer<R> | null, asked: string | null, requestKey: string): R | null {
  if (!first || asked === null || asked !== first.key || requestKey !== first.key) return null;
  return first.route;
}

/** What is said when a free e-bike's option is shown again from the first answer (nothing is re-planned). */
export function optionReplaySaid(letter: string, option: BikeshareOption): string {
  return `Option ${letter}: picking up at ${option.pickup.name}, as first planned.`;
}

/**
 * Said when a free e-bike's option cannot be shown again (the ride's settings changed since the first answer):
 * it is not re-planned, since asking again could plan another bike or a dock.
 */
export function stationlessUnavailable(letter: string): string {
  return `Option ${letter}, an e-bike outside a dock, came from the first plan, and the ride's settings have changed since, so it cannot be planned again.`;
}
