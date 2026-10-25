/**
 * Saved routes (v0.7.0 plan, "Discord sign-in on, with saved settings and routes", item 3): signed in, "Save
 * route" next to Share keeps the exact line as planned, verbatim like a GPX track, with the plan's inputs, a
 * name and the date (POST /api/me/routes; core.models.SavedRoute). A GPX file opened in the app is saved the
 * same way, its own text kept byte for byte. "My routes" opens, renames, deletes or exports them. In Plan, a
 * route opened from My routes (or just saved) and saved again under its own name is a new version of it, the
 * one before kept (up to 20 per route); My routes lists them and restores one as the latest.
 *
 * Reopening shows the saved line unchanged. The page re-plans the same inputs with today's map only to
 * compare: if the distance differs by more than 5%, one line says so with an "Update route" link, and
 * nothing changes without that tap. At most 200 per account. Share keeps the same body, signed out too, for the
 * link it shares (lib/sharedRoutes.ts).
 */
import type { RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { encodePlan } from "./planHash.ts";
import { VIA_MARKS, viaIndices } from "./pointKinds.ts";
import type { PresetId } from "./presets.ts";
import type { ClosureAlert } from "./closureReview.ts";
import { csrfFromCookie } from "./stressEditor.ts";

export const MAX_SAVED = 200;
export const NAME_MAX = 120;
/** Past this share of the saved distance, today's map plans a different route. */
export const UPDATE_SHARE = 0.05;

export type SavedSource = "plan" | "gpx";
/** A vertex as kept: [lon, lat] or, from a GPX file, [lon, lat, elevation]. */
export type SavedVertex = [number, number] | [number, number, number];

export interface SavedInputs {
  hash: string;
  points: LonLat[];
  preset: PresetId;
  dials: Partial<Dials>;
}

export interface SavedSummary {
  id: number;
  name: string;
  source: SavedSource;
  distance_m: number;
  preset: string;
  created_at: string;
  updated_at: string;
  /** The closures in force along the line, as the server last checked (v0.7.0 closures); absent from an older server. */
  closure_alerts?: ClosureAlert[];
}

export interface SavedRoute extends SavedSummary {
  line: SavedVertex[];
  inputs: SavedInputs;
  answer: RouteResponse | null;
  gpx: string;
}

export interface SaveBody {
  name: string;
  source: SavedSource;
  line: SavedVertex[];
  distance_m: number;
  inputs: SavedInputs;
  answer?: RouteResponse | null;
  gpx?: string;
  /** Saved again: a new latest version of this saved route, the one before it kept in its versions. */
  version_of?: number;
}

/** The name a save offers (the plan: "defaults to 'Start to End'"). */
export function defaultRouteName(start: string | null | undefined, end: string | null | undefined): string {
  return `${start?.trim() || "Start"} to ${end?.trim() || "End"}`.slice(0, NAME_MAX);
}

/** A route's answer as a save keeps it: without the other candidates. */
export function keptAnswer(route: RouteResponse): RouteResponse {
  return { ...route, candidates: null, avoid_alternate: null, closure_through: null };
}

/**
 * A planned route's save: the line exactly as on screen, its answer without the other candidates. Its link keeps
 * each point's kind and each stop's own name (2026-10-24), from the page's marks, so it reopens as it was planned.
 */
export function planSave(name: string, route: RouteResponse, points: readonly LonLat[], preset: PresetId, dials: Dials): SaveBody {
  const answer = keptAnswer(route);
  return {
    name: name.trim().slice(0, NAME_MAX),
    source: "plan",
    line: route.geometry.coordinates.map(([lon, lat]) => [lon, lat] as SavedVertex),
    distance_m: route.distance_m,
    inputs: { hash: encodePlan(points, preset, dials, viaIndices(points, VIA_MARKS.isVia)), points: points.map(([lon, lat]) => [lon, lat] as LonLat), preset, dials },
    answer,
  };
}

/**
 * An opened GPX file's save: its own text and its whole track, verbatim; the plan it opened as for inputs. `shown`,
 * the route on screen for it once settled (v0.9.0, "share the exact route"): kept as its answer, so the file reopens
 * (or its shared link opens) as that very line, followed by the ride type's rules or exactly, never planned again.
 */
export function gpxSave(name: string, text: string, track: readonly SavedVertex[], points: readonly LonLat[], preset: PresetId, dials: Dials, shown: RouteResponse | null = null): SaveBody {
  let m = 0;
  for (let i = 1; i < track.length; i += 1) m += metres(track[i - 1], track[i]);
  return {
    name: name.trim().slice(0, NAME_MAX),
    source: "gpx",
    line: track.map((v) => [...v] as SavedVertex),
    distance_m: m,
    inputs: { hash: encodePlan(points, preset, dials, viaIndices(points, VIA_MARKS.isVia)), points: points.map(([lon, lat]) => [lon, lat] as LonLat), preset, dials },
    gpx: text,
    ...(shown ? { answer: keptAnswer(shown) } : {}),
  };
}

function metres(a: readonly number[], b: readonly number[]): number {
  const r = 6_371_008.8;
  const toRad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toRad;
  const dLon = (b[0] - a[0]) * toRad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * r * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Whether today's plan differs from the saved one enough to offer "Update route": more than 5% in distance. */
export function differsTooMuch(savedM: number, todayM: number): boolean {
  if (!(savedM > 0) || !(todayM > 0)) return false;
  return Math.abs(todayM - savedM) / savedM > UPDATE_SHARE;
}

/** The one line (with the "Update route" link after it): "Today's map plans this 0.8 mi (1.3 km) longer." */
export function differenceLine(savedM: number, todayM: number): string {
  const by = formatDistance(Math.abs(todayM - savedM));
  return `Today's map plans this route ${by} ${todayM > savedM ? "longer" : "shorter"}.`;
}

export const UPDATE_ROUTE = "Update route";
export const SAVE_ROUTE = "Save route";
/** Go's chip shows this; it is named SAVE_ROUTE (the words shown are in the name). */
export const SAVE_SHORT = "Save";
export const MY_ROUTES = "My routes";
export const SAVED_SAID = (name: string) => `Saved "${name}" to My routes.`;
export const SAVE_FAILED = "The route was not saved; try again shortly.";
export const NONE_SAVED = "No saved routes yet. Plan a route and press Save route.";
export const OPENED_SAID = (name: string) => `Opened "${name}", as it was saved.`;
export const VERSION_SAID = (name: string) => `Saved a new version of "${name}"; the one before it is in its versions.`;
/** Saved again with nothing to keep: a file's own text unchanged (what a saved file keeps, whatever the plan on it), or the plan. */
export const UNCHANGED_SAID = (name: string, source: SavedSource = "plan") =>
  source === "gpx" ? `"${name}" is saved as it was: this route's file hasn't changed.` : `"${name}" is saved as it is; nothing changed.`;

/** "12 of 200 saved." */
export function countLine(n: number, max = MAX_SAVED): string {
  return `${n} of ${max} saved.`;
}

/** A row's details: "4.7 mi (7.6 km) · Saved Oct 15, 2026" (US units first). */
export function rowDetails(route: Pick<SavedSummary, "distance_m" | "created_at" | "source">): string {
  const date = new Date(route.created_at);
  const when = Number.isNaN(date.getTime()) ? "" : ` · Saved ${date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
  return `${formatDistance(route.distance_m)}${route.source === "gpx" ? " · GPX file" : ""}${when}`;
}

// ---- versions: a route saved again with changes keeps what it was, up to 20 (Plan's My routes) -------

export const VERSIONS_MAX = 20;

/** The saved route on screen: opened from My routes, or saved last. */
export interface OpenSaved {
  id: number;
  name: string;
}

/**
 * Which saved route a save is a new version of: the one on screen, saved again in Plan under its own name. Any
 * other name is a new saved route, as before; Go's save is unchanged.
 */
export function versionOf(open: OpenSaved | null, name: string, inPlan: boolean): number | undefined {
  return inPlan && open && open.name === name.trim().slice(0, NAME_MAX) ? open.id : undefined;
}

export interface SavedVersion {
  /** null for the latest version: the route as it is now. */
  id: number | null;
  saved_at: string;
  distance_m: number;
  source: SavedSource;
  /** What changed from the version before it, in a phrase ("Stop added"); empty when not known. */
  change: string;
}

function dateText(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** A version's line: "Oct 15, 2026 · 4.7 mi (7.6 km) · Stop added" (US units first). */
export function versionDetails(v: Pick<SavedVersion, "saved_at" | "distance_m" | "change">): string {
  return [dateText(v.saved_at), formatDistance(v.distance_m), v.change].filter(Boolean).join(" · ");
}

export const RESTORED_SAID = (name: string, v: Pick<SavedVersion, "saved_at">) =>
  `Restored the version of "${name}" from ${dateText(v.saved_at) || "before"} as its latest, and opened it.`;
export const RESTORE_FAILED = "That version was not restored; try again shortly.";

// ---- the API -----------------------------------------------------------------------------------------

type Fetch = typeof fetch;

function headers(cookie: string, json = true): Record<string, string> {
  const token = csrfFromCookie(cookie);
  return { Accept: "application/json", ...(json ? { "Content-Type": "application/json" } : {}), ...(token ? { "X-CSRFToken": token } : {}) };
}

const docCookie = () => (typeof document === "undefined" ? "" : document.cookie);

export type SaveOutcome = { ok: true; route: SavedSummary; versioned?: boolean } | { ok: false; full: boolean; notFound?: true; message: string };

export async function saveRoute(origin: string, body: SaveBody, post: Fetch = fetch, cookie = docCookie()): Promise<SaveOutcome> {
  try {
    const response = await post(`${origin}/api/me/routes`, { method: "POST", credentials: "same-origin", headers: headers(cookie), body: JSON.stringify(body) });
    const answer = (await response.json().catch(() => ({}))) as { error?: string; code?: string; versioned?: boolean } & SavedSummary;
    if (response.ok) return { ok: true, route: answer, ...(typeof answer.versioned === "boolean" ? { versioned: answer.versioned } : {}) };
    return { ok: false, full: answer.code === "full", ...(answer.code === "not_found" ? { notFound: true } : {}), message: answer.error || SAVE_FAILED };
  } catch {
    return { ok: false, full: false, message: SAVE_FAILED };
  }
}

/**
 * A save as a new version of saved route `of` (versionOf), or a plain save without one. A route no longer in
 * the account (deleted in another tab, say) is saved as a new route instead: the save is not lost.
 */
export async function saveAsVersion(origin: string, body: SaveBody, of: number | undefined, post: Fetch = fetch, cookie = docCookie()): Promise<SaveOutcome> {
  if (of === undefined) return saveRoute(origin, body, post, cookie);
  const first = await saveRoute(origin, { ...body, version_of: of }, post, cookie);
  if (first.ok || !first.notFound) return first;
  const { version_of: _gone, ...plain } = body;
  return saveRoute(origin, plain, post, cookie);
}

/** What My routes' rename or delete leaves of the saved route on screen. */
export function afterRename(open: OpenSaved | null, id: number, name: string): OpenSaved | null {
  return open && open.id === id ? { id, name: name.trim().slice(0, NAME_MAX) } : open;
}
export function afterDelete(open: OpenSaved | null, id: number): OpenSaved | null {
  return open && open.id === id ? null : open;
}

export async function listRoutes(origin: string, get: Fetch = fetch): Promise<SavedSummary[] | null> {
  try {
    const response = await get(`${origin}/api/me/routes`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return null;
    const body = (await response.json()) as { routes?: SavedSummary[] };
    return Array.isArray(body.routes) ? body.routes : null;
  } catch {
    return null;
  }
}

export async function readRoute(origin: string, id: number, get: Fetch = fetch): Promise<SavedRoute | null> {
  try {
    const response = await get(`${origin}/api/me/routes/${id}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    return response.ok ? ((await response.json()) as SavedRoute) : null;
  } catch {
    return null;
  }
}

export async function renameRoute(origin: string, id: number, name: string, send: Fetch = fetch, cookie = docCookie()): Promise<boolean> {
  try {
    const response = await send(`${origin}/api/me/routes/${id}`, { method: "PATCH", credentials: "same-origin", headers: headers(cookie), body: JSON.stringify({ name: name.trim().slice(0, NAME_MAX) }) });
    return response.ok;
  } catch {
    return false;
  }
}

export async function deleteRoute(origin: string, id: number, send: Fetch = fetch, cookie = docCookie()): Promise<boolean> {
  try {
    const response = await send(`${origin}/api/me/routes/${id}`, { method: "DELETE", credentials: "same-origin", headers: headers(cookie, false) });
    return response.ok;
  } catch {
    return false;
  }
}

export async function listVersions(origin: string, id: number, get: Fetch = fetch): Promise<SavedVersion[] | null> {
  try {
    const response = await get(`${origin}/api/me/routes/${id}/versions`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return null;
    const body = (await response.json()) as { versions?: SavedVersion[] };
    return Array.isArray(body.versions) ? body.versions : null;
  } catch {
    return null;
  }
}

/** Make an earlier version the latest again; resolves to the route as it now is, or null. */
export async function restoreVersion(origin: string, id: number, versionId: number, send: Fetch = fetch, cookie = docCookie()): Promise<SavedRoute | null> {
  try {
    const response = await send(`${origin}/api/me/routes/${id}/versions/${versionId}/restore`, { method: "POST", credentials: "same-origin", headers: headers(cookie), body: "{}" });
    return response.ok ? ((await response.json()) as SavedRoute) : null;
  } catch {
    return null;
  }
}

/** The plan line and route a reopened planned route shows: its saved answer, unchanged. */
export function savedAnswer(route: Pick<SavedRoute, "source" | "answer">): RouteResponse | null {
  if (route.source !== "plan" || !route.answer) return null;
  return route.answer;
}
