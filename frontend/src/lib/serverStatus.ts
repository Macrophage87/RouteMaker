/**
 * The riders' status line (backlog 2026-11-12, "Ready for a dozen testers"; the owner, 2026-11-12: one line in Go and
 * Plan, shown only while something is wrong, no new control).
 *
 * The server keeps a small `/status.json` beside the front end only while something is down (scripts/beta/alert.sh,
 * "The riders' status line"): `{"state": "updating"}` while a release is deployed, `{"state": "degraded", "parts":
 * [...]}` while the 10-minute check sees route planning, the trail graphs or place search failing. nginx serves it even
 * while the api is stopped, so it can say "Updating" when the planner itself says nothing useful. Any other answer (the
 * usual 404, the PC's Caddy handing back the page, no network) means no line.
 *
 * Read at open, when the page comes back to the front, when a plan or search fails, and every minute while a line is
 * shown, so the line goes once the fault does.
 */

import { t } from "./i18n.ts";

export type ServerPart = "routing" | "trails" | "search";
export type ServerStatus = { state: "updating" } | { state: "degraded"; parts: ServerPart[] };

export const STATUS_URL = "/status.json";
/** How often a shown line is checked again, so it clears soon after the fault (our default). */
export const RECHECK_MS = 60_000;

const PARTS: readonly ServerPart[] = ["routing", "trails", "search"];

/** The file's text read strictly: anything unexpected is no status, never a wrong line. */
export function parseServerStatus(text: string): ServerStatus | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const state = (value as { state?: unknown }).state;
  if (state === "updating") return { state };
  if (state !== "degraded") return null;
  const raw = (value as { parts?: unknown }).parts;
  const parts = Array.isArray(raw) ? PARTS.filter((part) => raw.includes(part)) : [];
  return parts.length ? { state, parts } : null;
}

/** The one line riders see, or null. Short sentences: Go's text is translated into 20 languages. */
export function serverStatusLine(status: ServerStatus | null): string | null {
  if (!status) return null;
  if (status.state === "updating") return t("Updating. Back in a few minutes.");
  const said: string[] = [];
  if (status.parts.includes("routing")) said.push(t("Route planning is down right now."));
  else if (status.parts.includes("trails")) said.push(t("Some ride types are not working right now."));
  if (status.parts.includes("search")) said.push(t("Place search is down right now."));
  return said.join(" ") || null;
}

/** Asks the server; null for anything but a status file (404, a page, an error, no network). */
export async function fetchServerStatus(origin: string, fetcher: typeof fetch = fetch): Promise<ServerStatus | null> {
  try {
    const answer = await fetcher(`${origin}${STATUS_URL}`, { cache: "no-store", headers: { Accept: "application/json" } });
    if (!answer.ok) return null;
    return parseServerStatus(await answer.text());
  } catch {
    return null;
  }
}
