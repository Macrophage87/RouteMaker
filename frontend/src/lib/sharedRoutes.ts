/**
 * Share the identical route (v0.7.0; the owner, 2026-10-15 23:19 UTC: "The ability to share a gpx identical
 * route should be in too?"). The Share button (no new control) keeps the exact line shown, verbatim like a saved
 * route or an opened GPX file (lib/savedRoutes.ts planSave and gpxSave: points in order, elevations, stops, a
 * planned route's answer or the file's own text), at POST /api/shared-routes (core.shared_routes), and the link it
 * shares carries that line's id beside the plan's inputs: `#p=...&preset=...&route=<id>`. Opened, the link shows
 * the line unchanged, as a saved route opens (App.tsx openSaved): the closure check runs, and "Update route" plans
 * the inputs again with today's map.
 *
 * The id is 128 random bits from the browser's own random source, made here so the share sheet opens inside the
 * press (it refuses to open after a wait, and the line can take a moment to send); the line is sent at the same
 * time. A line over 2 MB, or one that could not be sent, leaves the link with the plan's inputs only (as every
 * link was before), and the page says so in one line. A link whose line is not found plans again from its inputs,
 * and says so.
 *
 * Nothing of the rider is sent: no position, no account, and never the weight (OWNER-DECISIONS 313): a planned
 * answer's system weight and the effort figure weighed with it are taken out here (and again by the server).
 */
import type { RouteResponse } from "./api.ts";
import type { SaveBody, SavedRoute } from "./savedRoutes.ts";

/** The link's fragment parameter that names the shared line. */
export const SHARED_PARAM = "route";
/** The most a shared route may be (core.shared_routes.MAX_BYTES). */
export const SHARED_MAX_BYTES = 2 * 1024 * 1024;
const ID_RE = /^[0-9a-f]{32}$/;
/** How long the page waits for a shared line before planning the link's inputs instead. */
export const SHARED_READ_TIMEOUT_MS = 8000;

export const SHARED_INPUTS_ONLY = "Exact line not kept: the link plans the route again.";
export const SHARED_GONE = "Exact line gone: planned again from its points.";
export const SHARED_OPENED = (name: string) => `Opened "${name}", as it was shared.`;

/**
 * How long the server keeps a shared line (core.shared_routes.KEEP_CHOICES; the owner, 2026-10-16: "For the 1 year
 * deletion, make this the default. For other users, we can offer "keep permanently" and "delete after <date>"").
 * Chosen beside Share in Plan's More; Go always keeps the default.
 */
export type ShareKeepChoice = "year" | "forever" | "until";
export interface ShareKeep {
  keep: ShareKeepChoice;
  /** "YYYY-MM-DD", the sharer's own date; read only for "until". */
  deleteAfter: string;
}
export const SHARE_KEEP_DEFAULT: ShareKeep = { keep: "year", deleteAfter: "" };
export const SHARE_KEEP_LABEL = "Keep shared link";
export const SHARE_KEEP_OPTIONS: readonly (readonly [ShareKeepChoice, string])[] = [
  ["year", "1 year after last opened"],
  ["forever", "Permanently"],
  ["until", "Until a date"],
];
export const SHARE_DELETE_AFTER_LABEL = "Delete after";
/** The date "Until a date" starts at: a month from today. */
export const SHARE_UNTIL_DAYS = 30;

/** `days` from today, in the sharer's own time zone, as "YYYY-MM-DD". */
export function dayFromToday(days: number, now: Date = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** The keeping a share sends. "Until a date" with no date from tomorrow on keeps the default (a year). */
export function keepFields(choice: ShareKeep, now: Date = new Date()): { keep: ShareKeepChoice; delete_after?: string } {
  if (choice.keep === "until") {
    const ok = /^\d{4}-\d{2}-\d{2}$/.test(choice.deleteAfter) && choice.deleteAfter >= dayFromToday(1, now);
    return ok ? { keep: "until", delete_after: choice.deleteAfter } : { keep: "year" };
  }
  return { keep: choice.keep };
}

/** What POST /api/shared-routes takes: a saved route's body with the link's id and its keeping. */
export interface SharedBody extends Omit<SaveBody, "name"> {
  id: string;
  name: string;
  keep?: ShareKeepChoice;
  delete_after?: string;
}

/** What GET /api/shared-routes/{id} gives: what App's openSaved reads of a saved route. */
export type SharedRoute = Pick<SavedRoute, "name" | "source" | "distance_m" | "line" | "inputs" | "answer" | "gpx"> & { id: string };

/** A new id: 16 random bytes as 32 hex characters. */
export function newSharedId(fill: (bytes: Uint8Array<ArrayBuffer>) => void = (bytes) => void crypto.getRandomValues(bytes)): string {
  const bytes = new Uint8Array(16);
  fill(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The shared line's id a link names, or null. */
export function sharedIdFrom(hash: string): string | null {
  const id = new URLSearchParams(hash.replace(/^#/, "")).get(SHARED_PARAM);
  return id && ID_RE.test(id) ? id : null;
}

/** The link with the shared line's id added to its fragment (the plan's inputs stay, for a link whose line is gone). */
export function withSharedId(link: string, id: string): string {
  const at = link.indexOf("#");
  const base = at < 0 ? link : link.slice(0, at);
  const fragment = at < 0 ? "" : link.slice(at + 1);
  return `${base}#${fragment ? `${fragment}&` : ""}${SHARED_PARAM}=${id}`;
}

/** A planned answer as it may be shared: without the other candidates, the rider's weight or the effort weighed with it. */
export function publicAnswer(answer: RouteResponse): RouteResponse {
  const out: RouteResponse = { ...answer, candidates: null, avoid_alternate: null };
  if (out.dials && out.dials.system_weight_kg != null) {
    out.dials = { ...out.dials, system_weight_kg: null };
    out.effort_m = null;
  }
  return out;
}

/**
 * The body to send, as JSON, or null when it is larger than the server keeps (the link is then the inputs only).
 * `save` is what Save route would send (planSave or gpxSave), so the shared line is the saved one's.
 */
export function sharedBody(id: string, save: SaveBody, keep: ShareKeep = SHARE_KEEP_DEFAULT): { body: SharedBody; json: string } | null {
  const body: SharedBody = { ...save, id, ...(save.answer ? { answer: publicAnswer(save.answer) } : {}), ...keepFields(keep) };
  const json = JSON.stringify(body);
  return new TextEncoder().encode(json).length > SHARED_MAX_BYTES ? null : { body, json };
}

type Fetch = typeof fetch;

/** Send the line; true once it is kept. */
export async function storeShared(origin: string, json: string, post: Fetch = fetch): Promise<boolean> {
  try {
    const response = await post(`${origin}/api/shared-routes`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: json,
    });
    return response.status === 201;
  } catch {
    return false;
  }
}

function isRoute(value: unknown, id: string): value is SharedRoute {
  const r = value as Partial<SharedRoute> | null;
  return (
    !!r &&
    r.id === id &&
    (r.source === "plan" || r.source === "gpx") &&
    Array.isArray(r.line) &&
    r.line.length >= 2 &&
    typeof r.distance_m === "number" &&
    !!r.inputs &&
    typeof r.inputs.hash === "string" &&
    typeof r.name === "string"
  );
}

/** The shared line, or null when it is not kept (or cannot be had in time): the link's inputs are planned instead. */
export async function readShared(origin: string, id: string, get: Fetch = fetch, timeoutMs = SHARED_READ_TIMEOUT_MS): Promise<SharedRoute | null> {
  const abort = typeof AbortController === "undefined" ? null : new AbortController();
  const timer = abort ? setTimeout(() => abort.abort(), timeoutMs) : null;
  try {
    const response = await get(`${origin}/api/shared-routes/${id}`, { headers: { Accept: "application/json" }, credentials: "same-origin", signal: abort?.signal });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    return isRoute(body, id) ? { ...body, gpx: typeof body.gpx === "string" ? body.gpx : "", answer: body.answer ?? null } : null;
  } catch {
    return null;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** The GPX file the share sheet attaches: the text Download GPX would save, under its file name. */
export function gpxShareFile(text: string, fileName: string): File | null {
  if (typeof File === "undefined") return null;
  return new File([text], fileName, { type: "application/gpx+xml" });
}
