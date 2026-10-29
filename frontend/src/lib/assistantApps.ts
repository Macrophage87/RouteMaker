/**
 * Settings > Account's AI assistants: the apps the rider connected through the site's own MCP connector (core.connector;
 * the owner, 2026-10-19), each with Disconnect, and a link to how to connect one. The save-only key it once offered
 * beside them is retired (the owner, 2026-10-25: "the old method with the random token, we should take it out and just
 * link to the documentation on MCP").
 */
import { locale, t } from "./i18n.ts";
import { csrfFromCookie } from "./stressEditor.ts";

export const APPS_LABEL = t("AI assistants");
export const APPS_HELP = t("Assistant apps you allowed to plan routes and add them to My routes, such as Claude on the web or your phone.");
export const DOCS_LINK = "/about/assistants.html";
export const DOCS_WORDS = t("How to connect an assistant");
export const APPS_NONE = t("None");
export const APPS_READ_FAILED = t("Couldn't read your connected apps. Try again later.");
export const DISCONNECT_ASK = t("Disconnect this app? It can no longer plan or save routes for you until you allow it again.");
export const DISCONNECTED = t("Disconnected.");
export const DISCONNECT_FAILED = t("That did not work; try again shortly.");

export interface ConnectedApp {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

/** One app's line: "Claude, connected Oct 19, last used Oct 19". */
export function appSummary(app: ConnectedApp): string {
  const connected = shortDate(app.created_at);
  return app.last_used_at
    ? t("{name}, connected {connected}, last used {used}", { name: app.name, connected, used: shortDate(app.last_used_at) })
    : t("{name}, connected {connected}, not used yet", { name: app.name, connected });
}

/** The fold's line: how many apps are connected, or None. */
export function assistantsSummary(apps: ConnectedApp[]): string {
  if (!apps.length) return APPS_NONE;
  return apps.length === 1 ? t("1 app connected") : t("{count} apps connected", { count: apps.length });
}

function shortDate(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? t("before") : when.toLocaleDateString(locale(), { month: "short", day: "numeric" });
}

type Fetch = typeof fetch;
const docCookie = () => (typeof document === "undefined" ? "" : document.cookie);

function writeHeaders(cookie: string): Record<string, string> {
  const token = csrfFromCookie(cookie);
  return { Accept: "application/json", "Content-Type": "application/json", ...(token ? { "X-CSRFToken": token } : {}) };
}

/** The apps connected to the account; undefined where they could not be read. */
export async function readApps(origin: string, get: Fetch = fetch): Promise<ConnectedApp[] | undefined> {
  try {
    const response = await get(`${origin}/api/me/connected-apps`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    return ((await response.json()) as { apps: ConnectedApp[] }).apps;
  } catch {
    return undefined;
  }
}

/** Disconnect one app: the apps left, or null where it failed. */
export async function disconnectApp(origin: string, id: number, post: Fetch = fetch, cookie = docCookie()): Promise<ConnectedApp[] | null> {
  try {
    const response = await post(`${origin}/api/me/connected-apps/${id}/delete`, { method: "POST", credentials: "same-origin", headers: writeHeaders(cookie), body: "{}" });
    if (!response.ok) return null;
    return ((await response.json()) as { apps: ConnectedApp[] }).apps;
  } catch {
    return null;
  }
}
