/**
 * Settings > Account's Wahoo connection (core.wahoo_views; the owner, 2026-10-23): connect once, and Send to Wahoo
 * adds the route, with its turn cues, to the rider's Wahoo app, which sends it to their ELEMNT. As Garmin's
 * (lib/garminLink.ts): connecting is a page visit, Wahoo sends the rider back to `/?wahoo=<outcome>`, and the
 * connection is offered only where the server has Wahoo's keys. Send to Wahoo is shown only once connected, so
 * riders who never connect see no new control.
 */
import { t } from "./i18n.ts";
import { csrfFromCookie } from "./stressEditor.ts";
import { FILES_PLUGIN, FIT_TYPE, canSendToGarmin, toBase64, type SendEnv } from "./sendToGarmin.ts";

export const CONNECT_PATH = "/auth/wahoo/start";
export const RETURN_PARAM = "wahoo";

export const WAHOO_LABEL = "Wahoo";
export const WAHOO_HELP =
  t("Connect your Wahoo account and Send to Wahoo adds routes, with turn cues, to the Wahoo app, which sends them to your ELEMNT. RouteMaker can only send routes: it reads nothing from your Wahoo but your account number.");
export const DISCONNECT_ASK = t("Disconnect Wahoo? The routes already sent stay in your Wahoo app.");
export const DISCONNECTED = t("Wahoo disconnected.");
export const READ_FAILED = t("Your Wahoo connection could not be checked just now.");
export const SEND_LABEL = t("Send to Wahoo");

/** What the page says when Wahoo sends the rider back. */
export const RETURNED: Record<string, string> = {
  connected: t("Wahoo connected. Send to Wahoo is now beside Download in the GPX section."),
  declined: t("Wahoo not connected: you did not allow it at Wahoo."),
  failed: t("Wahoo could not be connected. Try again."),
  signin: t("Sign in first, then connect Wahoo."),
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
export const ROUTE_ADDED = t("Route added to your Wahoo app. It syncs to your ELEMNT.");
export const ROUTE_UPDATED = t("Route updated in your Wahoo app. It syncs to your ELEMNT.");
export const CONNECTION_ENDED = t("Wahoo is no longer connected.");
export const UNREACHED = t("Wahoo could not be reached.");
/** After the reason: the FIT course is saved instead, for the Wahoo app to open. */
export const AS_FILE = t("The FIT course was saved instead: open it with the Wahoo app.");
export const SENDING = t("Still sending the last route.");
/** The same, in the phone app: a WebView saves no file a page makes, so the file goes to Android's "Open with" list. */
export const AS_FILE_CHOOSER = t("Choose the Wahoo app to open the FIT course instead. Not listed? Install it from Google Play, then send again.");
/** An app from before the plugin took anyApp handed it to Garmin Connect. */
export const AS_FILE_GARMIN = t("The FIT course went to Garmin Connect instead. Update the RouteMaker app to choose the Wahoo app.");
export const AS_FILE_FAILED = t("The FIT course could not be handed on either. Is the Wahoo app installed?");
/** An app from before the plugin: it can neither save nor hand on a file. */
export const AS_FILE_NONE = t("This version of the RouteMaker app cannot hand on the FIT course. Update it, or send from the website.");

/**
 * Where Wahoo did not take the route: the FIT course for the Wahoo app to open. In a browser it is saved (a download);
 * in the phone app, where a download does nothing (mobile/README.md), it goes to the RouteMakerFiles plugin as Send
 * to Garmin's does, with anyApp, so Android lists the apps that open it rather than Garmin Connect. Answers the line.
 */
export async function handWahooFile(bytes: Uint8Array<ArrayBuffer>, fileName: string, env: Pick<SendEnv, "bridge" | "save">): Promise<string> {
  if (!env.bridge) {
    env.save(bytes, FIT_TYPE, fileName);
    return AS_FILE;
  }
  if (!canSendToGarmin(env.bridge)) return AS_FILE_NONE;
  try {
    const done = (await env.bridge.nativePromise(FILES_PLUGIN, "openWith", { name: fileName, data: toBase64(bytes), anyApp: true })) as { app?: string } | null;
    return done?.app === "garmin-connect" ? AS_FILE_GARMIN : AS_FILE_CHOOSER;
  } catch {
    return AS_FILE_FAILED;
  }
}

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
