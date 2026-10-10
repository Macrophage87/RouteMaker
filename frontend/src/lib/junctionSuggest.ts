/**
 * Rider suggestions for a junction's danger level (FOLLOWUP-STRESS-SUGGEST, OWNER-DECISIONS 232;
 * core/junction_suggestions.py). The owner: "add a mechanism for intersections as well. In some times
 * the road is fine, but the intersection can be especially dangerous."
 *
 * A rider the settings allow (`Me.can_suggest`, the roads' own setting) opens the road panel on a junction
 * (its marker's card has a Suggest a change button, or any spot within JUNCTION_SPOT_FT of one) and picks a
 * level in plain words and/or "more or less dangerous than shown", with a reason. Only the junction's node
 * is kept (the API snaps the spot to it), never where the rider clicked or stands. The admin reviews it with
 * the roads' three actions (SuggestionReview.tsx).
 */
import type { RouteResponse } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { call, suggestionLine, type ReviewAction, type SuggestionItem } from "./suggestions.ts";

/** The levels, as the poll says them (core/suggestion_post.py JUNCTION_WORDS). 5 is Avoid. */
export const JUNCTION_LEVELS: readonly { level: 2 | 3 | 4 | 5; words: string }[] = [
  { level: 2, words: "Easy: little waiting, and drivers are slow" },
  { level: 3, words: "Takes patience: you wait for a gap" },
  { level: 4, words: "Hard: long waits or fast traffic" },
  { level: 5, words: "Avoid crossing here" },
];

/** What the rider's route shows at the junction: no marker, an orange or a red marker, or Avoid. */
export type Shown = "none" | "orange" | "red" | "avoid";
export type Direction = "more" | "less";

/** The level each marker stands for (core/junction_suggestions.py SHOWN_LEVELS). */
export const SHOWN_LEVELS: Readonly<Record<Shown, number>> = { none: 2, orange: 3, red: 4, avoid: 5 };

/** What the map shows there, in words, for the form's "Now:" line. */
export const SHOWN_WORDS: Readonly<Record<Shown, string>> = {
  none: "no marker on your route",
  orange: "an orange marker, higher stress",
  red: "a red marker, very high stress",
  avoid: "rated Avoid",
};

export const JUNCTION_SUGGEST_TEXT = "Suggest a junction change";
export const JUNCTION_SUGGEST_HEADING = "Suggest a danger level for this junction";
export const JUNCTION_LEVEL_LEGEND = "How dangerous is it? (optional)";
export const JUNCTION_DIRECTION_LEGEND = "Compared with what the map shows (optional)";
export const DIRECTION_WORDS: Readonly<Record<Direction, string>> = {
  more: "More dangerous than shown",
  less: "Less dangerous than shown",
};
export const JUNCTION_PRIVACY =
  "An admin reviews every suggestion before anything changes. The junction's location and your reason may be shared in a public poll to ask other riders, never your name or the spot you clicked.";
export const JUNCTION_REASON_MAX = 500;

/**
 * How near the road panel's spot a junction's marker must be for the form to say what the route shows
 * there: 82 ft (25 m), the API's own reach for the junction (SNAP_MAX_M) and the Avoid card's
 * (AVOID_SPOT_M).
 */
export const JUNCTION_SPOT_M = 25;
export const JUNCTION_SPOT_FT = 82;

/** The junction the API found at a spot (GET /api/junction-suggestions/at): its node, never the spot. */
export interface JunctionAt {
  lon: number;
  lat: number;
  name: string;
  roads: string[];
}

export interface JunctionRequest {
  lat: number;
  lon: number;
  level: number | null;
  direction: Direction | null;
  shown: Shown | null;
  reason: string;
}

/** One junction suggestion waiting for review (core/junction_suggestions.py summary). */
export interface JunctionSuggestionItem {
  id: number;
  junction: string;
  lat: number;
  lon: number;
  current_level: number;
  current_words: string;
  level: number;
  words: string;
  direction: Direction | null;
  reason: string;
  status: "pending" | "sent_to_discord";
  created_at: string;
  sent_at: string | null;
}

type Fetch = typeof fetch;

/**
 * What the rider's route shows nearest `point`, within JUNCTION_SPOT_M: Avoid first, then the worst
 * marker; "none" where the route shows nothing there; null with no route (the map shows nothing to
 * compare with, and the API takes the junction as not marked).
 */
export function shownNear(
  route: Pick<RouteResponse, "intersections" | "avoid_junctions"> | null,
  point: LonLat,
  within = JUNCTION_SPOT_M,
): Shown | null {
  if (!route) return null;
  const near = (lon: number, lat: number) => haversineM([lon, lat], point) <= within;
  if ((route.avoid_junctions ?? []).some((a) => near(a.lon, a.lat))) return "avoid";
  const marks = (route.intersections ?? []).filter((j) => near(j.lon, j.lat)).map((j) => j.severity);
  if (marks.includes("red")) return "red";
  if (marks.includes("orange")) return "orange";
  return "none";
}

/** The words of a level: "Hard: long waits or fast traffic". */
export function levelWords(level: number): string {
  return JUNCTION_LEVELS.find((l) => l.level === level)?.words ?? "Not rated";
}

/**
 * The form's own check before sending (the API checks again, against the junction's approved rating):
 * the field and its sentence, or null.
 */
export function junctionProblem(
  level: number | null,
  direction: Direction | null,
  reason: string,
  shown: Shown | null,
): { field: "level" | "direction" | "reason"; message: string } | null {
  if (level === null && direction === null) {
    return { field: "level", message: "Choose a level, or say whether it is more or less dangerous than shown." };
  }
  const current = SHOWN_LEVELS[shown ?? "none"];
  if (level !== null && direction === null && level === current) {
    return { field: "level", message: "That is how the map shows it already." };
  }
  if (level !== null && direction !== null && (direction === "more" ? level < current : level > current)) {
    return { field: "direction", message: "The level and the comparison disagree. Choose one, or make them match." };
  }
  if (level === null && direction === "more" && current >= 5) {
    return { field: "direction", message: "The map rates it Avoid already, the most dangerous level." };
  }
  if (level === null && direction === "less" && current <= 2) {
    return { field: "direction", message: "The map shows it as easy already, the least dangerous level." };
  }
  const text = reason.trim();
  if (!text) return { field: "reason", message: "Say why, in a sentence or two." };
  if (text.length > JUNCTION_REASON_MAX) {
    return { field: "reason", message: `The reason is at most ${JUNCTION_REASON_MAX} characters.` };
  }
  return null;
}

/** GET /api/junction-suggestions/at: the junction at the spot, or null (none there, or not allowed). */
export async function findJunction(origin: string, point: LonLat, signal?: AbortSignal, run: Fetch = fetch): Promise<JunctionAt | null> {
  const url = `${origin}/api/junction-suggestions/at?lat=${point[1].toFixed(6)}&lon=${point[0].toFixed(6)}`;
  const r = await call<JunctionAt>(url, { method: "GET", signal }, null, run);
  return r.ok ? r.body : null;
}

/** POST /api/junction-suggestions. */
export async function sendJunctionSuggestion(
  origin: string,
  request: JunctionRequest,
  csrf: string | null,
  run: Fetch = fetch,
): Promise<{ kind: "sent"; message: string } | { kind: "refused"; status: number; message: string; field: string | null }> {
  const r = await call<{ message: string }>(`${origin}/api/junction-suggestions`, { method: "POST", body: JSON.stringify(request) }, csrf, run);
  return r.ok ? { kind: "sent", message: r.body.message } : { kind: "refused", status: r.status, message: r.message, field: r.field };
}

/** GET /api/junction-suggestions/open (instance admin). */
export async function fetchJunctionSuggestions(origin: string, run: Fetch = fetch): Promise<JunctionSuggestionItem[] | string> {
  const r = await call<{ suggestions: JunctionSuggestionItem[] }>(`${origin}/api/junction-suggestions/open`, { method: "GET" }, null, run);
  return r.ok ? r.body.suggestions : r.message;
}

/** POST /api/junction-suggestions/{id}/{action} (instance admin). */
export async function reviewJunctionSuggestion<T = { message: string; status: string }>(
  origin: string,
  id: number,
  action: ReviewAction,
  csrf: string | null,
  run: Fetch = fetch,
): Promise<{ ok: true; body: T } | { ok: false; message: string }> {
  const r = await call<T>(`${origin}/api/junction-suggestions/${id}/${action}`, { method: "POST", body: "{}" }, csrf, run);
  return r.ok ? r : { ok: false, message: r.message };
}

/** The API's name for a junction whose roads it cannot name (core/junction_suggestions.py Node.name). */
export const UNNAMED_JUNCTION = "An unnamed junction";

/** The road panel's note for its Suggest a junction change button: which junction it is for. */
export function junctionNote(name: string): string {
  return name === UNNAMED_JUNCTION ? "for this unnamed junction." : `for the junction of ${name}.`;
}

/** A junction suggestion in one line for its heading: "Junction of Oak Street and Elm Street: from Takes patience to Hard". */
export function junctionLine(item: Pick<JunctionSuggestionItem, "junction" | "current_level" | "level">): string {
  const place = item.junction === UNNAMED_JUNCTION ? UNNAMED_JUNCTION : `Junction of ${item.junction}`;
  return `${place}: from ${shortWords(item.current_level)} to ${shortWords(item.level)}`;
}

/** A level's short name, before its colon: "Takes patience"; "Avoid" for 5. */
export function shortWords(level: number): string {
  if (level === 5) return "Avoid";
  return levelWords(level).split(":")[0];
}

/** What the rider said about the comparison, for the review list; "" where they chose a level only. */
export function directionLine(item: Pick<JunctionSuggestionItem, "direction">): string {
  return item.direction ? `The rider said: ${DIRECTION_WORDS[item.direction].toLowerCase()}.` : "";
}

/**
 * One suggestion in the admin's review list, a road's or a junction's (SuggestionReview.tsx): both have
 * the same three actions, at their own endpoints.
 */
export interface ReviewEntry {
  /** Unique across both kinds ("road-41", "junction-3"): the list's keys and element ids. */
  key: string;
  kind: "road" | "junction";
  id: number;
  /** What the status region names it by: "Oak Street", "the junction of Oak Street and Elm Street". */
  place: string;
  /** Its heading, both levels in words. */
  line: string;
  /** A further line in words ("The rider said: more dangerous than shown."), or "". */
  detail: string;
  reason: string;
  status: "pending" | "sent_to_discord";
  lat: number;
  lon: number;
  created_at: string;
}

export function roadEntry(item: SuggestionItem): ReviewEntry {
  return {
    key: `road-${item.id}`,
    kind: "road",
    id: item.id,
    place: item.road,
    line: suggestionLine(item),
    detail: "",
    reason: item.reason,
    status: item.status,
    lat: item.lat,
    lon: item.lon,
    created_at: item.created_at,
  };
}

export function junctionEntry(item: JunctionSuggestionItem): ReviewEntry {
  return {
    key: `junction-${item.id}`,
    kind: "junction",
    id: item.id,
    place: item.junction === UNNAMED_JUNCTION ? "the unnamed junction" : `the junction of ${item.junction}`,
    line: junctionLine(item),
    detail: directionLine(item),
    reason: item.reason,
    status: item.status,
    lat: item.lat,
    lon: item.lon,
    created_at: item.created_at,
  };
}

/** Both lists as one, oldest first (each API answers its own oldest first). */
export function reviewEntries(roads: SuggestionItem[], junctions: JunctionSuggestionItem[]): ReviewEntry[] {
  const all = [...roads.map(roadEntry), ...junctions.map(junctionEntry)];
  return all.sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
}

/** What the status region says after an action on an entry. */
export function entrySaid(action: ReviewAction, entry: Pick<ReviewEntry, "place">, message: string): string {
  if (action === "discord") return `The post for ${entry.place} is ready to copy below. The suggestion is marked as sent to Discord.`;
  return message;
}
