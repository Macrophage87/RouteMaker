/**
 * The sidebar redesign's decisions (OWNER-DECISIONS 312, mockup v3), kept out of
 * App.tsx so they are tested without a browser: what the bottom bar offers, what
 * each of its sheets is called, the one-line lede over the points, the tips'
 * toggle words, "Copy link", and where the focus goes when the panel changes
 * view or the points compact.
 */
import { encodePlan } from "./planHash.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";

/** The views the panel body shows: the planner, or one of the bottom bar's sheets. */
export type PanelView = "planner" | "layers" | "gpx" | "settings";

/** The planner's own heading, where the focus goes when the Plan button returns to it (OWNER-DECISIONS 392). */
export const PLANNER_TITLE = "RouteMaker";

/** The sheets, and where each one's heading is (the focus goes to it on open). */
export const SHEET_TITLES: Record<Exclude<PanelView, "planner">, string> = {
  layers: "Map layers",
  gpx: "GPX file",
  settings: "Settings",
};

export interface BarItem {
  /** The button's own id, for the focus on the way back. */
  id: "plan" | "layers" | "legend" | "gpx" | "settings";
  /** Its text, always shown beside the icon. */
  label: string;
  /** The view it opens: a sheet, or the planner (Plan). */
  opens: PanelView;
  /** Whether the sheet opens scrolled to the legend. */
  toLegend?: boolean;
  /** What a screen reader hears besides the label. */
  description: string;
}

/**
 * Plan, Map layers, Legend, GPX and Settings (OWNER-DECISIONS 392, 393: Plan is first, the way back to
 * the planner from any sheet; 384: Settings was "About" until then). The Settings sheet holds the sign-in note and a Display group with the
 * High contrast switch; nothing else is there, so no fake settings.
 */
export const BAR_ITEMS: readonly BarItem[] = [
  { id: "plan", label: "Plan", opens: "planner", description: "Shows the planner: the points, the ride settings and the route." },
  { id: "layers", label: "Map layers", opens: "layers", description: "Opens the map layers and their switches." },
  { id: "legend", label: "Legend", opens: "layers", toLegend: true, description: "Opens the map legend, in the map layers." },
  { id: "gpx", label: "GPX", opens: "gpx", description: "Opens the GPX file tools: open a file, or download the route." },
  { id: "settings", label: "Settings", opens: "settings", description: "Opens the settings: display options and signing in." },
];

/**
 * Whether a bar button is the current one: its sheet is the view showing, and of the two buttons
 * that open Map layers only the one that did (Legend, or Map layers). Pure, so a test runs it over
 * every view and button (the mutation re-check's NIT A).
 */
export function barCurrent(item: Pick<BarItem, "id" | "opens">, view: PanelView, legend: boolean): boolean {
  return view === item.opens && (item.id !== "layers" || !legend) && (item.id !== "legend" || legend);
}

/** The sheets' Back button, in words, not only an arrow (OWNER-DECISIONS 393). */
export const BACK_LABEL = "Back to planner";

/** The bottom bar's landmark name: the pages of the panel it switches between. */
export const BAR_NAME = "Panel pages";

/**
 * Parts built and ready to place, both decided OFF (OWNER-DECISIONS 384, items 3 and 4);
 * flip a flag to show one in the planner.
 * - `zoomNotice`: the one-line zoom notice ("Zoom in to see traffic stress on
 *   roads...") over the points; the notice lives in the Map layers sheet.
 * - `highContrastShortcut`: the High contrast on/off in the planner; the switch is
 *   in the Map layers sheet and the Settings sheet.
 */
export const PLANNER_EXTRAS = { zoomNotice: false, highContrastShortcut: false } as const;

/** The line in the Map layers sheet for every ride type but Mass Ride (mockup v3, Layers). */
export const MASS_RIDE_LAYERS_NOTE = "Mass Ride has its own layers, such as federal land.";

export const MORE_TIPS = "More tips";
export const FEWER_TIPS = "Fewer tips";

/**
 * The one line over the points, until there is a start; the full how-to is behind "More tips" (emptyPlanHint).
 * The keyboard's way in is said here too, as loneStartHint says it (the a11y review's S6).
 */
export function searchLede(loop: boolean): string {
  return loop
    ? "Search, click the map, or use Add point at map center: start, then stops. The ride comes back to the start."
    : "Search, click the map, or use Add point at map center: start, then end. Later clicks add stops.";
}

/** The Ride line's visible action: Edit while closed, Done while open. Its state is read from aria-expanded. */
export function rideActionLabel(open: boolean): string {
  return open ? "Done" : "Edit";
}

/** The Ride line's action as a screen reader hears it: the same word whatever the state (aria-expanded says that). */
export const RIDE_ACTION_SPOKEN = "Edit";

export const COPY_LINK = "Copy link";
export const COPY_LINK_DONE = "Link copied.";
export const COPY_LINK_FAILED = "Could not copy. Copy the address from the browser's address bar.";

/** What "Copy link" said after a press: done or not. */
export function linkSaidFor(done: boolean): string {
  return done ? COPY_LINK_DONE : COPY_LINK_FAILED;
}

/**
 * What "Copy link" copies: this page's address with the plan built afresh by
 * encodePlan (planHash.ts), the same fragment App writes to the address bar.
 * It carries the points, the ride type and the sliders, and never the rider and
 * bike weight (OWNER-DECISIONS 313): the weight is kept apart from `dials`, and
 * nothing here reads where it is stored.
 */
export function linkToCopy(
  location: { origin: string; pathname: string; search: string },
  points: readonly LonLat[],
  preset: PresetId,
  dials: Dials,
): string {
  return `${location.origin}${location.pathname}${location.search}${encodePlan(points, preset, dials)}`;
}

/** The surface "Copy link" uses: the async clipboard where there is one, else the selection method. */
export interface ClipboardLike {
  writeText?: (text: string) => Promise<void>;
}

export async function copyText(
  text: string,
  clipboard: ClipboardLike | undefined,
  fallback: (text: string) => boolean,
): Promise<boolean> {
  try {
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the selection method.
  }
  try {
    return fallback(text);
  } catch {
    return false;
  }
}

/** The selection method, in the page (a textarea, execCommand), for a browser with no async clipboard. */
export function selectionCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const done = document.execCommand("copy");
  area.remove();
  return done;
}

/** A fold's summary text with its count: "Directions (12 steps)", "Junctions to watch (4)". */
export function foldTitle(title: string, count: string | number | null): string {
  return count === null ? title : `${title} (${count})`;
}

export function stepsCount(n: number): string {
  return n === 1 ? "1 step" : `${n} steps`;
}

/**
 * The route summary's folds: each one's heading (an h3, for a screen reader's
 * heading list: the a11y review's S5) and whether it starts open. "Routes to
 * choose from" is open, because it changes which route is shown; the others
 * are closed (Directions remembers its own state).
 */
export const ROUTE_FOLDS = {
  facilities: { title: "Stress and facilities", open: false },
  directions: { title: "Directions", open: false },
  junctions: { title: "Junctions to watch", open: false },
  choices: { title: "Routes to choose from", open: true },
} as const;

// ---- Where the focus goes ---------------------------------------------------------

/**
 * Why the panel changed view: a bar button, Back (or Escape), the Plan button (planButton, which
 * focuses the heading), the phone header's "Show planner" (panelToggle, which leaves the focus on the
 * toggle), or a question or error that needs the planner.
 */
export type ViewCause = "bar" | "back" | "error" | "confirm" | "planButton" | "panelToggle";

/** What takes the focus after the panel changes view. */
export type FocusTarget =
  | { kind: "heading"; view: Exclude<PanelView, "planner">; legend: boolean }
  | { kind: "bar"; id: BarItem["id"] }
  | { kind: "error" }
  | { kind: "plan" }
  | { kind: "planner" }
  | null;

/**
 * Where the focus goes when the panel body changes view (App.tsx). A sheet takes
 * it to its heading (the legend's, when Legend opened it). Back takes it to the
 * bar button that opened the sheet; the Plan button takes it to the planner's heading
 * (OWNER-DECISIONS 392). An error that brought the planner back takes
 * it to the error, and the long-ride question to its "Plan it" button. No change
 * of view moves nothing.
 */
export function focusOnViewChange(change: {
  was: PanelView;
  view: PanelView;
  legendTarget: boolean;
  openedBy: BarItem["id"];
  cause: ViewCause;
}): FocusTarget {
  const { was, view, legendTarget, openedBy, cause } = change;
  if (was === view) return null;
  if (view !== "planner") return { kind: "heading", view, legend: view === "layers" && legendTarget };
  if (cause === "error") return { kind: "error" };
  if (cause === "confirm") return { kind: "plan" };
  if (cause === "planButton") return { kind: "planner" };
  // The phone header's "Show planner" leaves the focus on the toggle that was pressed.
  if (cause === "panelToggle") return null;
  return { kind: "bar", id: openedBy };
}

/** The parts of a key event the sheet's Escape handler reads. */
export interface SheetKeyEvent {
  key: string;
  defaultPrevented: boolean;
  target: { closest(selector: string): unknown; getAttribute(name: string): string | null } | null;
  preventDefault(): void;
}

/**
 * A sheet's Escape: back to the planner, unless it was already handled, or it
 * came from a nested dialog (the weight dialog) or the place search's list,
 * whose own Escape it is. True when it went back.
 */
export function sheetEscape(event: SheetKeyEvent, onBack: () => void): boolean {
  if (event.key !== "Escape" || event.defaultPrevented) return false;
  const target = event.target;
  if (target && (target.closest("dialog") || target.getAttribute("role") === "combobox")) return false;
  event.preventDefault();
  onBack();
  return true;
}

/**
 * Whether the points notice must be said through the app-level live region: when there is one and the
 * planner, whose own status shows it, is hidden (a bar sheet, or the phone's sheet closed). With the
 * planner shown its own region says it, so it is not said twice.
 */
export function noticeSaidElsewhere(notice: string | null, plannerShown: boolean): boolean {
  return notice !== null && notice !== "" && !plannerShown;
}

/** The parts of an element the compact points' focus rescue reads. */
export interface FocusContainer {
  contains(node: unknown): boolean;
}

/**
 * When a route arrives the points compact, hiding the search, Add point at map
 * center and the tools. If the focus was in them, it would drop to the page
 * (a hidden element cannot hold it): it goes to "Edit points" instead, which
 * opens them again (the review's B1). True when it moved the focus.
 */
export function rescueCompactFocus(state: {
  wasCompact: boolean;
  compact: boolean;
  /** What had the focus before the render that compacted the points. */
  before: unknown;
  /** The parts that are hidden while compact. */
  hidden: ReadonlyArray<FocusContainer | null>;
  editPoints: { focus(): void } | null;
}): boolean {
  const { wasCompact, compact, before, hidden, editPoints } = state;
  if (!compact || wasCompact || before === null || editPoints === null) return false;
  if (!hidden.some((part) => part !== null && part.contains(before))) return false;
  editPoints.focus();
  return true;
}
