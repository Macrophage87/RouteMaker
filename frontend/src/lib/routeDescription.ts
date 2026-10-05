/**
 * The route in words (OWNER-DECISIONS 220: many blind cyclists ride as tandem
 * stokers, so what the map shows by colour and position is also written out).
 * The API's `description` entries come ready-worded (src/routemaker/describe.py:
 * US units first, the legend's tier words, one sentence each); this only lists
 * them, copies them and makes the text file. Nothing here words a stretch
 * itself, so there is one wording to keep right.
 */
import type { DescriptionCrossing, DescriptionEntry, RouteResponse } from "./api.ts";
import { formatDistance, milesFigure } from "./format.ts";
import { presetLabel } from "./presets.ts";
import { capacityDescription, capacitySummary } from "./massCapacity.ts";
import { HIGH_STRESS_LANE_MIN_TIER, highStressLanesOn } from "../stressStyle.js";

export const DESCRIPTION_HEADING = "Route description";

/**
 * The two views (OWNER-DECISIONS 226): the overview merges stretches under a
 * quarter of a mile into their neighbours, never hiding a busy stretch or a
 * flagged junction and never spanning a stop; "full" lists every entry.
 */
export type DescriptionView = "overview" | "full";

type Described = Pick<RouteResponse, "description"> & Partial<Pick<RouteResponse, "description_overview">>;

function usableEntries(entries: unknown): DescriptionEntry[] | null {
  if (!Array.isArray(entries)) return null;
  const usable = entries.filter((e) => e && typeof e.text === "string" && e.text.trim() !== "");
  return usable.length > 0 ? usable : null;
}

/**
 * The entries to list in a view, or null where the API gave none (an older
 * one, or one that could not build it). An answer without an overview (an older
 * API) lists the full description in either view.
 */
export function descriptionEntries(
  route: Described,
  view: DescriptionView = "overview",
  showHighStressLanes: boolean = highStressLanesOn(),
): DescriptionEntry[] | null {
  const full = usableEntries(route.description);
  const entries = view === "full" ? full : (usableEntries(route.description_overview) ?? full);
  return entries && !showHighStressLanes ? entries.map(withoutHighStressLane) : entries;
}

/**
 * The words an older API adds after a stretch's tier for a painted lane
 * (src/routemaker/describe.py: ", " and FACILITY_WORDS["lane"]; the
 * cross-language test in tests/test_describe.py, TestFrontEndAgrees, holds
 * the two equal).
 */
export const PAINTED_LANE_WORDS = ", painted bike lane";

/**
 * A stretch on LTS 4 or Avoid is not called a bike lane while the "Show bike
 * lanes on high-stress roads" switch is off (OWNER-DECISIONS 275): the entry
 * loses its painted-lane words and its facility. Any other entry is returned
 * as it is.
 *
 * The API words it (describe.py, `text_lanes_hidden`): the text as it reads
 * with those lanes not called bike lanes, or null where that is the text
 * itself - an overview stretch that merges an LTS 3 lane with an LTS 4 one
 * keeps its lane, as the facility bar counts the LTS 3 part. Only an older
 * API, without the field, has the words taken out here.
 */
export function withoutHighStressLane(entry: DescriptionEntry): DescriptionEntry {
  if ("text_lanes_hidden" in entry && entry.text_lanes_hidden !== undefined) {
    return typeof entry.text_lanes_hidden === "string" ? { ...entry, facility: null, text: entry.text_lanes_hidden } : entry;
  }
  if (entry.facility !== "lane" || typeof entry.tier !== "number" || entry.tier < HIGH_STRESS_LANE_MIN_TIER) return entry;
  return { ...entry, facility: null, text: entry.text.split(PAINTED_LANE_WORDS).join("") };
}

/**
 * The one sentence said at the top of the description when the lane switch hid a
 * painted lane in it (the a11y review's N9): otherwise the hiding is silent.
 */
export const LANES_HIDDEN_NOTE =
  "Painted lanes on heavy-traffic roads are not listed; turn on Show bike lanes on high-stress roads to include them.";

/** LANES_HIDDEN_NOTE where some entry of the view was reworded by the switch, else null. */
export function lanesHiddenNote(
  route: Described,
  view: DescriptionView = "overview",
  showHighStressLanes: boolean = highStressLanesOn(),
): string | null {
  if (showHighStressLanes) return null;
  const shown = descriptionEntries(route, view, true) ?? [];
  return shown.some((entry) => withoutHighStressLane(entry) !== entry) ? LANES_HIDDEN_NOTE : null;
}

/** Whether the overview is shorter than the full list: only then is there a choice to offer. */
export function hasOverview(route: Described): boolean {
  const full = descriptionEntries(route, "full");
  const short = descriptionEntries(route, "overview");
  return full !== null && short !== null && short.length < full.length;
}

/** The view that applies to a route: the full list where there is no shorter one. */
export function viewFor(route: Described, view: DescriptionView): DescriptionView {
  return hasOverview(route) ? view : "full";
}

/** How many steps the list has, for the toggle: "12 steps", "1 step". */
export function stepCount(entries: readonly DescriptionEntry[]): string {
  return entries.length === 1 ? "1 step" : `${entries.length} steps`;
}

/**
 * The toggle's words. They do not change with the state: `aria-expanded` says
 * it, and a label that flips between "Show" and "Hide" would be said twice.
 */
export function toggleLabel(entries: readonly DescriptionEntry[], view: DescriptionView = "full", choice = false): string {
  if (!choice) return stepCount(entries);
  return `${stepCount(entries)}, ${view === "full" ? "full detail" : "overview"}`;
}

/**
 * The toggle's accessible name: what it opens, then its visible words ("Route
 * description: 11 steps, overview"), so a reader who Tabs to it hears what it is
 * (a11y re-check of 2b0cf00). The visible words lead nothing but are all in it (2.5.3).
 */
export function toggleName(entries: readonly DescriptionEntry[], view: DescriptionView = "full", choice = false): string {
  return `${DESCRIPTION_HEADING}: ${toggleLabel(entries, view, choice)}`;
}

/**
 * A group entry's crossings, each with its mile marker (OWNER-DECISIONS 248): in the
 * full description only; none on any other entry, or from an older API.
 */
export function crossingsOf(entry: DescriptionEntry): DescriptionCrossing[] {
  const crossings = entry.group?.crossings;
  if (!Array.isArray(crossings)) return [];
  return crossings.filter((c) => c && typeof c.text === "string" && c.text.trim() !== "");
}

/**
 * The entries as numbered text lines, one entry to a line, and a group's crossings
 * under it, set in and numbered within it ("   3.1. At 1.0 mi ...").
 */
export function entryLines(entries: readonly DescriptionEntry[]): string[] {
  const lines: string[] = [];
  entries.forEach((entry, i) => {
    lines.push(`${i + 1}. ${entry.text}`);
    crossingsOf(entry).forEach((crossing, k) => lines.push(`   ${i + 1}.${k + 1}. ${crossing.text}`));
  });
  return lines;
}

/** The visible chevron beside the toggle: a shape, not a colour, for the state. */
export function chevron(open: boolean): string {
  return open ? "▾" : "▸";
}

/**
 * The description as text for the clipboard or a file: a line saying what
 * route it is, then one numbered line for each entry (and, in full detail, a
 * group's crossings under it: `entryLines`).
 */
export function descriptionText(
  route: Pick<RouteResponse, "preset" | "distance_m"> & Described & Partial<Pick<RouteResponse, "stress_spans" | "profile">>,
  view: DescriptionView = "overview",
): string {
  const shown = viewFor(route, view);
  const entries = descriptionEntries(route, shown) ?? [];
  // Which view it is, said only where there is a choice of two.
  const which = hasOverview(route) ? (shown === "full" ? " Full detail." : " Overview, short stretches merged.") : "";
  const head = `RouteMaker ${presetLabel(route.preset)} route, ${formatDistance(route.distance_m)}.${which}`;
  const lead = capacityLead(route);
  return [head, ...(lead ? [lead] : []), ...entryLines(entries)].join("\n") + "\n";
}

/**
 * A Mass Ride's lead sentence (OWNER-DECISIONS 325: riders per minute in place of the LTS breakdown): the
 * narrowest points, on the flat and with the hills (424), and the share of the distance in each band, in words. Null on every other ride type, and
 * where the route has no capacity figures (an older table), which keep the description as it was.
 */
export function capacityLead(route: Partial<Pick<RouteResponse, "stress_spans" | "profile">>): string | null {
  const summary = capacitySummary(route.stress_spans);
  return summary ? capacityDescription(summary, route.profile?.flow) : null;
}

/** The most of the description the GPX file carries in full; beyond it, the overview. */
export const GPX_FULL_MAX_CHARS = 4000;

/**
 * The description for the GPX route's `<desc>` (OWNER-DECISIONS 225): plain
 * text, one numbered entry to a line. The full text where it is short enough
 * for a device to show (GPX_FULL_MAX_CHARS), else the overview (never the
 * rider's screen view: a file is read elsewhere). Empty where there is none.
 */
export function gpxDescriptionText(route: Described & Partial<Pick<RouteResponse, "stress_spans">>): string {
  const full = descriptionEntries(route, "full");
  if (full === null) return "";
  const lines = entryLines;
  const fullText = lines(full).join("\n");
  const useFull = !hasOverview(route) || fullText.length <= GPX_FULL_MAX_CHARS;
  const entries = useFull ? full : (descriptionEntries(route, "overview") ?? full);
  const label = hasOverview(route) ? (useFull ? "Route description, full detail:" : "Route description, overview:") : "Route description:";
  const lead = capacityLead(route);
  return [label, ...(lead ? [lead] : []), ...lines(entries)].join("\n");
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
const VIEW_KEY = "routemaker.description.view";

/** The view the rider chose, remembered; the overview where nothing is stored or storage fails. */
export function readView(storage: Pick<Storage, "getItem"> | null | undefined = safeStorage()): DescriptionView {
  try {
    return storage?.getItem(VIEW_KEY) === "full" ? "full" : "overview";
  } catch {
    return "overview";
  }
}

export function writeView(view: DescriptionView, storage: Pick<Storage, "setItem"> | null | undefined = safeStorage()): void {
  try {
    storage?.setItem(VIEW_KEY, view);
  } catch {
    // Storage may be blocked; the overview is simply shown next time.
  }
}

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
