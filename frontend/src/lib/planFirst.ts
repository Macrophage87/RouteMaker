/**
 * Plan mode: write the plan first, then route (v0.7.0 plan; Stephen 2026-10-14 14:11 UTC: "Create a plain text
 * plan that says starting here ending here with stops, via, etc. ... Then put a route button ... When a plan is
 * changed after rendering show the differences ... While rendering make it more clear that it's in progress").
 *
 * What the page shows and says, kept apart from App.tsx so it can be tested:
 * - the plan in plain sentences, each phrase pointing at its editor (planSentences);
 * - the Route button's label and why it is unavailable (routeButton);
 * - the step in words while routing (routingStep), and the elapsed seconds;
 * - the one-line summary of what an update changed (changeSummary);
 * - whether the plan changed since the route was drawn (planChanged), and why Reset is unavailable.
 */
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { t } from "./i18n.ts";
import { pathLengthM, type LonLat } from "./geo.ts";
import { formatDistance, formatDistanceChange } from "./format.ts";
import { namePoints } from "./pointKinds.ts";
import type { StressMetres } from "./stressBar.ts";

/** Where a phrase of the plan takes the rider: a point's row, the ride type, or one of the two sliders. */
export type PhraseTarget = { kind: "point"; index: number } | { kind: "ride" } | { kind: "traffic" } | { kind: "hills" };

/** A run of a sentence: plain text, or a link to its editor. */
export interface Phrase {
  text: string;
  target?: PhraseTarget;
}

/** What the sentences are made from, besides the points. */
export interface PlanWords {
  /** The ride type in words (presetSaid). */
  ride: string;
  /** The traffic slider in words (dials.ts stressWords), or null on a ride type without it. */
  traffic: string | null;
  /** The hills slider in words (dials.ts hillsWords), or null. */
  hills: string | null;
}

const lower = (text: string) => (text ? text[0].toLowerCase() + text.slice(1) : text);

/** A list of linked names: "A", "A, then B", "A, then B, then C". */
function linked(items: { name: string; index: number }[]): Phrase[] {
  const out: Phrase[] = [];
  items.forEach((item, i) => {
    if (i > 0) out.push({ text: ", then " });
    out.push({ text: item.name, target: { kind: "point", index: item.index } });
  });
  return out;
}

/**
 * The plan in sentences: "Start at Union Station. Stop at Eastern Market, then Union Market. Pass through Rock
 * Creek Trail (via). End at Silver Spring. Default ride, balanced, gentler grades." Each name, the ride type and
 * each slider's words are links to their editors. A point without a name is "a point on the map".
 */
export function planSentences(
  points: readonly LonLat[],
  isVia: (p: LonLat) => boolean,
  loop: boolean,
  nameOf: (p: LonLat) => string | undefined,
  words: PlanWords,
): Phrase[][] {
  const named = namePoints(points, isVia, loop);
  const nameAt = (i: number) => nameOf(points[i]) ?? "a point on the map";
  const sentences: Phrase[][] = [];
  if (points.length === 0) {
    sentences.push([{ text: "Start: tap the map or search for a place." }]);
  } else {
    sentences.push([{ text: loop ? "Start and finish at " : "Start at " }, { text: nameAt(0), target: { kind: "point", index: 0 } }, { text: "." }]);
    const stops = named.flatMap((n, index) => (n.role === "stop" ? [{ name: nameAt(index), index }] : []));
    const vias = named.flatMap((n, index) => (n.role === "via" ? [{ name: nameAt(index), index }] : []));
    if (stops.length) sentences.push([{ text: "Stop at " }, ...linked(stops), { text: "." }]);
    if (vias.length) sentences.push([{ text: "Pass through " }, ...linked(vias), { text: " (via)." }]);
    const end = named.findIndex((n) => n.role === "end");
    if (end >= 0) sentences.push([{ text: "End at " }, { text: nameAt(end), target: { kind: "point", index: end } }, { text: "." }]);
    else if (!loop) sentences.push([{ text: "End: tap the map or search for a place." }]);
  }
  const ride: Phrase[] = [{ text: words.ride, target: { kind: "ride" } }, { text: " ride" }];
  if (words.traffic) ride.push({ text: ", " }, { text: lower(words.traffic), target: { kind: "traffic" } });
  if (words.hills) ride.push({ text: ", " }, { text: lower(words.hills), target: { kind: "hills" } });
  ride.push({ text: "." });
  sentences.push(ride);
  return sentences;
}

/** The plan as one line of text (for a test, or a screen reader's summary). */
export function sentencesText(sentences: readonly Phrase[][]): string {
  return sentences.map((s) => s.map((p) => p.text).join("")).join(" ");
}

/** The ride the drawn route answers: what Reset goes back to, and what a change is measured against. */
export interface DrawnPlan<R> {
  points: readonly LonLat[];
  ride: R;
  /** The dials as sent, as a key (App's routeKey), so a slider moved and moved back is no change. */
  dialsKey: string;
}

/** Whether the plan now differs from the one the route shown was drawn for. */
export function planChanged<R extends { preset: string }>(drawn: DrawnPlan<R> | null, points: readonly LonLat[], preset: string, dialsKey: string): boolean {
  if (!drawn) return false;
  return drawn.points !== points || drawn.ride.preset !== preset || drawn.dialsKey !== dialsKey;
}

export const ROUTE_LABEL = t("Route");
export const UPDATE_LABEL = t("Update route");
/** The map bar's big button while routing (its progress is in the plan panel). */
export const ROUTING_LABEL = t("Routing…");
export const ROUTE_NEEDS_POINTS = t("Add a start and an end first.");
/** A loop needs a start and one stop (OWNER-DECISIONS 374). */
export const ROUTE_NEEDS_STOP = t("Add a start and a stop first.");
export const ROUTE_UP_TO_DATE = t("The route shown is up to date.");
export const RESET_LABEL = t("Reset");
export const RESET_NOTHING = t("Nothing changed since the route was drawn");
export const CLEAR_LABEL = t("Clear");
export const PLANNING_SAID = t("Planning route");
export const CANCELLED_SAID = t("Routing cancelled. The plan is as you left it.");
export const RESET_SAID = t("Reset to the route as drawn. Undo brings your changes back.");
export const CLEARED_SAID = t("Plan cleared. Undo brings it back.");
/** How long Clear waits for its route to go before it gives up handing the focus on (review a11y-1). */
export const CLEAR_FOCUS_WAIT_MS = 1000;

/** The Route button: its label, and why it does nothing now (null: it routes). */
export function routeButton(state: { points: number; drawn: boolean; changed: boolean; routeShown: boolean; loop?: boolean }): { label: string; unavailable: string | null } {
  const label = state.drawn && (state.changed || !state.routeShown) ? UPDATE_LABEL : ROUTE_LABEL;
  if (state.points < 2) return { label: ROUTE_LABEL, unavailable: state.loop ? ROUTE_NEEDS_STOP : ROUTE_NEEDS_POINTS };
  if (state.drawn && state.routeShown && !state.changed) return { label, unavailable: ROUTE_UP_TO_DATE };
  return { label, unavailable: null };
}

/**
 * The step shown while routing, by the time it has taken. The server answers in one piece, so the steps are
 * the planner's usual order paced by the clock, not reports from it (an open question for the owner).
 */
export function routingStep(elapsedMs: number): string {
  if (elapsedMs < 1500) return t("Finding routes");
  if (elapsedMs < 4000) return t("Checking traffic stress");
  if (elapsedMs < 9000) return t("Ranking");
  return t("Drawing");
}

/** "3 s", the seconds elapsed while routing. */
export function elapsedText(elapsedMs: number): string {
  return `${Math.floor(Math.max(0, elapsedMs) / 1000)} s`;
}

const busyOf = (stress: StressMetres) => (stress["3"] ?? 0) + (stress["4"] ?? 0) + (stress["5"] ?? 0);
const NO_CHANGE = formatDistanceChange(0);

/** Metres on each named street of a route (its description's stretches). */
function streets(route: Pick<RouteResponse, "description">): Map<string, number> {
  const out = new Map<string, number>();
  for (const entry of (route.description ?? []) as DescriptionEntry[]) {
    if (entry.kind !== "stretch" || !entry.street) continue;
    out.set(entry.street, (out.get(entry.street) ?? 0) + Math.max(0, entry.to_m - entry.from_m));
  }
  return out;
}

/** The longest street of `a` that `b` does not use (200 m or more), or null. */
function longestOnlyIn(a: Map<string, number>, b: Map<string, number>): string | null {
  let best: string | null = null;
  let bestM = 200;
  for (const [street, metres] of a) {
    if (!b.has(street) && metres >= bestM) {
      best = street;
      bestM = metres;
    }
  }
  return best;
}

type Compared = Pick<RouteResponse, "distance_m" | "duration_s" | "stress_m" | "description">;

/**
 * What an update changed, in one line: "+1.2 mi (1.9 km), +6 min, 0.4 mi (0.6 km) less on LTS 3 or busier, now
 * uses Beach Drive instead of 16th Street". Changes too small to say are left out.
 */
export function changeSummary(before: Compared, after: Compared): string {
  const parts: string[] = [];
  const dm = after.distance_m - before.distance_m;
  if (formatDistanceChange(dm) !== NO_CHANGE) parts.push(`${dm > 0 ? "+" : "−"}${formatDistanceChange(dm)}`);
  const dmin = Math.round((after.duration_s - before.duration_s) / 60);
  if (dmin !== 0) parts.push(`${dmin > 0 ? "+" : "−"}${Math.abs(dmin)} min`);
  const dbusy = busyOf(after.stress_m) - busyOf(before.stress_m);
  if (formatDistanceChange(dbusy) !== NO_CHANGE) parts.push(`${formatDistanceChange(dbusy)} ${dbusy < 0 ? "less" : "more"} on LTS 3 or busier`);
  const was = streets(before);
  const now = streets(after);
  const added = longestOnlyIn(now, was);
  const dropped = longestOnlyIn(was, now);
  if (added && dropped) parts.push(`now uses ${added} instead of ${dropped}`);
  else if (added) parts.push(`now uses ${added}`);
  else if (dropped) parts.push(`no longer uses ${dropped}`);
  if (parts.length === 0) return "The same route as before.";
  const line = parts.join(", ");
  return `${line[0].toUpperCase()}${line.slice(1)}.`;
}

/** A drawn route with the points it was drawn through, for its legs. */
export interface LeggedRoute {
  route: Pick<RouteResponse, "geometry" | "leg_ends">;
  points: readonly LonLat[];
  loop: boolean;
}

/** One leg of a route: its two ends (the plan's own point pairs), their names, and its length. */
interface Leg {
  from: LonLat;
  to: LonLat;
  label: string;
  metres: number;
}

/** A route's legs, from the API's `leg_ends`; null where they do not fit its points (an older API). */
function legsOf(drawn: LeggedRoute, isVia: (p: LonLat) => boolean, nameOf: (p: LonLat) => string | undefined): Leg[] | null {
  const { route, points, loop } = drawn;
  const through = loop ? [...points, points[0]] : [...points];
  const ends = route.leg_ends;
  const line = route.geometry.coordinates;
  if (!Array.isArray(ends) || ends.length !== through.length - 1 || ends[ends.length - 1] !== line.length - 1) return null;
  const named = namePoints(points, isVia, loop);
  const say = (i: number) => {
    const index = i % points.length;
    const place = nameOf(points[index]);
    const role = named[index]?.name ?? "Start";
    return place ? `${role} (${place})` : role;
  };
  return ends.map((end, k) => ({
    from: through[k],
    to: through[k + 1],
    label: `${say(k)} to ${say(k + 1)}`,
    metres: pathLengthM(line.slice(k === 0 ? 0 : ends[k - 1], end + 1)),
  }));
}

/**
 * The per-leg details behind the change summary (inverted pyramid: the one line first, these on a tap): each leg
 * of the new route with its length and, where the old route had the same leg (the same two points), the change;
 * then the old legs that are gone. Empty where either route's legs cannot be read.
 */
export function legChanges(
  before: LeggedRoute,
  after: LeggedRoute,
  isVia: (p: LonLat) => boolean,
  nameOf: (p: LonLat) => string | undefined,
): string[] {
  const was = legsOf(before, isVia, nameOf);
  const now = legsOf(after, isVia, nameOf);
  if (!was || !now) return [];
  const key = (leg: Leg) => `${leg.from[0]},${leg.from[1]}>${leg.to[0]},${leg.to[1]}`;
  const old = new Map(was.map((leg) => [key(leg), leg]));
  const lines = now.map((leg) => {
    const match = old.get(key(leg));
    old.delete(key(leg));
    if (!match) return `${leg.label}: ${formatDistance(leg.metres)}, a new leg.`;
    const d = leg.metres - match.metres;
    const change = formatDistanceChange(d) === NO_CHANGE ? "unchanged" : `${d > 0 ? "+" : "−"}${formatDistanceChange(d)}`;
    return `${leg.label}: ${formatDistance(leg.metres)}, ${change}.`;
  });
  for (const leg of old.values()) lines.push(`${leg.label}: no longer ridden (was ${formatDistance(leg.metres)}).`);
  return lines;
}
