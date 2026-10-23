/**
 * Settings > Account's Wahoo connection (core.wahoo_views; the owner, 2026-10-23): connect once, and Send to Wahoo
 * adds the route, with its turn cues, to the rider's Wahoo app, which sends it to their ELEMNT. As Garmin's
 * (lib/garminLink.ts): connecting is a page visit, Wahoo sends the rider back to `/?wahoo=<outcome>`, and the
 * connection is offered only where the server has Wahoo's keys. Send to Wahoo is shown only once connected, so
 * riders who never connect see no new control.
 */
import { csrfFromCookie } from "./stressEditor.ts";

export const CONNECT_PATH = "/auth/wahoo/start";
export const RETURN_PARAM = "wahoo";

export const WAHOO_LABEL = "Wahoo";
export const WAHOO_HELP =
  "Connect your Wahoo account and Send to Wahoo adds routes, with turn cues, to the Wahoo app, which sends them to your ELEMNT. RouteMaker can only send routes: it reads nothing from your Wahoo but your account number.";
export const DISCONNECT_ASK = "Disconnect Wahoo? The routes already sent stay in your Wahoo app.";
export const DISCONNECTED = "Wahoo disconnected.";
export const READ_FAILED = "Your Wahoo connection could not be checked just now.";
export const SEND_LABEL = "Send to Wahoo";

/** What the page says when Wahoo sends the rider back. */
export const RETURNED: Record<string, string> = {
  connected: "Wahoo connected. Send to Wahoo is now beside Download in the GPX section.",
  declined: "Wahoo not connected: you did not allow it at Wahoo.",
  failed: "Wahoo could not be connected. Try again.",
  signin: "Sign in first, then connect Wahoo.",
};

export interface WahooState {
  available: boolean;
  connected: boolean;
  connected_at: string | null;
  last_used_at: string | null;
}

/** The return's message, or null when the address carries none (or one this page does not know). */
export function wahooReturnFrom(search: string): string | null {
  const outcome = new URLSearchParams(search).get(RETURN_PARAM);
  return outcome !== null && Object.hasOwn(RETURNED, outcome) ? RETURNED[outcome] : null;
}

type Fetch = typeof fetch;
const docCookie = () => (typeof document === "undefined" ? "" : document.cookie);

/** The account's Wahoo state; undefined where it could not be read (signed out included). */
export async function readWahoo(origin: string, get: Fetch = fetch): Promise<WahooState | undefined> {
  try {
    const response = await get(`${origin}/api/me/wahoo`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    return (await response.json()) as WahooState;
  } catch {
    return undefined;
  }
}

function postJson(origin: string, path: string, body: unknown, post: Fetch, cookie: string): Promise<Response> {
  const token = csrfFromCookie(cookie);
  return post(`${origin}${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
    body: JSON.stringify(body),
  });
}

/** Disconnect: the state after, or null where it failed. */
export async function disconnectWahoo(origin: string, post: Fetch = fetch, cookie = docCookie()): Promise<WahooState | null> {
  try {
    const response = await postJson(origin, "/api/me/wahoo/delete", {}, post, cookie);
    if (!response.ok) return null;
    return (await response.json()) as WahooState;
  } catch {
    return null;
  }
}

/** What Send to Wahoo says. */
export const ROUTE_ADDED = "Route added to your Wahoo app. It syncs to your ELEMNT.";
export const ROUTE_UPDATED = "Route updated in your Wahoo app. It syncs to your ELEMNT.";
export const CONNECTION_ENDED = "Wahoo is no longer connected.";
export const UNREACHED = "Wahoo could not be reached.";
/** After the reason: the FIT course is saved instead, for the Wahoo app to open. */
export const AS_FILE = "The FIT course was saved instead: open it with the Wahoo app.";
export const SENDING = "Still sending the last route.";

export interface WahooRoute {
  name: string;
  /** [lon, lat] or [lon, lat, ele]: Wahoo asks for the start, distance and climb beside the file. */
  line: (readonly [number, number] | readonly [number, number, number])[];
  /** The FIT course, base64. */
  fit: string;
  /** The saved route on screen: sent again, its Wahoo route is updated in place. */
  saved_route: number | null;
}

/** What sending came to: the line to say, or the reason to say before the file is saved instead. */
export type WahooOutcome = { said: string } | { asFile: string };

export async function sendToWahoo(origin: string, route: WahooRoute, post: Fetch = fetch, cookie = docCookie()): Promise<WahooOutcome> {
  try {
    const response = await postJson(origin, "/api/me/wahoo/routes", route, post, cookie);
    const body = (await response.json().catch(() => ({}))) as { sent?: string; error?: string; code?: string };
    const reason = typeof body.error === "string" ? body.error.trim() : "";
    if (response.ok) return { said: body.sent === "updated" ? ROUTE_UPDATED : ROUTE_ADDED };
    if (response.status === 409 && body.code === "not_connected") return { asFile: CONNECTION_ENDED };
    if ((response.status === 502 || response.status === 400) && reason) return { asFile: reason };
    return { asFile: UNREACHED };
  } catch {
    return { asFile: UNREACHED };
  }
}
