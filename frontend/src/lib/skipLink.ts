/**
 * The skip link at the top of the page (a11y review of integrate-2; OWNER-DECISIONS
 * 220). The map comes first in the page, and every junction marker on it is a
 * tab stop (up to MAX_ON_MAP, 150), so a keyboard rider could press Tab a
 * hundred times and more before reaching the planner.
 *
 * Why a skip link rather than taking the markers out of the tab order: the
 * markers are where a sighted keyboard rider sees the junctions, and a card
 * opened from one gives the focus back to it; a screen-reader rider has the
 * list in the summary, which says the same, and both get past the map in one
 * key press. The link is the first stop and shows when it has the focus.
 *
 * It does not change the address: the plan lives in the fragment (planHash.ts),
 * and "#route-planner" there would be read as a plan. So the link moves the
 * focus itself.
 */

export const SKIP_LINK_TEXT = "Skip to the route planner";

/** The parts of the link's click and of the planner this uses. */
export interface SkipEvent {
  preventDefault(): void;
}
export interface Focusable {
  focus(options?: { preventScroll?: boolean }): void;
}

/** Take the focus to the planner, leaving the address as it is; whether it went. */
export function skipToPlanner(event: SkipEvent, planner: Focusable | null): boolean {
  event.preventDefault();
  if (!planner) return false;
  planner.focus();
  return true;
}
