/**
 * Saved routes (v0.7.0 plan, "Discord sign-in on, with saved settings and routes", item 3): signed in, "Save
 * route" next to Share keeps the exact line as planned, verbatim like a GPX track, with the plan's inputs, a
 * name and the date (POST /api/me/routes; core.models.SavedRoute). A GPX file opened in the app is saved the
 * same way, its own text kept byte for byte. "My routes" opens, renames, deletes or exports them.
 *
 * Reopening shows the saved line unchanged. The page re-plans the same inputs with today's map only to
 * compare: if the distance differs by more than 5%, one line says so with an "Update route" link, and
 * nothing changes without that tap. At most 200 per account; sharing stays the link in the address bar.
 */
import type { RouteResponse } from "./api.ts";
import type { Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { encodePlan } from "./planHash.ts";
import type { PresetId } from "./presets.ts";
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
}

/** The name a save offers (the plan: "defaults to 'Start to End'"). */
export function defaultRouteName(start: string | null | undefined, end: string | null | undefined): string {
  return `${start?.trim() || "Start"} to ${end?.trim() || "End"}`.slice(0, NAME_MAX);
}

/** A planned route's save: the line exactly as on screen, its answer without the other candidates. */
export function planSave(name: string, route: RouteResponse, points: readonly LonLat[], preset: PresetId, dials: Dials): SaveBody {
  const answer: RouteResponse = { ...route, candidates: null, avoid_alternate: null };
  return {
    name: name.trim().slice(0, NAME_MAX),
    source: "plan",
    line: route.geometry.coordinates.map(([lon, lat]) => [lon, lat] as SavedVertex),
    distance_m: route.distance_m,
    inputs: { hash: encodePlan(points, preset, dials), points: points.map(([lon, lat]) => [lon, lat] as LonLat), preset, dials },
    answer,
  };
}

/** An opened GPX file's save: its own text and its whole track, verbatim; the plan it opened as for inputs. */
export function gpxSave(name: string, text: string, track: readonly SavedVertex[], points: readonly LonLat[], preset: PresetId, dials: Dials): SaveBody {
  let m = 0;
  for (let i = 1; i < track.length; i += 1) m += metres(track[i - 1], track[i]);
  return {
    name: name.trim().slice(0, NAME_MAX),
    source: "gpx",
    line: track.map((v) => [...v] as SavedVertex),
    distance_m: m,
    inputs: { hash: encodePlan(points, preset, dials), points: points.map(([lon, lat]) => [lon, lat] as LonLat), preset, dials },
    gpx: text,
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
export const MY_ROUTES = "My routes";
export const SAVED_SAID = (name: string) => `Saved "${name}" to My routes.`;
export const SAVE_FAILED = "The route was not saved; try again shortly.";
export const NONE_SAVED = "No saved routes yet. Plan a route and press Save route.";
export const OPENED_SAID = (name: string) => `Opened "${name}", as it was saved.`;

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

// ---- the API -----------------------------------------------------------------------------------------

type Fetch = typeof fetch;

function headers(cookie: string, json = true): Record<string, string> {
  const token = csrfFromCookie(cookie);
  return { Accept: "application/json", ...(json ? { "Content-Type": "application/json" } : {}), ...(token ? { "X-CSRFToken": token } : {}) };
}

const docCookie = () => (typeof document === "undefined" ? "" : document.cookie);

export type SaveOutcome = { ok: true; route: SavedSummary } | { ok: false; full: boolean; message: string };

export async function saveRoute(origin: string, body: SaveBody, post: Fetch = fetch, cookie = docCookie()): Promise<SaveOutcome> {
  try {
    const response = await post(`${origin}/api/me/routes`, { method: "POST", credentials: "same-origin", headers: headers(cookie), body: JSON.stringify(body) });
    const answer = (await response.json().catch(() => ({}))) as { error?: string; code?: string } & SavedSummary;
    if (response.ok) return { ok: true, route: answer };
    return { ok: false, full: answer.code === "full", message: answer.error || SAVE_FAILED };
  } catch {
    return { ok: false, full: false, message: SAVE_FAILED };
  }
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

/** The plan line and route a reopened planned route shows: its saved answer, unchanged. */
export function savedAnswer(route: SavedRoute): RouteResponse | null {
  if (route.source !== "plan" || !route.answer) return null;
  return route.answer;
}
