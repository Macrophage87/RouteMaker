/**
 * Settings > Account's Garmin connection (core.garmin_views; the owner, 2026-10-23, "Keep it, encrypted"): connect
 * once, and Send to Garmin adds courses to the rider's Garmin Connect account directly. Connecting is a page visit
 * (Garmin's consent is a page); Garmin sends the rider back to `/?garmin=<outcome>`, which `garminReturnFrom` reads
 * once, so Settings can open and say what happened. Offered only where the server has Garmin's keys.
 */
import { csrfFromCookie } from "./stressEditor.ts";

export const CONNECT_PATH = "/auth/garmin/start";
export const RETURN_PARAM = "garmin";

export const GARMIN_LABEL = "Garmin";
export const GARMIN_HELP =
  "Connect your Garmin account and Send to Garmin adds courses to Garmin Connect directly. RouteMaker can only send courses: it reads nothing from your Garmin but your account number.";
export const GARMIN_CONNECTED = "Connected";
export const GARMIN_NOT_CONNECTED = "Not connected";
export const DISCONNECT_ASK = "Disconnect Garmin? Send to Garmin then hands the file to the Garmin Connect app instead.";
export const DISCONNECTED = "Garmin disconnected.";
export const FAILED = "That did not work; try again shortly.";
export const READ_FAILED = "Your Garmin connection could not be checked just now.";

/** What the page says when Garmin sends the rider back. */
export const RETURNED: Record<string, string> = {
  connected: "Garmin connected. Send to Garmin now adds courses to Garmin Connect directly.",
  declined: "Garmin not connected: you did not allow it at Garmin.",
  failed: "Garmin could not be connected. Try again.",
  signin: "Sign in first, then connect Garmin.",
};

export interface GarminState {
  available: boolean;
  connected: boolean;
  connected_at: string | null;
  last_used_at: string | null;
}

/** The return's message, or null when the address carries none (or one this page does not know). */
export function garminReturnFrom(search: string): string | null {
  const outcome = new URLSearchParams(search).get(RETURN_PARAM);
  return outcome !== null && Object.hasOwn(RETURNED, outcome) ? RETURNED[outcome] : null;
}

/** The address without the return's parameter (Garmin's, or another service's), so a reload does not say it again. */
export function withoutReturn(search: string, param = RETURN_PARAM): string {
  const query = new URLSearchParams(search);
  query.delete(param);
  return query.size ? `?${query}` : "";
}

/** The fold's line: "Connected since Oct 23" or "Not connected" (Wahoo's too, lib/wahooLink.ts). */
export function garminSummary(state: Pick<GarminState, "connected" | "connected_at"> | null | undefined): string {
  if (!state) return "…";
  if (!state.connected) return GARMIN_NOT_CONNECTED;
  const when = state.connected_at ? new Date(state.connected_at) : null;
  return when && !Number.isNaN(when.getTime())
    ? `${GARMIN_CONNECTED} since ${when.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
    : GARMIN_CONNECTED;
}

type Fetch = typeof fetch;
const docCookie = () => (typeof document === "undefined" ? "" : document.cookie);

/** The account's Garmin state; undefined where it could not be read. */
export async function readGarmin(origin: string, get: Fetch = fetch): Promise<GarminState | undefined> {
  try {
    const response = await get(`${origin}/api/me/garmin`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    return (await response.json()) as GarminState;
  } catch {
    return undefined;
  }
}

/** Disconnect: the state after, or null where it failed. */
export async function disconnectGarmin(origin: string, post: Fetch = fetch, cookie = docCookie()): Promise<GarminState | null> {
  const token = csrfFromCookie(cookie);
  try {
    const response = await post(`${origin}/api/me/garmin/delete`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: "{}",
    });
    if (!response.ok) return null;
    return (await response.json()) as GarminState;
  } catch {
    return null;
  }
}

/** What Send to Garmin says when it went through the connection (core.garmin_courses). */
export const COURSE_ADDED = "Course added to Garmin Connect. It syncs to your Garmin.";
export const COURSE_UPDATED = "Course updated in Garmin Connect. It syncs to your Garmin.";
export const CONNECTION_ENDED = "Garmin is no longer connected, so the course went as a file.";
export const COURSE_FAILED_FILE = "Garmin could not be reached, so the course went as a file.";
/** After Garmin's own reason (the server's words): the file goes instead. */
export const AS_FILE = "It went as a file instead.";
export const SENDING = "Still sending the last course.";

export interface DirectCourse {
  name: string;
  preset: string;
  /** [lon, lat] or [lon, lat, ele]: Garmin works out the turns from the line. */
  line: (readonly [number, number] | readonly [number, number, number])[];
  /** The saved route on screen: sent again, its course is updated in place. */
  saved_route: number | null;
}

/** What sending through the connection came to: the line to say, or the line to say before handing the file on. */
export type DirectOutcome = { said: string } | { asFile: string };

/**
 * Send the course through the connection. Sent, it says so. Otherwise (not connected any more, refused by Garmin or
 * for the line itself, or not reached at all) the caller hands the file on instead, after the reason.
 */
export async function sendDirect(origin: string, course: DirectCourse, post: Fetch = fetch, cookie = docCookie()): Promise<DirectOutcome> {
  const token = csrfFromCookie(cookie);
  try {
    const response = await post(`${origin}/api/me/garmin/courses`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: JSON.stringify(course),
    });
    const body = (await response.json().catch(() => ({}))) as { sent?: string; error?: string; code?: string };
    const reason = typeof body.error === "string" ? body.error.trim() : "";
    if (response.ok) return { said: body.sent === "updated" ? COURSE_UPDATED : COURSE_ADDED };
    if (response.status === 409 && body.code === "not_connected") return { asFile: CONNECTION_ENDED };
    // The reason in the server's words: Garmin's refusal (its permission, too many courses, the course not read) or
    // the line's (too many points; the file is fitted to the unit, lib/course.ts).
    if ((response.status === 502 || response.status === 400) && reason) return { asFile: `${reason} ${AS_FILE}` };
    return { asFile: COURSE_FAILED_FILE };
  } catch {
    return { asFile: COURSE_FAILED_FILE };
  }
}
