/**
 * The planner panel's decisions, kept out of App.tsx so they can be tested
 * without a browser (the lane has no DOM test harness; these were proven only
 * by screenshots before).
 *
 * On a phone the panel is a bottom sheet over half the screen, and the rider
 * often hides it to see the map. The long-ride question and every error are
 * in its Route section, so a hidden sheet opens for them; and whatever needs
 * the rider - a route that is showing, a question, an error - comes first in
 * it, where the sheet opens, rather than below the ride types.
 */

export type StatusKind = "idle" | "loading" | "waiting" | "ok" | "error" | "confirm";
export type SheetSection = "presets" | "points" | "route";

/** A question or an error: something a hidden sheet must open to show. */
export function opensSheet(kind: StatusKind): boolean {
  return kind === "confirm" || kind === "error";
}

/**
 * The order of the panel's first three sections: the points first, then the ride settings (the
 * "presets" section: the Ride line), then the route (OWNER-DECISIONS 312). A desktop's never changes.
 */
export function sheetOrder(narrow: boolean, kind: StatusKind, hasRoute: boolean): SheetSection[] {
  return narrow && (hasRoute || opensSheet(kind)) ? ["route", "points", "presets"] : ["points", "presets", "route"];
}

/** The long-ride question takes the focus, once the sheet is open: a hidden button cannot take it. */
export function focusesPlanButton(kind: StatusKind, panelOpen: boolean): boolean {
  return kind === "confirm" && panelOpen;
}

/** The key that answers the long-ride question with Cancel. */
export function isCancelKey(key: string): boolean {
  return key === "Escape";
}
