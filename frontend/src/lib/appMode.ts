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

import { coordinatesText } from "./geocode.ts";
import { LOCATE_MESSAGES, type LocateFailure } from "./geolocation.ts";
import type { LonLat } from "./geo.ts";

/**
 * Review (the owner, 2026-10-16: "Basically we'd have 3 modes for people who have admin access go/plan/review") is
 * the third, offered to an instance admin only (a closures reviewer too): its queues of roads to rule on
 * (ReviewMode.tsx). Everyone else has exactly Go and Plan.
 */
export type AppMode = "go" | "plan" | "review";

/** My Go's "Open in": Go or Plan, or "" for by screen size (Review is remembered on the device: readLastReview). */
export type OpenIn = "" | "go" | "plan";

/** The tab's own view (sessionStorage): kept across a reload, forgotten with the tab. */
export const TAB_MODE_KEY = "routemaker.tab-mode";

export const MODE_LABEL: Record<AppMode, string> = { go: "Go", plan: "Plan", review: "Review" };

/** What each view is for, said as the switch's description. */
export const MODE_SWITCH_HINT = "Go: type a place and ride. Plan: every tool. Both keep the same route.";
/** The same with Review, for an admin. */
export const MODE_SWITCH_HINT_REVIEW = `${MODE_SWITCH_HINT} Review: roads waiting for your ruling.`;

/** The views the switch offers: Review only to someone who may review. */
export function switchModes(canReview: boolean): AppMode[] {
  return canReview ? ["go", "plan", "review"] : ["go", "plan"];
}

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
  return value === "go" || value === "plan" || value === "review";
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
  return value === "" || value === "go" || value === "plan";
}

/** Whether this device last left the app in Review (localStorage; Review is not one of My Go's choices). */
export const LAST_REVIEW_KEY = "routemaker.last-review";

interface DeviceStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function deviceStore(): DeviceStore | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readLastReview(store: DeviceStore | null = deviceStore()): boolean {
  try {
    return store?.getItem(LAST_REVIEW_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeLastReview(on: boolean, store: DeviceStore | null = deviceStore()): void {
  try {
    if (on) store?.setItem(LAST_REVIEW_KEY, "1");
    else store?.removeItem(LAST_REVIEW_KEY);
  } catch {
    // Not kept.
  }
}

/**
 * Whether the app, once it knows the account may review, moves to Review: the device was last left in it, and the
 * view opened was the screen's or My Go's guess (a tab's own view or a shared link wins), with no switch since.
 */
export function reopenReview(state: { lastReview: boolean; canReview: boolean; by: "tab" | "link" | "my-go" | "screen"; switched: boolean; mode: AppMode }): boolean {
  return state.lastReview && state.canReview && !state.switched && state.mode !== "review" && (state.by === "screen" || state.by === "my-go");
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
  if (mode === "review") return "Review: roads waiting for your ruling.";
  return mode === "go" ? "Go: type a place, then Start." : "Plan: the full planner.";
}

// ---- Go's start (the owner, 2026-10-11 19:53 UTC: "in go, make the current location the starting location by default") ----

/** Where Go's start stands: looking, the rider's location found, not available, or not asked yet. */
export type GoStart = { kind: "idle" } | { kind: "locating" } | { kind: "here"; point: [number, number] } | { kind: "none" };

/** Said politely when the location becomes the start, and shown on Go's start line. */
export const GO_START_SAID = "Start: your current location.";
/** Said politely (and shown) when the location could not be had: denied, unavailable or timed out. */
export const GO_START_UNAVAILABLE = "Current location not available; type a start.";

/**
 * Whether Go asks for the location now: only in Go (never in Plan), once per page, and only while the plan
 * has no point, so a start from the link (or one typed first) wins.
 */
export function shouldAskGoStart(state: { mode: AppMode; asked: boolean; pointCount: number }): boolean {
  return state.mode === "go" && !state.asked && state.pointCount === 0;
}

/**
 * Go's start line: the plan's own first point when there is one (from the link or typed: it replaces
 * the location), else the location, else what is happening.
 */
export function goStartLine(start: GoStart, firstPointName: string | null): string {
  if (firstPointName !== null) return `Start: ${firstPointName}`;
  if (start.kind === "here") return "Start: your current location";
  if (start.kind === "locating") return "Start: finding your location…";
  return "Start: none yet; type a start";
}

/** The start Go routes from: the plan's first point, else the location found; null when there is neither. */
export function goRouteStart(points: readonly [number, number][], start: GoStart): { point: [number, number]; located: boolean } | null {
  if (points.length > 0) return { point: points[0], located: false };
  if (start.kind === "here") return { point: start.point, located: true };
  return null;
}

/**
 * What a destination picked in Go does (review of PR #95): route at once from the start Go has; wait while the
 * location is still being found (the pick is kept and routed when it comes, never dropped); or, with no
 * location, look it up once more and, failing that, keep the destination and ask for a start (the start box),
 * so the destination is never made the start.
 */
export type GoPick = { kind: "route"; point: [number, number]; located: boolean } | { kind: "wait" } | { kind: "locate" };

export function goPickAction(points: readonly [number, number][], start: GoStart): GoPick {
  const known = goRouteStart(points, start);
  if (known !== null) return { kind: "route", ...known };
  return start.kind === "locating" ? { kind: "wait" } : { kind: "locate" };
}

/** Shown and said while a picked destination waits for the location. */
export function goDestinationLocating(name: string): string {
  return `To ${name}: finding your location for the start…`;
}

/** Shown and said when a picked destination has no start: the location is not available. */
export function goDestinationNeedsStart(name: string): string {
  return `To ${name}. ${GO_START_UNAVAILABLE}`;
}

/**
 * What a map press does in Go (the owner, 2026-10-12: "When on Go mode, make it so the location you press is the
 * end"): a press on the open map (or the keyboard's Set destination at map center) is the destination, in place of
 * any destination before it, and is routed as a destination picked in the search is (goPickAction): from the start
 * Go has, else it waits for one. A press on a station, a place's letter or a water stop still opens its card. In
 * Plan a press adds a point as before. This replaces the tap that was the start of a waiting destination (PR #95's
 * follow-up review): with no location, the start is typed in the start box.
 */
export function goTapSetsEnd(mode: AppMode): boolean {
  return mode === "go";
}

/** A point that is the rider's location, as Go's route card and the points list name it (edit-route redesign). */
export const YOUR_LOCATION = "Your location";

/**
 * Go's name for a destination, the same in what is said and on the sheet's "To …": its place name once known (a
 * pressed spot's is looked up after it is placed, and the sheet takes it when it comes), else its coordinates.
 */
export function goPlaceName(name: string | undefined, point: LonLat): string {
  return name ?? coordinatesText(point);
}

/** Said when a press on the map sets Go's destination: an essential, said at Brief and at Full. */
export function goDestinationSet(name: string): string {
  return `Destination set: ${name}.`;
}

/**
 * Said when a pressed destination has no start and must wait: "Destination set" and what it waits for, in one
 * announcement. Said apart, the second replaced the first in the live region a moment later (about 140 ms with
 * the location denied), so a screen reader could miss the essential part.
 */
export function goPressLocatingSaid(name: string): string {
  return `${goDestinationSet(name)} Finding your location for the start…`;
}

/**
 * Why Go's Locate could not find the rider, for a destination waiting on it: Locate's own reason (what to allow or
 * try), ending in typing a start, as the start box asks, in place of searching for a place.
 */
export function goStartFailedReason(reason: LocateFailure): string {
  return LOCATE_MESSAGES[reason].replace(/search for a place\.$/, "type a start.").replace(/Search for a place instead\.$/, "Type a start instead.");
}

/** Shown when a destination waited on Go's Locate and it failed: the destination and Locate's reason. */
export function goDestinationNeedsStartBecause(name: string, reason: LocateFailure): string {
  return `To ${name}. ${goStartFailedReason(reason)}`;
}

/** Said when a pressed destination waited on Go's Locate and it failed: one announcement, as goPressNeedsStartSaid. */
export function goPressNeedsStartBecause(name: string, reason: LocateFailure): string {
  return `${goDestinationSet(name)} ${goStartFailedReason(reason)}`;
}

/**
 * How long Go's look-up for a pressed destination may take before the press is said with "Finding your location for
 * the start…": a denial answers well inside it and is said once ("Current location not available"); a slow fix or a
 * timeout (up to a minute) is not left silent.
 */
export const GO_PRESS_LOCATING_SAY_MS = 1000;

/** Said when a pressed destination has no start and the location is not available: one announcement, as above. */
export function goPressNeedsStartSaid(name: string): string {
  return `${goDestinationSet(name)} ${GO_START_UNAVAILABLE}`;
}

/**
 * What is said when a pressed destination is routed at once: at Full the extra "Planning a route" narration
 * follows it in the same sentence (one announcement, so neither is lost); at Brief only the destination.
 */
export function goTapRoutedSaid(name: string, located: boolean, full: boolean): string {
  const set = goDestinationSet(name);
  return full ? `${set} Planning a route from ${located ? "your location" : "your start"}.` : set;
}
