/**
 * The AI assistant key (the owner, 2026-10-18: the MCP server "should take the created route and have it saved as one
 * of the users saved routes"; the save-only key; "other users might use different models"). Settings > Account makes,
 * shows once and removes the account's one key; an assistant's MCP server (mcp/ in the repository) sends it to add
 * routes to My routes, and it can do nothing else (core.api, /api/keyed/routes).
 */
import { csrfFromCookie } from "./stressEditor.ts";

export const KEY_LABEL = "AI assistant key";
export const KEY_HELP =
  "Lets an AI assistant that supports MCP, such as Claude, save routes it plans to My routes. The key can only add routes: it cannot sign in, read your routes or change anything else. Remove it here at any time.";
export const KEY_NONE = "None";
export const KEY_SHOWN_ONCE = "Copy it into your assistant's RouteMaker server settings now: it is shown only this once.";
export const KEY_FAILED = "That did not work; try again shortly.";
export const KEY_REMOVED = "Key removed. An assistant using it can no longer save routes.";

export interface KeyInfo {
  hint: string;
  created_at: string;
  last_used_at: string | null;
}

/** The key's line in Settings: "Ends …abcd, last used 18 Oct" or "None". */
export function keySummary(key: KeyInfo | null): string {
  if (!key) return KEY_NONE;
  const used = key.last_used_at ? `last used ${shortDate(key.last_used_at)}` : "not used yet";
  return `Ends …${key.hint}, ${used}`;
}

function shortDate(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? "before" : when.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

type Fetch = typeof fetch;
const docCookie = () => (typeof document === "undefined" ? "" : document.cookie);

function writeHeaders(cookie: string): Record<string, string> {
  const token = csrfFromCookie(cookie);
  return { Accept: "application/json", "Content-Type": "application/json", ...(token ? { "X-CSRFToken": token } : {}) };
}

/** The account's key without its secret; undefined where it could not be read. */
export async function readKey(origin: string, get: Fetch = fetch): Promise<KeyInfo | null | undefined> {
  try {
    const response = await get(`${origin}/api/me/assistant-key`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    return ((await response.json()) as { key: KeyInfo | null }).key;
  } catch {
    return undefined;
  }
}

/** A new key, replacing any other: its details and the secret, shown once; null where it failed. */
export async function makeKey(origin: string, post: Fetch = fetch, cookie = docCookie()): Promise<{ key: KeyInfo; secret: string } | null> {
  try {
    const response = await post(`${origin}/api/me/assistant-key`, { method: "POST", credentials: "same-origin", headers: writeHeaders(cookie), body: "{}" });
    if (!response.ok) return null;
    const body = (await response.json()) as { key: KeyInfo; secret: string };
    return body.key && typeof body.secret === "string" ? body : null;
  } catch {
    return null;
  }
}

export async function removeKey(origin: string, post: Fetch = fetch, cookie = docCookie()): Promise<boolean> {
  try {
    const response = await post(`${origin}/api/me/assistant-key/delete`, { method: "POST", credentials: "same-origin", headers: writeHeaders(cookie), body: "{}" });
    return response.ok;
  } catch {
    return false;
  }
}
