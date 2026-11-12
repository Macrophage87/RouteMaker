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
 * nothing changes without that tap. A fixed route (the owner, 2026-11-10: "save routes as an unchanging, GPX identical
 * mode. The via points are usually better, but sometimes fixed routes are more useful") is never compared, and a
 * ride on it is never re-routed: off it, the way back to the line. Only a closure on its line now offers Update route
 * ("Update route can be offered when a closure occurs on a road"). At most 200 per account. Share keeps the same body, signed out too, for the
 * link it shares (lib/sharedRoutes.ts).
 */
import { PAGE_NOTES } from "./routeNotes.ts";
import type { RouteResponse } from "./api.ts";
import { locale, t } from "./i18n.ts";
import type { Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { encodePlan } from "./planHash.ts";
import { VIA_MARKS, viaIndices } from "./pointKinds.ts";
import { presetSaid, type PresetId } from "./presets.ts";
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
  /** A fixed route: its line, never planned again (the owner, 2026-11-10); absent from an older server. */
  fixed?: boolean;
  distance_m: number;
  preset: string;
  created_at: string;
  updated_at: string;
  /** The closures in force along the line, as the server last checked (v0.7.0 closures); absent from an older server. */
  closure_alerts?: ClosureAlert[];
  /** The rider's tags (the owner, 2026-11-07); absent from an older server. */
  tags?: string[];
  /** When it was archived, or null; absent from an older server. */
  archived_at?: string | null;
  /** When it was last opened, or null if never; Load route lists the one last opened or made first. */
  opened_at?: string | null;
  /** The saved route that replaced it when it was archived for it (an assistant's save), or null. */
  replaced_by?: number | null;
  /** On a save at a full account: the archived route deleted to make room for it. */
  made_room?: { id: number; name: string };
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
  /** A fixed route (FIXED_ROUTE); left out, by its via points (our default). */
  fixed?: boolean;
  /** Saved again: a new latest version of this saved route, the one before it kept in its versions. */
  version_of?: number;
  /** The rider's tags (core.accounts.clean_tags); left out, a new version keeps the route's. */
  tags?: string[];
  /** A full account: the saved route the rider agreed to delete to make room (FULL_ASK). */
  make_room?: number;
  /** The assistant's draft this saves, by its link's id (lib/drafts.ts): no longer listed as a draft. */
  from_draft?: string;
}

/** A full account's proposal (core.api _full_account): the route unopened longest, from its creation where never
 * opened (the owner, 2026-11-07: "at 200 routes, then propose deleting the route that has the longest time since last
 * open or creation"). */
export interface RoomProposal {
  id: number;
  name: string;
  opened_at: string | null;
  created_at: string;
}

export const FULL_HEADING = t("Your account is full");
export const FULL_DELETE = t("Delete it and save");
/** The question: which route would go, and when it was last opened (or saved, never opened). */
export function fullAsk(p: RoomProposal, max = MAX_SAVED): string {
  return p.opened_at
    ? t("You have {max} saved routes. Delete \"{name}\" to save this one? You last opened it {date}.", { max: String(max), name: p.name, date: dateText(p.opened_at) })
    : t("You have {max} saved routes. Delete \"{name}\" to save this one? It was saved {date} and never opened.", { max: String(max), name: p.name, date: dateText(p.created_at) });
}

/** core.models.SavedRoute.TAGS_MAX and TAG_MAX. */
export const TAGS_MAX = 8;
export const TAG_MAX = 30;

/** Tags as typed ("Loop, trail ,loop"): split at commas, trimmed, the same tag twice kept once as first written (as
 * core.accounts.clean_tags keeps them), each cut to TAG_MAX, at most TAGS_MAX. */
export function parseTags(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(",")) {
    const tag = raw.split(/\s+/).filter(Boolean).join(" ").slice(0, TAG_MAX);
    if (!tag || seen.has(tag.toLocaleLowerCase())) continue;
    seen.add(tag.toLocaleLowerCase());
    out.push(tag);
  }
  return out.slice(0, TAGS_MAX);
}

/** The tags in use on these routes, most used first (then A to Z), each once whatever its case. */
export function tagsInUse(routes: readonly Pick<SavedSummary, "tags">[]): string[] {
  const count = new Map<string, { tag: string; n: number }>();
  for (const r of routes)
    for (const tag of r.tags ?? []) {
      const key = tag.toLocaleLowerCase();
      const had = count.get(key);
      if (had) had.n += 1;
      else count.set(key, { tag, n: 1 });
    }
  return [...count.values()].sort((a, b) => b.n - a.n || a.tag.localeCompare(b.tag)).map((c) => c.tag);
}

/** The account's tags not yet in the field that begin with what is being typed after the last comma; at most six. */
export function tagHints(offered: readonly string[], text: string): string[] {
  const parts = text.split(",");
  const part = (parts.pop() ?? "").trim().toLocaleLowerCase();
  const done = new Set(parseTags(parts.join(",")).map((x) => x.toLocaleLowerCase()));
  return offered
    .filter((x) => {
      const low = x.toLocaleLowerCase();
      return !done.has(low) && low !== part && low.startsWith(part);
    })
    .slice(0, 6);
}

/** The field with this hint taken in place of the part being typed, and a comma after it for the next. */
export function takeHint(text: string, hint: string): string {
  const parts = text.split(",");
  parts[parts.length - 1] = ` ${hint}`;
  return `${parts.join(",").replace(/^\s+/, "")}, `;
}

/** Whether a route carries this tag, whatever its case. */
export function hasTag(route: Pick<SavedSummary, "tags">, tag: string): boolean {
  const want = tag.toLocaleLowerCase();
  return (route.tags ?? []).some((t) => t.toLocaleLowerCase() === want);
}

/** The name a save offers (the plan: "defaults to 'Start to End'"). */
export function defaultRouteName(start: string | null | undefined, end: string | null | undefined): string {
  return `${start?.trim() || "Start"} to ${end?.trim() || "End"}`.slice(0, NAME_MAX);
}

/** A route's answer as a save keeps it: without the other candidates, and settled (a first route saved before Go's
 * full plan came reopens as saved, never swapped for a better one: a fixed route's line never changes). */
export function keptAnswer(route: RouteResponse): RouteResponse {
  return { ...route, candidates: null, avoid_alternate: null, closure_through: null, provisional: false };
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
    inputs: { hash: encodePlan(points, preset, dials, viaIndices(points, VIA_MARKS.isVia), undefined, undefined, "q", PAGE_NOTES.list), points: points.map(([lon, lat]) => [lon, lat] as LonLat), preset, dials },
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
    inputs: { hash: encodePlan(points, preset, dials, viaIndices(points, VIA_MARKS.isVia), undefined, undefined, "q", PAGE_NOTES.list), points: points.map(([lon, lat]) => [lon, lat] as LonLat), preset, dials },
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
  return todayM > savedM ? t("Today's map plans this route {by} longer.", { by }) : t("Today's map plans this route {by} shorter.", { by });
}

export const UPDATE_ROUTE = t("Update route");
/** Plan's Save form's box (the owner, 2026-11-10): unticked, by its via points (our default). Not in Go's Save. */
export const FIXED_ROUTE = t("Fixed route");
export const FIXED_HINT = t("Keep this exact line. Never re-routed.");
/** Plan's (i) behind the box: the two kinds side by side. */
export const FIXED_ABOUT = [
  t("Unticked (our default): the route keeps its via points, Update route is offered when the map changes, and off route a ride plans again through them."),
  t("Ticked: the line never changes, like a GPX file, and off route a ride shows the way back to it."),
];
export const OPENED_FIXED_SAID = (name: string) => t('Opened "{name}", a fixed route: it stays as saved.', { name });
export const SAVE_ROUTE = t("Save route");
/** Go's chip shows this; it is named SAVE_ROUTE (the words shown are in the name). */
export const SAVE_SHORT = t("Save");
export const MY_ROUTES = t("My routes");
/** The saved routes' heading under My routes (YourRoutes.tsx), beside the routes kept for offline. */
export const ACCOUNT_ROUTES = t("Saved to your account");
export const SAVED_SAID = (name: string) => t('Saved "{name}" to My routes.', { name });
export const SAVE_FAILED = t("The route was not saved; try again shortly.");
/** Said after a save at a full account deleted the longest-archived route to make room. */
export const MADE_ROOM_SAID = (name: string) => t('Deleted "{name}", archived longest, to make room.', { name });
/** The line a save says: Saved, and what made room for it if anything did. */
export function savedLine(name: string, route: Pick<SavedSummary, "made_room">): string {
  return route.made_room ? `${SAVED_SAID(name)} ${MADE_ROOM_SAID(route.made_room.name)}` : SAVED_SAID(name);
}
export const NONE_SAVED = t("No saved routes yet. Plan a route and press Save route.");
export const OPENED_SAID = (name: string) => t('Opened "{name}", as it was saved.', { name });
export const VERSION_SAID = (name: string) => `Saved a new version of "${name}"; the one before it is in its versions.`;
/** Saved again with nothing to keep: a file's own text unchanged (what a saved file keeps, whatever the plan on it), or the plan. */
export const UNCHANGED_SAID = (name: string, source: SavedSource = "plan") =>
  source === "gpx" ? `"${name}" is saved as it was: this route's file hasn't changed.` : `"${name}" is saved as it is; nothing changed.`;

/** "12 of 200 saved." */
export function countLine(n: number, max = MAX_SAVED): string {
  return `${n} of ${max} saved.`;
}

/**
 * A row's details: "4.7 mi (7.6 km) · Gravel · Saved Oct 15, 2026" (US units first). The ride type a plan was saved with
 * is named (backlog 2026-11-12, Plan); a file's is not, since a file is the line it holds whatever the type.
 */
export function rowDetails(route: Pick<SavedSummary, "distance_m" | "created_at" | "source" | "fixed"> & { preset?: string }): string {
  const date = new Date(route.created_at);
  const when = Number.isNaN(date.getTime()) ? "" : ` · ${t("Saved {date}", { date: date.toLocaleDateString(locale(), { month: "short", day: "numeric", year: "numeric" }) })}`;
  const ride = route.source !== "gpx" && route.preset ? ` · ${presetSaid(route.preset as PresetId)}` : "";
  const kind = `${ride}${route.source === "gpx" ? " · GPX file" : ""}${route.fixed ? ` · ${t("Fixed")}` : ""}`;
  return `${formatDistance(route.distance_m)}${kind}${when}`;
}

// ---- versions: a route saved again with changes keeps what it was, up to 20 (Plan's My routes) -------

export const VERSIONS_MAX = 20;

/** The saved route on screen: opened from My routes, or saved last. */
export interface OpenSaved {
  id: number;
  name: string;
  /** Its tags, offered again when it is saved again in Plan. */
  tags?: string[];
  /** A fixed route: the Save form's box starts ticked when it is saved again. */
  fixed?: boolean;
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
  /** A fixed route at that version; absent from an older server. */
  fixed?: boolean;
  /** What changed from the version before it, in a phrase ("Stop added"); empty when not known. */
  change: string;
}

function dateText(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(locale(), { month: "short", day: "numeric", year: "numeric" });
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

export type SaveOutcome = { ok: true; route: SavedSummary; versioned?: boolean } | { ok: false; full: boolean; notFound?: true; message: string; propose?: RoomProposal };

export async function saveRoute(origin: string, body: SaveBody, post: Fetch = fetch, cookie = docCookie()): Promise<SaveOutcome> {
  try {
    const response = await post(`${origin}/api/me/routes`, { method: "POST", credentials: "same-origin", headers: headers(cookie), body: JSON.stringify(body) });
    const answer = (await response.json().catch(() => ({}))) as { error?: string; code?: string; versioned?: boolean; propose?: RoomProposal } & SavedSummary;
    if (response.ok) return { ok: true, route: answer, ...(typeof answer.versioned === "boolean" ? { versioned: answer.versioned } : {}) };
    return {
      ok: false,
      full: answer.code === "full",
      ...(answer.code === "not_found" ? { notFound: true } : {}),
      ...(answer.code === "full" && answer.propose && typeof answer.propose.id === "number" ? { propose: answer.propose } : {}),
      message: answer.error || SAVE_FAILED,
    };
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
  return open && open.id === id ? { ...open, name: name.trim().slice(0, NAME_MAX) } : open;
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

/** Change a saved route's tags, or archive (true) or restore (false) it; resolves to the route as it now is, or null. */
export async function changeRoute(origin: string, id: number, change: { tags?: string[]; archived?: boolean }, send: Fetch = fetch, cookie = docCookie()): Promise<SavedSummary | null> {
  try {
    const response = await send(`${origin}/api/me/routes/${id}`, { method: "PATCH", credentials: "same-origin", headers: headers(cookie), body: JSON.stringify(change) });
    return response.ok ? ((await response.json()) as SavedSummary) : null;
  } catch {
    return null;
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
