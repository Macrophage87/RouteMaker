/**
 * Go's "More direct" and "Calmer" (the owner, 2026-10-16, test-riding: "in go mode see if it's possible to change the
 * routing to be one notch more traffic tolerant and one notch less tolerant on routes and show them as options saying
 * what's gained and the tradeoff"). The API plans the trip one notch either side of the rider's traffic setting
 * (core.presets stress_notches, POST /api/route/neighbours) once the rider's own route is shown; here each is compared
 * with that route, kept only where it really differs, and given one short line: what it gains, then what it costs.
 * They join Go's routes to choose from after the rider's own, which stays first and chosen. Choosing one rides it and
 * changes no setting: the rider's traffic setting, and the saved default (the Ride sheet's Edit default), stay as
 * they are. Bike-only ride types and plain Bikeshare (its ride between the same docks); not the multimodal trips, and
 * not Mass Ride, whose slider is locked.
 */
import type { NeighbourKind, NeighbourOption, RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import { formatDistanceChange, formatDuration } from "./format.ts";
import { isTransit, type PresetId } from "./presets.ts";
import type { StressKey } from "./stressBar.ts";

export const NEIGHBOUR_NAME: Record<NeighbourKind, string> = { direct: "More direct", calmer: "Calmer" };

/**
 * Whether Go asks for the options at all: the bike-only ride types with a traffic slider to move, and plain Bikeshare
 * (the owner, 21:21: "You can put it on bikeshare, but the multimodal trips will have way too many options"). Not the
 * transit ride types, nor Rebalance Ride, whose docks are the point of it.
 */
export function offersNeighbours(preset: PresetId): boolean {
  return !isTransit(preset) && preset !== "rebalance" && preset !== "mass-ride";
}

/**
 * The dials the options are asked for with, or null where none can be: a Bikeshare plan's are its own docks (the dock
 * picked up from, and the one returned to unless it ends outside a dock), so only the ride between them changes; a plan
 * from a free e-bike has no dock to keep. Every other ride type asks with the plan's own dials.
 */
export function neighbourDials(preset: PresetId, dials: Dials, final: RouteResponse): Dials | null {
  if (preset !== "bikeshare") return dials;
  const plan = final.bikeshare;
  const pickup = plan?.start.kind === "dock" ? plan.start.station_id : null;
  const dropoff = plan?.end.kind === "dock" ? plan.end.station_id : null;
  if (!plan || !pickup || (plan.ending !== "outside_dock" && !dropoff)) return null;
  return {
    ...dials,
    bike: plan.bike,
    ending: plan.ending,
    pickupStation: pickup,
    ...(dropoff && plan.ending !== "outside_dock" ? { dropoffStation: dropoff } : { dropoffStation: undefined }),
  };
}

/** An option is shown only where it saves or costs at least this much time (the coordinator, 2026-10-16)... */
export const MIN_TIME_S = 120;
/** ...or moves at least this much riding between stress tiers: 0.3 mi (0.5 km). */
export const MIN_MOVED_M = 483;
/** Below these a figure is not said: under a minute, and under about 250 ft (80 m), which reads as 0.0 mi. */
const SAID_S = 60;
const SAID_M = 80;
/** A trail is named where one route rides at least 0.5 mi (0.8 km) of it and the other next to none. */
const TRAIL_M = 800;
const TRAIL_NONE_M = 160;
/** On Novice and Nervous and Cargo with passengers more direct never means more LTS 4: beyond rounding, it is left out. */
const LTS4_ROUNDING_M = 10;

function tier(route: RouteResponse, t: StressKey): number {
  return route.stress_m?.[t] ?? 0;
}

function lts4(route: RouteResponse): number {
  return tier(route, "4") + tier(route, "5");
}

function busy(route: RouteResponse): number {
  return tier(route, "3") + lts4(route);
}

/** How much riding moved between stress tiers, half the sum of each tier's change (a metre moved counts once). */
export function movedBetweenTiers(own: RouteResponse, other: RouteResponse): number {
  const tiers = new Set([...Object.keys(own.stress_m ?? {}), ...Object.keys(other.stress_m ?? {})] as StressKey[]);
  let sum = 0;
  for (const t of tiers) sum += Math.abs(tier(other, t) - tier(own, t));
  return sum / 2;
}

/** Whether `other` differs enough from `own` to be offered: at least MIN_TIME_S, or MIN_MOVED_M between tiers. */
export function differsEnough(own: RouteResponse, other: RouteResponse): boolean {
  return Math.abs(other.duration_s - own.duration_s) >= MIN_TIME_S || movedBetweenTiers(own, other) >= MIN_MOVED_M;
}

/** The named trails a route rides, metres each, from its description's stretches on paths. */
function trails(route: RouteResponse): Map<string, number> {
  const out = new Map<string, number>();
  for (const entry of route.description ?? []) {
    if (entry.kind !== "stretch" || entry.facility !== "path" || !entry.street) continue;
    out.set(entry.street, (out.get(entry.street) ?? 0) + Math.max(0, entry.to_m - entry.from_m));
  }
  return out;
}

/** The notable trail `other` gains or loses against `own`, the longest change, or null. */
export function trailChange(own: RouteResponse, other: RouteResponse): { name: string; gained: boolean } | null {
  const mine = trails(own);
  const theirs = trails(other);
  let best: { name: string; gained: boolean; m: number } | null = null;
  for (const [name, m] of theirs) {
    if (m >= TRAIL_M && (mine.get(name) ?? 0) < TRAIL_NONE_M && (!best || m > best.m)) best = { name, gained: true, m };
  }
  for (const [name, m] of mine) {
    if (m >= TRAIL_M && (theirs.get(name) ?? 0) < TRAIL_NONE_M && (!best || m > best.m)) best = { name, gained: false, m };
  }
  return best && { name: best.name, gained: best.gained };
}

/** "the Metropolitan Branch Trail", or a name that already starts with "the" as it is. */
function trailName(name: string): string {
  return /^the\s/i.test(name) ? name : `the ${name}`;
}

/**
 * The option's line against the rider's own route: what it gains, then what it costs, US units first.
 * "4 min faster, 0.6 mi (1.0 km) more on busier streets"; "0.9 mi (1.4 km) less on busy streets, 3 min
 * longer"; a notable trail gained or left is named last of its side ("on the Metropolitan Branch Trail"). Empty where
 * it gains nothing, and such an option is not offered.
 */
export function tradeoffLine(own: RouteResponse, other: RouteResponse): string {
  const gains: string[] = [];
  const costs: string[] = [];
  const dt = other.duration_s - own.duration_s;
  const time = formatDuration(Math.abs(dt));
  if (dt <= -SAID_S) gains.push(`${time} faster`);
  const dBusy = busy(other) - busy(own);
  if (dBusy <= -SAID_M) gains.push(`${formatDistanceChange(dBusy)} less on busy streets`);
  if (dBusy >= SAID_M) {
    const d4 = lts4(other) - lts4(own);
    // In words, never as a level number (the review's 8): heavy-traffic roads where those grow, else busier streets.
    const which = d4 >= SAID_M ? "heavy-traffic roads" : "busier streets";
    costs.push(`${formatDistanceChange(dBusy)} more on ${which}`);
  }
  if (dt >= SAID_S) costs.push(`${time} longer`);
  const trail = trailChange(own, other);
  if (trail?.gained) gains.push(`on ${trailName(trail.name)}`);
  if (gains.length === 0) return "";
  if (trail && !trail.gained) costs.push(`leaves ${trailName(trail.name)}`);
  return [...gains, ...costs].join(", ");
}

/** Whether the ride must never be offered more LTS 4 to be more direct: Novice and Nervous, Cargo with passengers. */
function holdsLts4(preset: PresetId, dials: Pick<Dials, "carrying"> | undefined): boolean {
  return preset === "novice" || (preset === "cargo" && dials?.carrying === "people");
}

/** Go's route choice holds at most this many rows: the rider's own, its routes to choose from, then the options. */
export const MAX_ROWS = 4;

/**
 * The options to offer beside `answer`, more direct first, each a route tagged with its kind, setting and line. Kept
 * only where it does what its name says (More direct saves at least a minute, Calmer takes at least 250 ft (80 m) off
 * busy riding), differs enough from every route already in the choice (the answer, its routes to choose from, and a
 * kept option), and, on a ride that holds LTS 4, a more direct one adds none. The choice stays at MAX_ROWS rows: the
 * options go first. Each line is against the rider's own route, the answer.
 */
export function keptNeighbours(
  answer: RouteResponse,
  options: readonly NeighbourOption[],
  preset: PresetId,
  dials?: Pick<Dials, "carrying">,
): RouteResponse[] {
  const shown = [answer, ...(answer.candidates ?? [])];
  const kept: RouteResponse[] = [];
  for (const option of [...options].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "direct" ? -1 : 1))) {
    if (shown.length + kept.length >= MAX_ROWS) break;
    const route = option.route;
    if ([...shown, ...kept].some((r) => !differsEnough(r, route))) continue;
    if (option.kind === "direct" && route.duration_s > answer.duration_s - SAID_S) continue;
    if (option.kind === "calmer" && busy(route) > busy(answer) - SAID_M) continue;
    if (option.kind === "direct" && holdsLts4(preset, dials) && lts4(route) > lts4(answer) + LTS4_ROUNDING_M) continue;
    const line = tradeoffLine(answer, route);
    if (!line) continue;
    kept.push({ ...route, neighbour: { kind: option.kind, stress: option.stress, line } });
  }
  return kept;
}

/** The answer with the options after its own routes to choose from; the answer itself where there are none. */
export function withNeighbours(answer: RouteResponse | null, kept: readonly RouteResponse[]): RouteResponse | null {
  if (!answer || kept.length === 0) return answer;
  return { ...answer, candidates: [...(answer.candidates ?? []), ...kept] };
}

/** Said once, through the app's polite region, when the options arrive: "More direct and Calmer added to the route choice." */
export function neighboursSaid(kept: readonly RouteResponse[]): string {
  const names = kept.flatMap((r) => (r.neighbour ? [NEIGHBOUR_NAME[r.neighbour.kind]] : []));
  if (names.length === 0) return "";
  return `${names.join(" and ")} added to the route choice.`;
}

/**
 * The dials a ride on `shown` re-plans with (Ride mode's re-routes): the option's own traffic setting where the rider
 * chose one, so a re-route keeps to it; the plan's dials otherwise. A copy: the plan's dials, and the saved default,
 * are never changed by choosing.
 */
export function rideDials(planDials: Dials, shown: RouteResponse | null): Dials {
  const stress = shown?.neighbour?.stress;
  return stress === undefined ? planDials : { ...planDials, stress };
}
