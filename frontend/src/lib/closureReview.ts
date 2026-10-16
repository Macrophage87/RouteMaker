/**
 * Closures a RouteMaker reviewer enters or confirms (v0.7.0 closures; core/reviewed_closures.py): the pure half.
 * A reviewer (`Me.can_review_closures`: an instance admin, for now; guild reviewer roles are kept out)
 * marks a road piece or its whole named stretch closed from the road panel (ClosureEntry.tsx), and in Review
 * confirms or rejects riders' closure reports and ends a confirmed closure early (ClosureReview.tsx). A confirmed
 * closure is routed round and named by the closure check like a feed's, credited "Confirmed by a RouteMaker
 * reviewer".
 *
 * Saved-route alerts (core/saved_route_alerts.py) are read here too: My routes says the first closure on a route in
 * one line (`alertLine`).
 */
import { csrfFromCookie, refusalText } from "./stressEditor.ts";

export const MARK_CLOSED_TEXT = "Mark closed";
export const CLOSURE_HEADING = "Mark this road closed";
export const CONFIRM_HEADING = "Confirm this closure";
export const CLOSURE_EXTENT_LEGEND = "What is closed";
export const CLOSURE_REASON_LABEL = "Why it is closed";
export const CLOSURE_START_LABEL = "First day";
export const CLOSURE_END_LABEL = "Last day";
export const CLOSURE_END_HELP = "Leave it empty if no end is known: it then stays until a reviewer ends it.";
export const CLOSURE_URL_LABEL = "Source link (optional)";
export const CLOSURE_SEND = "Confirm closure";
export const CLOSURE_REASON_MAX = 500;
export const CLOSURE_NOTE =
  "Riders see the reason on their routes, credited “Confirmed by a RouteMaker reviewer”. New plans route round it within a minute.";
export const CLOSURES_HEADING = "Closures";

export interface ReviewedClosure {
  id: number;
  road: string;
  osm_way_ids: number[];
  reason: string;
  start: string | null;
  end: string | null;
  url: string | null;
  when_text: string;
  from_report: boolean;
  point: [number, number] | null;
}

export interface ClosureReport {
  id: number;
  osm_way_id: number;
  road: string;
  reason: string;
  /** The one-tap reasons' fixed words only, never the rider's own text: what the form starts with. */
  reason_fixed: string;
  lat: number;
  lon: number;
  created_at: string;
}

export interface ClosureReviewList {
  closures: ReviewedClosure[];
  reports: ClosureReport[];
}

/** One saved route's closure alert (`SavedRoute.closure_alerts`). */
export interface ClosureAlert {
  id: string;
  title: string;
  road: string | null;
  end: string | null;
  source: string;
  text: string;
}

/** My routes' one line for a route's alerts: the first, and how many more. */
export function alertLine(alerts: readonly ClosureAlert[] | null | undefined): string {
  if (!alerts || alerts.length === 0) return "";
  const more = alerts.length - 1;
  return more > 0 ? `${alerts[0].text} And ${more} more closure${more === 1 ? "" : "s"}.` : alerts[0].text;
}

/** Today in the region's own days (America/New_York), as YYYY-MM-DD: the form's first day. */
export function regionToday(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  return parts;
}

export type ClosureField = "reason" | "start" | "end" | "url";

/** What the form checks before it sends; the server checks it all again. */
export function closureProblem(reason: string, start: string, end: string, url: string): { field: ClosureField; message: string } | null {
  if (!reason.trim()) return { field: "reason", message: "Say why it is closed, in a few words." };
  if (reason.trim().length > CLOSURE_REASON_MAX) return { field: "reason", message: `The reason is at most ${CLOSURE_REASON_MAX} characters.` };
  if (start && end && end < start) return { field: "end", message: "The last day is before the first." };
  if (url.trim() && !/^https?:\/\/\S+$/i.test(url.trim())) return { field: "url", message: "The source link must be a web address (https://...)." };
  return null;
}

export interface ClosureBody {
  reason: string;
  start: string | null;
  end: string | null;
  url: string;
}

type Fetch = typeof fetch;
export type ClosureOutcome = { kind: "done"; id: number; message: string } | { kind: "refused"; message: string; field: string | null };

const docCookie = (): string => (typeof document === "undefined" ? "" : document.cookie);

async function send(url: string, payload: unknown, post: Fetch, cookie: string): Promise<ClosureOutcome> {
  const csrf = csrfFromCookie(cookie);
  try {
    const response = await post(url, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", ...(csrf ? { "X-CSRFToken": csrf } : {}) },
      body: JSON.stringify(payload),
    });
    const body = (await response.json().catch(() => ({}))) as { id?: number; message?: string; error?: string; field?: string };
    if (response.ok) return { kind: "done", id: Number(body.id), message: body.message ?? "Done." };
    return { kind: "refused", message: refusalText(response.status, body.error ?? null), field: body.field ?? null };
  } catch {
    return { kind: "refused", message: refusalText(500, null), field: null };
  }
}

/** POST /api/closures/reviewed: the road pieces closed. */
export function enterClosure(origin: string, wayIds: number[], body: ClosureBody, post: Fetch = fetch, cookie = docCookie()): Promise<ClosureOutcome> {
  return send(`${origin}/api/closures/reviewed`, { osm_way_ids: wayIds, ...body }, post, cookie);
}

/** POST /api/closures/reports/{id}/confirm: a rider's report confirmed, on its road piece. */
export function confirmReport(origin: string, reportId: number, body: ClosureBody, post: Fetch = fetch, cookie = docCookie()): Promise<ClosureOutcome> {
  return send(`${origin}/api/closures/reports/${reportId}/confirm`, body, post, cookie);
}

export function rejectReport(origin: string, reportId: number, post: Fetch = fetch, cookie = docCookie()): Promise<ClosureOutcome> {
  return send(`${origin}/api/closures/reports/${reportId}/reject`, {}, post, cookie);
}

export function endClosure(origin: string, closureId: number, post: Fetch = fetch, cookie = docCookie()): Promise<ClosureOutcome> {
  return send(`${origin}/api/closures/reviewed/${closureId}/end`, {}, post, cookie);
}

/** GET /api/closures/reviewed: the closures in force or to come, and the reports waiting; a sentence where it failed. */
export async function fetchClosureReview(origin: string, get: Fetch = fetch): Promise<ClosureReviewList | string> {
  try {
    const response = await get(`${origin}/api/closures/reviewed`, { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!response.ok) return "The closures could not be read; try again shortly.";
    const body = (await response.json()) as Partial<ClosureReviewList>;
    return { closures: body.closures ?? [], reports: body.reports ?? [] };
  } catch {
    return "The closures could not be read; try again shortly.";
  }
}

/** The road panel's stretch for Mark closed's extent choice (the reviewers' own endpoint). */
export const closureStretchPath = (wayId: number): string => `/api/closures/stretch/${wayId}`;
