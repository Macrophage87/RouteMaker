/**
 * Routes kept for offline (WEB-NAV-plan.md section 8 "Offline route", phase P3; OWNER-DECISIONS
 * 465a): the pure part. The browser's side (IndexedDB, Cache Storage) is lib/offlineRouteStore.ts.
 *
 * What a kept route is: the plan (the link's fragment, which reopens it), the API's answer for it, and
 * the map along it (the stress tiles, the base map's byte ranges, the style's glyphs and sprite), so
 * the installed app opens it with no signal. Kept on this device until the rider removes it, never sent
 * anywhere; listed in Settings with Remove. 465a's exception covers a route whose start came from
 * "Use my location" too: the plan's points are what the link already holds, and no position from a
 * ride is ever kept (no breadcrumb, no progress).
 *
 * Two ways in:
 * - "Keep for offline" under a route (any browser; the press also asks `navigator.storage.persist()`).
 * - The last ride's route, kept automatically at Start ride when the app runs installed (465a: "the
 *   installed app may keep the last route"), and given the ride's own corridor at End ride, so nothing
 *   is fetched twice. One "last ride" at a time: the next ride replaces it.
 *
 * Tiles are shared between routes that overlap (the header and directories of the base map by every
 * one), so a removal deletes only what no remaining route uses (`orphans`).
 */
import type { Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { encodePlan } from "./planHash.ts";
import type { PresetId } from "./presets.ts";

/** At most this many routes kept by the rider; the last ride is one more, replaced by the next. */
export const MAX_KEPT = 10;
/** The last ride's id: one at a time. */
export const LAST_RIDE_ID = "last-ride";

export interface KeptRoute<Answer = unknown> {
  /** The plan's fragment for a kept route (keeping the same plan again replaces it), LAST_RIDE_ID for the last ride. */
  id: string;
  /** The link's fragment, "#p=...&preset=..." (planHash.ts encodePlan): what Open puts in the address bar. */
  plan: string;
  /** "Union Station to Dupont Circle". */
  title: string;
  distanceM: number;
  /** When it was kept (ms since 1970): a time, never a place. */
  savedAt: number;
  lastRide: boolean;
  /** The API's answer for the plan, shown as it was when the network is not there. */
  answer: Answer;
  /** The Cache Storage entries it uses (stress tiles, glyphs, sprite), by URL. */
  tiles: string[];
  /** The base map's byte ranges it uses, by key ("offset:length"). */
  ranges: string[];
  /** About how many bytes its own fetches added. */
  bytes: number;
  /** Whether the map along it was all kept (false: some of it, or still being fetched). */
  complete: boolean;
}

export function keptId(plan: string, lastRide: boolean): string {
  return lastRide ? LAST_RIDE_ID : plan;
}

/** The Settings list's order: the last ride first, then the newest first. */
export function sortKept<T extends KeptRoute>(routes: readonly T[]): T[] {
  return [...routes].sort((a, b) => Number(b.lastRide) - Number(a.lastRide) || b.savedAt - a.savedAt);
}

/** Whether a route for `plan` may be kept: replacing one already kept is always allowed. */
export function canKeep(routes: readonly KeptRoute[], id: string): boolean {
  return id === LAST_RIDE_ID || routes.some((r) => r.id === id) || routes.filter((r) => !r.lastRide).length < MAX_KEPT;
}

/**
 * Whether a browser tab offers "Keep for offline" too. OWNER-DECISIONS 465a names the installed app;
 * the owner may yet allow tabs (PLAN.md FOLLOWUP-WEB-NAV): this is the one switch.
 */
export const KEEP_IN_BROWSER_TAB = false;

/** Whether "Keep for offline" is offered: in the installed app (running standalone), or in a tab when allowed. */
export function keepOffered(standalone: boolean, inTab: boolean = KEEP_IN_BROWSER_TAB): boolean {
  return standalone || inTab;
}

/**
 * The key a route is kept and looked up under: the routed plan's link, without Mass Ride's ride size
 * (never sent to the planner: App.tsx plans from the dials without it), so a keep, the last ride,
 * Settings' Open and the planner's offline lookup all agree.
 */
export function keptPlanKey(points: readonly LonLat[], preset: PresetId, dials: Dials): string {
  const { rideSize: _unsent, ...sent } = dials;
  return encodePlan(points, preset, sent);
}

/** The kept answer for a plan with no network: a kept route of that plan first, else the last ride's. */
export function keptFor<T extends KeptRoute>(routes: readonly T[], plan: string): T | undefined {
  const matching = routes.filter((r) => r.plan === plan);
  return matching.find((r) => !r.lastRide) ?? matching[0];
}

/**
 * A route's record at the start of a keep. Keeping a plan again keeps the tiles and ranges its record
 * already names until the new walk has named them too (they are not fetched twice), so a keep cut short
 * never leaves what was kept before unnamed, and so unfreeable.
 */
export function keptRecord<A>(
  fields: { id: string; plan: string; title: string; distanceM: number; answer: A; lastRide: boolean },
  existing: KeptRoute<A> | undefined,
  now: number,
): KeptRoute<A> {
  return {
    ...fields,
    savedAt: now,
    tiles: existing ? [...existing.tiles] : [],
    ranges: existing ? [...existing.ranges] : [],
    bytes: existing?.bytes ?? 0,
    complete: false,
  };
}

/**
 * The record written as a keep goes, at most once every `everyMs` (each write carries the whole answer),
 * and once more at the end, so what was fetched is named by a record however the keep ends.
 */
export function progressSaver(save: () => Promise<void>, everyMs: number, now: () => number = Date.now) {
  let last = now();
  let pending: Promise<void> | null = null;
  return {
    /** Something was kept: write the record if the last write is old enough and none is under way. */
    noted(): void {
      if (pending || now() - last < everyMs) return;
      last = now();
      pending = save()
        .catch(() => undefined)
        .finally(() => {
          pending = null;
        });
    },
    /** The keep ended: wait for a write under way, then write the final record. */
    async flush(): Promise<void> {
      await pending;
      await save();
    },
  };
}

/**
 * What the store holds that no kept route names (a keep cut short before its record was written, a
 * removal that failed half way): the sweep deletes these. `norm` spells a tile URL as the store does
 * (Cache Storage keys are absolute).
 */
export function unreferenced(
  routes: readonly KeptRoute[],
  tileKeys: readonly string[],
  rangeKeys: readonly string[],
  norm: (url: string) => string = (url) => url,
): { tiles: string[]; ranges: string[] } {
  const usedTiles = new Set(routes.flatMap((r) => r.tiles.map(norm)));
  const usedRanges = new Set(routes.flatMap((r) => r.ranges));
  return {
    tiles: tileKeys.filter((t) => !usedTiles.has(norm(t))),
    ranges: rangeKeys.filter((k) => !usedRanges.has(k)),
  };
}

/** What a removal frees: the tiles and ranges `removed` uses that no remaining route does. */
export function orphans(removed: KeptRoute, remaining: readonly KeptRoute[]): { tiles: string[]; ranges: string[] } {
  const usedTiles = new Set(remaining.flatMap((r) => r.tiles));
  const usedRanges = new Set(remaining.flatMap((r) => r.ranges));
  return {
    tiles: [...new Set(removed.tiles)].filter((t) => !usedTiles.has(t)),
    ranges: [...new Set(removed.ranges)].filter((k) => !usedRanges.has(k)),
  };
}

/** A route's name from its first and last points' names (the planner's), or Start and End. */
export function routeTitle(start: string | undefined, end: string | undefined, loop: boolean): string {
  const from = start?.trim() || "Start";
  if (loop) return `Loop from ${from}`;
  return `${from} to ${end?.trim() || "End"}`;
}

/** "Oct 10" (this year) or "Oct 10, 2025". */
export function keptDate(savedAt: number, now: number = Date.now()): string {
  const at = new Date(savedAt);
  const sameYear = at.getFullYear() === new Date(now).getFullYear();
  return at.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}

/** "12 MB", "800 KB": a rough size, for the Settings list. */
export function sizeText(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** The second line of a kept route's row: "4.7 mi (7.6 km). Last ride, kept Oct 10. About 12 MB." */
export function keptDetail(route: KeptRoute, now: number = Date.now()): string {
  const when = `${route.lastRide ? "Last ride, kept" : "Kept"} ${keptDate(route.savedAt, now)}`;
  const map = route.complete ? "" : " Part of the map along it is not saved.";
  return `${formatDistance(route.distanceM)}. ${when}. About ${sizeText(route.bytes)}.${map}`;
}

// ---- Words -----------------------------------------------------------------------------------------

export const KEEP_LABEL = "Keep for offline";
export const KEPT_HEADING = "Routes kept for offline";
export const KEPT_NONE =
  "No routes are kept. Under a route, press “Keep for offline” to keep it and the map along it on this device for places with no signal.";
export const KEPT_PRIVATE = "Kept on this device only, until you remove them; never sent anywhere.";

/** Below the list: what `navigator.storage.persisted()` said, and the iOS seven-day rule for a tab. */
export function storageNote(persisted: boolean | null, installed: boolean): string {
  const tab = installed ? "" : " In a browser tab, Safari may clear them after seven days without a visit; the installed app keeps them.";
  if (persisted === true) return `Your browser will keep them until you remove them.${tab}`;
  return `Your browser may clear them if the device runs short of space.${tab}`;
}

export type KeepOutcome = "kept" | "partial" | "no-map" | "full" | "failed";

/** What a keep press says (polite) when it ends. */
export function keepSaid(outcome: KeepOutcome, title: string): string {
  switch (outcome) {
    case "kept":
      return `Kept for offline: ${title}, with the map along it. Open it from Settings when there is no signal.`;
    case "partial":
      return `Kept for offline: ${title}, with the map along the first part of it. Open it from Settings when there is no signal.`;
    case "no-map":
      return `Kept ${title} for offline, but the map along it could not be saved; it needs a signal to show the map.`;
    case "full":
      return `${MAX_KEPT} routes are kept, the most this app keeps. Remove one in Settings first.`;
    default:
      return "The route could not be kept: this browser refused to store it.";
  }
}

export const KEEPING_SAID = "Keeping the route and the map along it…";

/** The planner's notice when the network is gone and a kept route answers. */
export function offlineRouteNotice(route: KeptRoute, now: number = Date.now()): string {
  return `No signal: this is the route you kept on ${keptDate(route.savedAt, now)}. It may be out of date; plan again when you have a signal.`;
}

export function removedSaid(title: string, left: number): string {
  return `Removed ${title}. ${left === 0 ? "No routes are kept." : left === 1 ? "1 route is kept." : `${left} routes are kept.`}`;
}

/** Remove failed (storage refused): the route is still kept. */
export function removeFailedSaid(title: string): string {
  return `Could not remove ${title}. It is still kept; try again.`;
}

/** Where the focus goes after a removal: the next row's Remove, else the previous row's, else the heading. */
export function focusAfterRemove(index: number, countAfter: number): { row: number } | "heading" {
  if (countAfter === 0) return "heading";
  return { row: Math.min(index, countAfter - 1) };
}
