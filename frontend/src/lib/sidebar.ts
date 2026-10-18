/**
 * The sidebar redesign's decisions (OWNER-DECISIONS 312, mockup v3), kept out of
 * App.tsx so they are tested without a browser: what the bottom bar offers, what
 * each of its sheets is called, the one-line lede over the points, the tips'
 * toggle words, "Copy link", and where the focus goes when the panel changes
 * view or the points compact.
 */
import { ACCESS_SENTENCE_WHERE } from "./accessMode.ts";
import { encodePlan } from "./planHash.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";

/**
 * The views the panel body shows: the planner (Plan's sections, or Go's sheet), or one of the sheets
 * the bottom bar, the map's chips, Go's Menu and the Layers sheet's Legend button open (UI-CLEANUP,
 * the approved mockup of 2026-10-11).
 */
export type PanelView = "planner" | "layers" | "legend" | "suggest" | "review" | "gpx" | "settings" | "nearest" | "food" | "ride" | "repair" | "places" | "points";

/** The planner's own heading, where the focus goes when the Plan button returns to it (OWNER-DECISIONS 392). */
export const PLANNER_TITLE = "RouteMaker";

/** The sheets' headings (the focus goes to it on open). Go shows Settings as its Menu. */
export const SHEET_TITLES: Record<Exclude<PanelView, "planner">, string> = {
  layers: "Layers",
  legend: "Legend",
  suggest: "Suggest a change",
  review: "Review",
  // Save and load (the owner, 2026-10-18: "the files tab (maybe call it save or load)"): files, Save, Share, your routes.
  gpx: "Save and load",
  settings: "Settings",
  nearest: "Nearest",
  food: "Find food",
  ride: "Ride",
  // v0.7.0: Go's Repair (behind More), and Plan's Places to see (Go calls it Sights).
  repair: "Repair stands and bike shops",
  places: "Places to see",
  // Go's Edit route (edit-route redesign, Stephen 2026-10-18): Plan's points, from the route card.
  points: "Edit route",
};

/** The Files sheet's name on its buttons (the owner, 2026-10-18), short enough for the bar. */
export const SAVE_LOAD = "Save & load";

/** Go's Menu (the mockup's Menu sheet): Settings, with Plan, Suggest, GPX and Review above them. */
export const MENU_TITLE = "Menu";

export interface BarItem {
  /** The button's own id, for the focus on the way back. */
  id: "plan" | "layers" | "suggest" | "gpx" | "settings";
  /** Its text, always shown beside the icon. */
  label: string;
  /** The view it opens: a sheet, or the planner (Plan). */
  opens: PanelView;
  /** What a screen reader hears besides the label. */
  description: string;
}

/**
 * Plan, Layers, Suggest, GPX and Settings (OWNER-DECISIONS 392, 393: Plan is first, the way back to the
 * planner from any sheet). UI-CLEANUP (the owner's choice 6 of 2026-10-11): the legend moved behind a
 * Legend button at the top of Layers, and Suggest took its slot: the one way in to the suggest tools.
 */
export const BAR_ITEMS: readonly BarItem[] = [
  { id: "plan", label: "Plan", opens: "planner", description: "Shows the planner: the points, the ride settings and the route." },
  { id: "layers", label: "Layers", opens: "layers", description: "Opens the map layers and their switches; the legend is behind its Legend button." },
  { id: "suggest", label: "Suggest", opens: "suggest", description: "Opens the ways to suggest a change to the map, or report a problem to DC 311." },
  { id: "gpx", label: SAVE_LOAD, opens: "gpx", description: "Opens Save and load: save or share the route, find your routes, or open or export a route file." },
  { id: "settings", label: "Settings", opens: "settings", description: "Opens the settings: display, Ride mode and your account." },
];

/** The sheets a bar button counts as its own: Layers holds the legend, Suggest the review. */
const BAR_SHEETS: Record<BarItem["id"], readonly PanelView[]> = {
  plan: ["planner"],
  layers: ["layers", "legend"],
  suggest: ["suggest", "review"],
  gpx: ["gpx"],
  settings: ["settings"],
};

/** Whether a bar button is the current one: the view showing is its sheet, or a sheet inside it. Pure, so a test runs it over every view and button. */
export function barCurrent(item: Pick<BarItem, "id">, view: PanelView): boolean {
  return BAR_SHEETS[item.id].includes(view);
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

/** The Traffic stress section's status line while the stress tiles are checked, or down. */
export const STRESS_CHECKING = "Checking the stress map…";
export const STRESS_UNAVAILABLE = "Stress map unavailable for now. Routes still give their stress.";

export const MORE_TIPS = "More tips";
export const FEWER_TIPS = "Fewer tips";

/**
 * The one line over the points, until there is a start; the full how-to is behind "More tips" (emptyPlanHint).
 * The keyboard's way in is said here too, as loneStartHint says it (the a11y review's S6).
 */
export function searchLede(loop: boolean, accessMode = false): string {
  // Map tools exists only in accessibility mode (455): off, the line says how to get it.
  const how = accessMode ? "Search, click the map, or use Add point at map center in Map tools" : "Search or click the map";
  const end = loop ? "start, then stops. The ride comes back to the start." : "start, then end. Later clicks add stops.";
  return `${how}: ${end}${accessMode ? "" : ` ${ACCESS_SENTENCE_WHERE}`}`;
}

/**
 * The Ride settings line's visible action: Adjust while closed, Done while open (edit-route redesign, Stephen
 * 2026-10-18: "Edit" beside a row of chips read as a tag, not a button). Its state is read from aria-expanded.
 */
export function rideActionLabel(open: boolean): string {
  return open ? "Done" : "Adjust";
}

/** The Ride settings line's action as a screen reader hears it: the same word whatever the state (aria-expanded says that). */
export const RIDE_ACTION_SPOKEN = "Adjust";

/** The Ride settings line's label, over its summary. */
export const RIDE_SETTINGS_LABEL = "Ride settings";

export const COPY_LINK = "Copy link";
export const COPY_LINK_DONE = "Link copied.";
export const COPY_LINK_FAILED = "Could not copy. Copy the address from the browser's address bar.";

/** What "Copy link" said after a press: done or not. */
export function linkSaidFor(done: boolean): string {
  return done ? COPY_LINK_DONE : COPY_LINK_FAILED;
}

/**
 * What a screen reader hears after a press: the same, and when the link
 * includes the rider's location (OWNER-DECISIONS 395) that one line too, said
 * at the moment of sharing: "Link copied. This link includes your location as
 * the start." The visible text stays the first sentence; the note shows below.
 */
export function linkSpokenFor(done: boolean, note: string): string {
  return done && note ? `${COPY_LINK_DONE} ${note}` : linkSaidFor(done);
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
  vias: readonly number[] = [],
): string {
  return `${location.origin}${location.pathname}${location.search}${encodePlan(points, preset, dials, vias)}`;
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
 * heading list: the a11y review's S5) and whether it starts open. Since UI-CLEANUP
 * (the approved mockup of 2026-10-11) every fold is one closed line with its count
 * on the right, so the route's top fits without scrolling (Directions remembers
 * its own state).
 */
export const ROUTE_FOLDS = {
  // The route chart (OWNER-DECISIONS 322, 323), in the elevation slot; App closes it on a small screen. Its title
  // on a Mass Ride is "Riders per minute, corker load and elevation" (profileChart.ts foldName), three charts.
  // UI-CLEANUP (the owner's choice 7 of 2026-10-11): renamed "Elevation and climbs", with the climbs on the
  // route listed in it, and closed by default on a computer too.
  elevation: { title: "Elevation and climbs", open: false },
  facilities: { title: "Stress and facilities", open: false },
  directions: { title: "Directions", open: false },
  junctions: { title: "Junctions to watch", open: false },
  // The mockup's "Other routes", closed like the rest (the route shown is the first; a choice is one press in).
  choices: { title: "Other routes", open: false },
  water: { title: "Water and restrooms", open: false },
} as const;

/** Whether the route chart's fold starts open: closed everywhere since UI-CLEANUP (the owner's choice 7; it was open beside the map, OWNER-DECISIONS 322). */
export function chartFoldOpen(narrow: boolean): boolean {
  return ROUTE_FOLDS.elevation.open && !narrow;
}

// ---- Where the focus goes ---------------------------------------------------------

/**
 * Why the panel changed view: a bar button or another opener (a map chip, Go's Menu, the Legend
 * button), Back (or Escape), the Plan button (planButton, which focuses the heading), the phone
 * header's "Show planner" (panelToggle, which leaves the focus on the toggle), or a question or error
 * that needs the planner.
 */
export type ViewCause = "bar" | "back" | "error" | "confirm" | "planButton" | "panelToggle";

/** What takes the focus after the panel changes view. */
export type FocusTarget =
  | { kind: "heading"; view: Exclude<PanelView, "planner"> }
  | { kind: "opener" }
  | { kind: "error" }
  | { kind: "plan" }
  | { kind: "planner" }
  | null;

/**
 * Where the focus goes when the panel body changes view (App.tsx). A sheet opened takes it to its
 * heading. Back takes it to what opened the sheet (a bar button, a map chip, the Legend button), the
 * sheet it was opened from showing again; the Plan button takes it to the planner's heading
 * (OWNER-DECISIONS 392). An error that brought the planner back takes it to the error, and the
 * long-ride question to its "Plan it" button. No change of view moves nothing.
 */
export function focusOnViewChange(change: { was: PanelView; view: PanelView; cause: ViewCause }): FocusTarget {
  const { was, view, cause } = change;
  if (was === view) return null;
  if (cause === "back") return { kind: "opener" };
  if (view !== "planner") return { kind: "heading", view };
  if (cause === "error") return { kind: "error" };
  if (cause === "confirm") return { kind: "plan" };
  if (cause === "planButton") return { kind: "planner" };
  // The phone header's "Show planner" leaves the focus on the toggle that was pressed.
  if (cause === "panelToggle") return null;
  return { kind: "opener" };
}

/** One step of the way back: the view that was showing and what opened the next one. */
export interface Opened<E> {
  from: PanelView;
  opener: E | null;
}

/**
 * The way back through the sheets (Layers, then its Legend; Suggest, then Review): opening from the
 * planner starts it again, opening from a sheet adds a step, and Back takes one off. Pure, so the order
 * is tested.
 */
export function openOnto<E>(stack: readonly Opened<E>[], from: PanelView, opener: E | null, nested: boolean): Opened<E>[] {
  return nested && from !== "planner" ? [...stack, { from, opener }] : [{ from: "planner", opener }];
}

export function backFrom<E>(stack: readonly Opened<E>[]): { view: PanelView; opener: E | null; stack: Opened<E>[] } {
  const last = stack[stack.length - 1];
  if (!last) return { view: "planner", opener: null, stack: [] };
  return { view: last.from, opener: last.opener, stack: stack.slice(0, -1) };
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
 * When a route arrives the points compact, hiding the search and the point
 * tools. If the focus was in them, it would drop to the page
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
