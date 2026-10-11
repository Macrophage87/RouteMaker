/**
 * Go and Plan (UI-CLEANUP, the owner's two ways of using the app, 2026-10-11): "The first is commuting.
 * Basically, I'd want to pull out my phone, type in the destination, and go ... For planning, there's a
 * lot more time and coordination available." Go is the phone's few-steps view (one Where to? box, the
 * best route, Start); Plan is the full panel. Both use the same engine, settings and link.
 *
 * Which view the app opens in (the owner's choices 1 and 2 of 2026-10-11, approving the mockup):
 * - a tab keeps the view it was in (a reload of a Go route stays in Go);
 * - a link with a plan in it (a shared route) opens in Plan;
 * - else My Go's "Open in" (lib/myGo.ts): the account's when signed in, this device's when not. A
 *   press of Go or Plan is that choice, so it is remembered;
 * - else a phone opens in Go and a wider screen in Plan.
 *
 * Pure, so the order is tested without a browser; App reads and writes the two stores.
 */

export type AppMode = "go" | "plan";

/** My Go's "Open in": a view, or "" for by screen size. */
export type OpenIn = "" | AppMode;

/** The tab's own view (sessionStorage): kept across a reload, forgotten with the tab. */
export const TAB_MODE_KEY = "routemaker.tab-mode";

export const MODE_LABEL: Record<AppMode, string> = { go: "Go", plan: "Plan" };

/** What each view is for, said as the switch's description. */
export const MODE_SWITCH_HINT = "Go: type a place and ride. Plan: every tool. Both keep the same route.";

/** The switch's landmark-free group name. */
export const MODE_SWITCH_NAME = "View";

export const OPEN_IN_LABEL: Record<OpenIn, string> = {
  "": "By screen size",
  go: "Go",
  plan: "Plan",
};

/** A line under "Open in" saying what by screen size does. */
export const OPEN_IN_HINT = "By screen size: a phone opens in Go, a wider screen in Plan. A shared link always opens in Plan.";

export function isMode(value: unknown): value is AppMode {
  return value === "go" || value === "plan";
}

interface TabStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function tabStore(): TabStore | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** The tab's own view, if it has one (a refused store has none). */
export function readTabMode(store: TabStore | null = tabStore()): AppMode | null {
  try {
    const value = store?.getItem(TAB_MODE_KEY);
    return isMode(value) ? value : null;
  } catch {
    return null;
  }
}

/** Keep the tab's view for a reload; not kept, the view still holds for this page. */
export function writeTabMode(mode: AppMode, store: TabStore | null = tabStore()): void {
  try {
    store?.setItem(TAB_MODE_KEY, mode);
  } catch {
    // Not kept.
  }
}

export function isOpenIn(value: unknown): value is OpenIn {
  return value === "" || isMode(value);
}

/** Whether the address carries a plan (a shared link): its points or its ride, not only a map position. */
export function hasPlanLink(hash: string): boolean {
  const body = hash.replace(/^#/, "");
  if (!body) return false;
  return body.split("&").some((part) => {
    const key = part.split("=")[0];
    return key === "p" || key === "preset" || key === "loop" || key === "gpx";
  });
}

export interface OpeningInputs {
  /** The tab's own view, if it has one. */
  tab: AppMode | null;
  /** The address carries a plan. */
  planLink: boolean;
  /** My Go's Open in (the account's or this device's). */
  openIn: OpenIn;
  /** The screen is wide (not the phone layout). */
  wide: boolean;
}

/** The view to open in, and why (the why decides whether a later My Go may still change it). */
export function openingMode(inputs: OpeningInputs): { mode: AppMode; by: "tab" | "link" | "my-go" | "screen" } {
  if (inputs.tab) return { mode: inputs.tab, by: "tab" };
  if (inputs.planLink) return { mode: "plan", by: "link" };
  if (inputs.openIn) return { mode: inputs.openIn, by: "my-go" };
  return { mode: inputs.wide ? "plan" : "go", by: "screen" };
}

/**
 * Whether the account's My Go, arriving after the app opened, should move it to that view: only when
 * the view was the screen's or this device's guess, and the rider has not switched since.
 */
export function laterMyGoApplies(by: "tab" | "link" | "my-go" | "screen", switched: boolean): boolean {
  return !switched && (by === "screen" || by === "my-go");
}

/** What a switch says, politely, once the view has changed. */
export function modeSaid(mode: AppMode): string {
  return mode === "go" ? "Go: type a place, then Start." : "Plan: the full planner.";
}
