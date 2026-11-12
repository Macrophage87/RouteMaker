/**
 * Go's "More direct" and "Calmer" (the owner, 2026-10-16, test-riding: "in go mode see if it's possible to change the
 * routing to be one notch more traffic tolerant and one notch less tolerant on routes and show them as options saying
 * what's gained and the tradeoff"). The API plans the trip a step either side of the rider's traffic setting (core.presets
 * stress_notches, POST /api/route/neighbours) once the rider's own route is shown; here each is compared with that
 * route, kept only where it really differs, and given one short line: what it gains, then what it costs.
 * They join Go's routes to choose from after the rider's own, which stays first and chosen. Choosing one rides it and
 * changes no setting: the rider's traffic setting, and the saved default (the Ride sheet's Edit default), stay as
 * they are. Bike-only ride types and plain Bikeshare (its ride between the same docks); not the multimodal trips, and
 * not Mass Ride, whose slider is locked.
 */
import type { NeighbourKind, NeighbourOption, RouteResponse } from "./api.ts";
import { t } from "./i18n.ts";
import type { Dials } from "./dials.ts";
import { formatDistanceChange, formatDuration } from "./format.ts";
import { isTransit, type PresetId } from "./presets.ts";
import { turnTotal, unpavedMetres } from "./quickFigures.ts";
import type { StressKey } from "./stressBar.ts";

/** The calmer option is the trailmaxxed route, the top of the rider's slider (the owner, 2026-10-19; core.presets stress_notches). */
export const NEIGHBOUR_NAME: Record<NeighbourKind, string> = {
  direct: t("More direct"),
  calmer: "Trailmaxxed",
  // The backlog's "fewer turns" item (2026-11-12): the rider's own setting with one choice on, named for what it trades.
  fewer_turns: t("Fewer turns"),
  paved: t("All paved"),
};

/** "Fewer turns" is asked for only where the route has at least this many turns (our default, unmeasured). */
export const ASK_FEWER_TURNS_AT = 6;
/** ...and kept only where it has at least this many fewer, and at least a quarter fewer (our defaults, unmeasured). */
export const FEWER_TURNS_BY = 3;
export const FEWER_TURNS_SHARE = 0.25;
/** "All paved" is asked for, and kept, only where it takes at least this much unpaved riding off: 0.1 mi (160 m). */
export const PAVED_BY_M = 160;

function turnsOf(route: RouteResponse): number {
  return route.description == null ? 0 : turnTotal(route);
}

function unpavedOf(route: RouteResponse): number {
  return unpavedMetres(route.stress_spans) ?? 0;
}

/**
 * The options to ask for beside the rider's own route, in order of want (POST /api/route/neighbours `options`): Go's
 * More direct and Trailmaxxed (`go`), then Fewer turns where the route has ASK_FEWER_TURNS_AT turns or more, and All
 * paved where it rides PAVED_BY_M unpaved or more. Plan has its traffic slider for the first two, so asks only the
 * named ones; null where there is nothing to ask.
 */
export function neighbourKinds(final: RouteResponse, go: boolean): NeighbourKind[] | null {
  const kinds: NeighbourKind[] = go ? ["direct", "calmer"] : [];
  if (turnsOf(final) >= ASK_FEWER_TURNS_AT) kinds.push("fewer_turns");
  if (unpavedOf(final) >= PAVED_BY_M) kinds.push("paved");
  return kinds.length ? kinds : null;
}

/** Whether a Fewer turns option does what its name says against the rider's own route. */
export function fewerTurnsEnough(own: RouteResponse, other: RouteResponse): boolean {
  const mine = turnsOf(own);
  return mine - turnsOf(other) >= Math.max(FEWER_TURNS_BY, Math.ceil(mine * FEWER_TURNS_SHARE));
}

/** Whether an All paved option takes enough unpaved riding off the rider's own route. */
export function pavedEnough(own: RouteResponse, other: RouteResponse): boolean {
  return unpavedOf(own) - unpavedOf(other) >= PAVED_BY_M;
}

/** Whether two routes read the same on the figures a named option is chosen by: the same turns, unpaved and length. */
function sameNamedFigures(a: RouteResponse, b: RouteResponse): boolean {
  return turnsOf(a) === turnsOf(b) && Math.abs(unpavedOf(a) - unpavedOf(b)) < SAID_M && Math.abs(a.distance_m - b.distance_m) < SAID_M;
}

/**
 * Whether Go asks for the options at all: the bike-only ride types with a traffic slider to move, and plain Bikeshare
 * (the owner, 21:21: "You can put it on bikeshare, but the multimodal trips will have way too many options"). Not the
 * transit ride types, nor Rebalance Ride, whose docks are the point of it.
 */
export function offersNeighbours(preset: PresetId): boolean {
  // Nor Run (2026-11-02): it has no traffic slider.
  return !isTransit(preset) && preset !== "rebalance" && preset !== "mass-ride" && preset !== "run";
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
export function tradeoffLine(own: RouteResponse, other: RouteResponse, kind?: NeighbourKind): string {
  const gains: string[] = [];
  const costs: string[] = [];
  // A named option says first what it is named for: "5 fewer turns", "0.6 mi (1.0 km) less unpaved".
  const fewer = turnsOf(own) - turnsOf(other);
  if (kind === "fewer_turns" && fewer > 0) gains.push(fewer === 1 ? "1 fewer turn" : `${fewer} fewer turns`);
  const dUnpaved = unpavedOf(other) - unpavedOf(own);
  if (kind === "paved" && dUnpaved <= -SAID_M) gains.push(`${formatDistanceChange(dUnpaved)} less unpaved`);
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
 * kept option), and, on a ride that holds LTS 4, a more direct one adds none. Each line is against the rider's own
 * route, the answer. The choice stays at MAX_ROWS rows and the options come before the answer's own last routes to
 * choose from (the owner, 2026-10-19: "I never see the options"; at the top of the slider the router's three filled
 * it), except the first `keepRouter` of those, the one the rider has already chosen and those before it.
 */
export function keptNeighbours(
  answer: RouteResponse,
  options: readonly NeighbourOption[],
  preset: PresetId,
  dials?: Pick<Dials, "carrying">,
  keepRouter = 0,
): RouteResponse[] {
  const shown = [answer, ...(answer.candidates ?? [])];
  const room = MAX_ROWS - 1 - Math.min(keepRouter, shown.length - 1);
  const kept: RouteResponse[] = [];
  const order: NeighbourKind[] = ["direct", "calmer", "fewer_turns", "paved"];
  for (const option of [...options].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))) {
    if (kept.length >= room) break;
    const route = option.route;
    const named = option.kind === "fewer_turns" || option.kind === "paved";
    // A named option differs in what it is named for, which time and stress may not show; it is left out only where a
    // route already in the choice reads the same.
    if ([...shown, ...kept].some((r) => (named ? sameNamedFigures(r, route) : !differsEnough(r, route)))) continue;
    if (option.kind === "direct" && route.duration_s > answer.duration_s - SAID_S) continue;
    if (option.kind === "calmer" && busy(route) > busy(answer) - SAID_M) continue;
    if (option.kind === "fewer_turns" && !fewerTurnsEnough(answer, route)) continue;
    if (option.kind === "paved" && !pavedEnough(answer, route)) continue;
    // Never more heavy traffic to be more direct, nor for fewer turns or pavement, on a ride that holds LTS 4.
    if (option.kind !== "calmer" && holdsLts4(preset, dials) && lts4(route) > lts4(answer) + LTS4_ROUNDING_M) continue;
    const line = tradeoffLine(answer, route, option.kind);
    if (!line) continue;
    kept.push({ ...route, neighbour: { kind: option.kind, stress: option.stress, line } });
  }
  return kept;
}

/**
 * The answer with the options after as many of its own routes to choose from as still fit in MAX_ROWS rows (the
 * options have their room first, keptNeighbours); the answer itself where there are none.
 */
export function withNeighbours(answer: RouteResponse | null, kept: readonly RouteResponse[]): RouteResponse | null {
  if (!answer || kept.length === 0) return answer;
  const own = (answer.candidates ?? []).slice(0, Math.max(0, MAX_ROWS - 1 - kept.length));
  return { ...answer, candidates: [...own, ...kept] };
}

/**
 * Said once, through the app's polite region, when the options arrive: "More direct and Calmer added to the route
 * choice.", or, where they took the place of the answer's own last routes (`displaced` of them, said before as part of
 * its count), "More direct and Calmer replace the last 2 routes."
 */
export function neighboursSaid(kept: readonly RouteResponse[], displaced = 0): string {
  const names = kept.flatMap((r) => (r.neighbour ? [NEIGHBOUR_NAME[r.neighbour.kind]] : []));
  if (names.length === 0) return "";
  const who = names.join(" and ");
  if (displaced === 1) return `${who} ${names.length === 1 ? "replaces" : "replace"} the last route.`;
  if (displaced > 1) return `${who} ${names.length === 1 ? "replaces" : "replace"} the last ${displaced} routes.`;
  return `${who} added to the route choice.`;
}

/** How many of the answer's own routes to choose from gave way to the options in `picked` (withNeighbours). */
export function displacedBy(answer: RouteResponse | null, picked: RouteResponse | null, kept: readonly RouteResponse[]): number {
  const own = answer?.candidates?.length ?? 0;
  const left = (picked?.candidates?.length ?? 0) - kept.length;
  return Math.max(0, own - left);
}

/**
 * The dials a ride on `shown` re-plans with (Ride mode's re-routes): the option's own traffic setting where the rider
 * chose one, so a re-route keeps to it; the plan's dials otherwise. A copy: the plan's dials, and the saved default,
 * are never changed by choosing.
 */
export function rideDials(planDials: Dials, shown: RouteResponse | null): Dials {
  const neighbour = shown?.neighbour;
  if (!neighbour) return planDials;
  // A named option's re-plans keep its choice too ("Fewer turns", "All paved").
  return {
    ...planDials,
    stress: neighbour.stress,
    ...(neighbour.kind === "fewer_turns" ? { fewerTurns: true } : {}),
    ...(neighbour.kind === "paved" ? { paved: true } : {}),
  };
}
