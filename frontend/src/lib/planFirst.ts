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
  /** The ride type's name is already a ride's (presets.ts presetNamesRide): "Mass Ride, ...", not "Mass Ride ride, ...". */
  named?: boolean;
}

const lower = (text: string) => (text ? text[0].toLowerCase() + text.slice(1) : text);

/** A list of linked names: "A", "A, then B", "A, then B, then C". */
function linked(items: { name: string; index: number }[]): Phrase[] {
  const out: Phrase[] = [];
  items.forEach((item, i) => {
    if (i > 0) out.push({ text: t(", then ") });
    out.push({ text: item.name, target: { kind: "point", index: item.index } });
  });
  return out;
}

/** A spot named for what is near it (the reverse geocoder's "near Capitol Stones", core/geocode.py). */
const NEAR = /^near\s+/i;

/**
 * The words before a place: "End at Silver Spring", but "End near Capitol Stones", never "End at near Capitol
 * Stones" (P10). `items` are the names after it; the first loses its "near" when the lead says it.
 */
function lead(at: string, near: string, items: { name: string; index: number }[]): Phrase[] {
  if (!items.length || !NEAR.test(items[0].name)) return [{ text: at }, ...linked(items)];
  return [{ text: near }, ...linked([{ ...items[0], name: items[0].name.replace(NEAR, "") }, ...items.slice(1)])];
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
  const nameAt = (i: number) => nameOf(points[i]) ?? t("a point on the map");
  const sentences: Phrase[][] = [];
  if (points.length === 0) {
    sentences.push([{ text: t("Start: tap the map or search for a place.") }]);
  } else {
    const start = [{ name: nameAt(0), index: 0 }];
    sentences.push([...(loop ? lead(t("Start and finish at "), t("Start and finish near "), start) : lead(t("Start at "), t("Start near "), start)), { text: "." }]);
    const stops = named.flatMap((n, index) => (n.role === "stop" ? [{ name: nameAt(index), index }] : []));
    const vias = named.flatMap((n, index) => (n.role === "via" ? [{ name: nameAt(index), index }] : []));
    if (stops.length) sentences.push([...lead(t("Stop at "), t("Stop near "), stops), { text: "." }]);
    if (vias.length) sentences.push([{ text: t("Pass through ") }, ...linked(vias), { text: t(" (via).") }]);
    const end = named.findIndex((n) => n.role === "end");
    if (end >= 0) sentences.push([...lead(t("End at "), t("End near "), [{ name: nameAt(end), index: end }]), { text: "." }]);
    else if (!loop) sentences.push([{ text: t("End: tap the map or search for a place.") }]);
  }
  // The words around the ride type, in the language's own order ("Default ride", "Recorrido Default").
  const rideLink: Phrase = { text: words.ride, target: { kind: "ride" } };
  // A ride type named as a ride already (Group Ride, Mass Ride, Rebalance Ride) stands alone: never "Mass Ride ride"
  // (the audit's P14).
  const [before, after] = words.named || /\bride$/i.test(words.ride.trim()) ? ["", ""] : t("{ride} ride").split("{ride}");
  const ride: Phrase[] = [{ text: before }, rideLink, { text: after }].filter((p) => p === rideLink || p.text !== "");
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

/**
 * The plan panel's row (app/PlanPanel.tsx): while routing, on an empty plan, or with the plan changed. A route up to
 * date shows none (Plan on a phone, P10: "Route ✓ up to date" said the obvious); the panel says it out of sight.
 */
export function planRowShown(state: { routing: boolean; locate: boolean; unavailable: string | null }): boolean {
  return state.routing || state.locate || state.unavailable !== ROUTE_UP_TO_DATE;
}
export const PLANNING_SAID = t("Planning route");
export const CANCELLED_SAID = t("Routing cancelled. The plan is as you left it.");
export const RESET_SAID = t("Reset to the route as drawn. Undo brings your changes back.");
export const CLEARED_SAID = t("Plan cleared. Undo brings it back.");
/** Go's Clear names the route, as its button does: Go riders never meet the word "plan" (the 2026-10-29 review). */
export const GO_CLEARED_SAID = t("Route cleared. Undo brings it back.");
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
  if (dmin !== 0) parts.push(t("{sign}{minutes} min", { sign: dmin > 0 ? "+" : "−", minutes: Math.abs(dmin) }));
  const dbusy = busyOf(after.stress_m) - busyOf(before.stress_m);
  if (formatDistanceChange(dbusy) !== NO_CHANGE) parts.push(dbusy < 0 ? t("{distance} less on LTS 3 or busier", { distance: formatDistanceChange(dbusy) }) : t("{distance} more on LTS 3 or busier", { distance: formatDistanceChange(dbusy) }));
  const was = streets(before);
  const now = streets(after);
  const added = longestOnlyIn(now, was);
  const dropped = longestOnlyIn(was, now);
  if (added && dropped) parts.push(t("now uses {added} instead of {dropped}", { added, dropped }));
  else if (added) parts.push(t("now uses {added}", { added }));
  else if (dropped) parts.push(t("no longer uses {dropped}", { dropped }));
  if (parts.length === 0) return t("The same route as before.");
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
    label: t("{from} to {to}", { from: say(k), to: say(k + 1) }),
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
    if (!match) return t("{leg}: {distance}, a new leg.", { leg: leg.label, distance: formatDistance(leg.metres) });
    const d = leg.metres - match.metres;
    const change = formatDistanceChange(d) === NO_CHANGE ? t("unchanged") : `${d > 0 ? "+" : "−"}${formatDistanceChange(d)}`;
    return `${leg.label}: ${formatDistance(leg.metres)}, ${change}.`;
  });
  for (const leg of old.values()) lines.push(t("{leg}: no longer ridden (was {distance}).", { leg: leg.label, distance: formatDistance(leg.metres) }));
  return lines;
}
