/**
 * The route in words (OWNER-DECISIONS 220: many blind cyclists ride as tandem
 * stokers, so what the map shows by colour and position is also written out).
 * The API's `description` entries come ready-worded (src/routemaker/describe.py:
 * US units first, the legend's tier words, one sentence each); this only lists
 * them, copies them and makes the text file. Nothing here words a stretch
 * itself, so there is one wording to keep right.
 */
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { formatDistance, milesFigure } from "./format.ts";
import { presetLabel } from "./presets.ts";

export const DESCRIPTION_HEADING = "Route description";

/** The entries to list, or null where the API gave none (an older one, or one that could not build it). */
export function descriptionEntries(route: Pick<RouteResponse, "description">): DescriptionEntry[] | null {
  const entries = route.description;
  if (!Array.isArray(entries)) return null;
  const usable = entries.filter((e) => e && typeof e.text === "string" && e.text.trim() !== "");
  return usable.length > 0 ? usable : null;
}

/** How many steps the list has, for the toggle: "12 steps", "1 step". */
export function stepCount(entries: readonly DescriptionEntry[]): string {
  return entries.length === 1 ? "1 step" : `${entries.length} steps`;
}

/**
 * The toggle's words. They do not change with the state: `aria-expanded` says
 * it, and a label that flips between "Show" and "Hide" would be said twice.
 */
export function toggleLabel(entries: readonly DescriptionEntry[]): string {
  return stepCount(entries);
}

/** The visible chevron beside the toggle: a shape, not a colour, for the state. */
export function chevron(open: boolean): string {
  return open ? "▾" : "▸";
}

/**
 * The description as text for the clipboard or a file: a line saying what
 * route it is, then one numbered line for each entry.
 */
export function descriptionText(route: Pick<RouteResponse, "preset" | "distance_m" | "description">): string {
  const entries = descriptionEntries(route) ?? [];
  const head = `RouteMaker ${presetLabel(route.preset)} route, ${formatDistance(route.distance_m)}.`;
  return [head, ...entries.map((entry, i) => `${i + 1}. ${entry.text}`)].join("\n") + "\n";
}

/** "routemaker-default-12_1-miles-description.txt", beside the GPX file's name. */
export function cueSheetFileName(route: Pick<RouteResponse, "preset" | "distance_m">): string {
  const length = milesFigure(route.distance_m).replace(".", "_");
  return `routemaker-${route.preset}-${length}-miles-description.txt`;
}

/** Whether a junction or stretch entry's severity is said in words in its text (never by colour alone). */
export function saysItsSeverity(entry: DescriptionEntry): boolean {
  if (!entry.severity && !entry.turn?.severity) return true;
  return /Higher stress|Very high stress/.test(entry.text);
}

const OPEN_KEY = "routemaker.description.open";

/** Whether the list was left open (a reader who opens it once keeps it open); closed where storage is unavailable. */
export function readOpen(storage: Pick<Storage, "getItem"> | null | undefined = safeStorage()): boolean {
  try {
    return storage?.getItem(OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeOpen(open: boolean, storage: Pick<Storage, "setItem"> | null | undefined = safeStorage()): void {
  try {
    storage?.setItem(OPEN_KEY, open ? "1" : "0");
  } catch {
    // Storage may be blocked; the list is simply closed next time.
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
