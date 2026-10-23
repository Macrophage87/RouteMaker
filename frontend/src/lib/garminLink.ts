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
  "Connect your Garmin account and Send to Garmin adds courses to Garmin Connect directly. RouteMaker can only send courses: it reads nothing from your Garmin.";
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

/** The address without the return's parameter, so a reload does not say it again. */
export function withoutReturn(search: string): string {
  const query = new URLSearchParams(search);
  query.delete(RETURN_PARAM);
  return query.size ? `?${query}` : "";
}

/** The fold's line: "Connected since Oct 23" or "Not connected". */
export function garminSummary(state: GarminState | null | undefined): string {
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
